//! `pythia`: the command line for a running Pythia engine.
//!
//! It talks to the same HTTP API the web UI uses, so everything it shows is
//! what the engine itself reports, and everything it changes goes through the
//! engine's own checks. `pythia serve` starts the engine (`pythia-server`,
//! shipped next to this binary) for machines without a desktop.
//!
//! The engine address comes from `--url` or `PYTHIA_URL` and defaults to the
//! server's own default, `http://127.0.0.1:8787`.

use clap::{Parser, Subcommand};
use serde_json::{json, Value};
use std::io::Write;
use std::process::ExitCode;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

#[derive(Parser)]
#[command(name = "pythia", version, about = "Watch and steer a Pythia engine from the terminal.")]
struct Cli {
    /// Engine address.
    #[arg(long, env = "PYTHIA_URL", default_value = "http://127.0.0.1:8787", global = true)]
    url: String,
    /// Print the engine's raw JSON instead of a table.
    #[arg(long, global = true)]
    json: bool,
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    /// Engine mode, kill switch, account and a line per autopilot.
    Status,
    /// List the autopilots (running and paused; --all adds stopped ones).
    #[command(visible_alias = "ls")]
    Autopilots {
        #[arg(long)]
        all: bool,
    },
    /// Everything about one autopilot.
    Show { id: String },
    /// Pause an autopilot: it keeps its positions but places no orders.
    Pause { id: String },
    /// Resume a paused autopilot.
    Resume { id: String },
    /// Stop an autopilot. By default it follows its own flatten setting.
    Stop {
        id: String,
        /// Close its positions.
        #[arg(long, conflicts_with = "keep")]
        flatten: bool,
        /// Keep its positions open.
        #[arg(long)]
        keep: bool,
    },
    /// Switch the kill switch on or off. Asks first unless --yes.
    Kill {
        #[arg(long)]
        yes: bool,
    },
    /// What blocks a paper or live run, one check per line.
    Preflight,
    /// Print the status again every few seconds until Ctrl+C.
    Watch {
        #[arg(long, default_value_t = 10)]
        every: u64,
    },
    /// Start the engine (pythia-server) in this terminal. Arguments after
    /// `--` go to the server; settings come from the environment or a .env.
    Serve {
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        args: Vec<String>,
    },
}

struct Api {
    base: String,
    http: reqwest::blocking::Client,
}

impl Api {
    fn new(url: &str) -> Self {
        let http = reqwest::blocking::Client::builder()
            .timeout(Duration::from_secs(30))
            .user_agent(concat!("pythia-cli/", env!("CARGO_PKG_VERSION")))
            .build()
            .expect("http client");
        Self { base: url.trim_end_matches('/').to_string(), http }
    }

    fn get(&self, path: &str) -> Result<Value, String> {
        let resp = self.http.get(format!("{}{path}", self.base)).send().map_err(|e| self.unreachable(e))?;
        Self::read(resp)
    }

    fn command(&self, cmd: Value) -> Result<Value, String> {
        let resp = self
            .http
            .post(format!("{}/api/command", self.base))
            .json(&cmd)
            .send()
            .map_err(|e| self.unreachable(e))?;
        Self::read(resp)
    }

    fn read(resp: reqwest::blocking::Response) -> Result<Value, String> {
        let status = resp.status();
        let text = resp.text().unwrap_or_default();
        let body: Value = serde_json::from_str(&text).unwrap_or(Value::Null);
        if status.is_success() {
            return Ok(body);
        }
        // The engine answers a refused command with {"error": ...} or plain text.
        let msg = match body.get("error").and_then(Value::as_str) {
            Some(e) => e.to_string(),
            None if !text.trim().is_empty() && body.is_null() => text.trim().to_string(),
            None => status.to_string(),
        };
        Err(msg)
    }

    fn unreachable(&self, e: reqwest::Error) -> String {
        format!("no engine at {} ({e}). Start one with `pythia serve` or set PYTHIA_URL.", self.base)
    }
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    let api = Api::new(&cli.url);
    let result = match cli.cmd {
        Cmd::Status => api.get("/api/state").map(|s| {
            if cli.json {
                print_json(&s)
            } else {
                print_status(&s)
            }
        }),
        Cmd::Autopilots { all } => api.get("/api/state").map(|s| {
            if cli.json {
                print_json(&s["autopilots"])
            } else {
                print_autopilots(&s, all)
            }
        }),
        Cmd::Show { id } => api.get("/api/state").and_then(|s| {
            let ap = find_autopilot(&s, &id)?;
            if cli.json {
                print_json(ap)
            } else {
                print_autopilot(ap)
            }
            Ok(())
        }),
        Cmd::Pause { id } => steer(&api, json!({ "cmd": "autopilotPause", "id": id }), &id, "paused"),
        Cmd::Resume { id } => steer(&api, json!({ "cmd": "autopilotResume", "id": id }), &id, "resumed"),
        Cmd::Stop { id, flatten, keep } => {
            let mut cmd = json!({ "cmd": "autopilotStop", "id": id });
            if flatten || keep {
                cmd["flatten"] = json!(flatten);
            }
            steer(&api, cmd, &id, "stopped")
        }
        Cmd::Kill { yes } => kill(&api, yes),
        Cmd::Preflight => api.get("/api/preflight").map(|p| {
            if cli.json {
                print_json(&p)
            } else {
                print_preflight(&p)
            }
        }),
        Cmd::Watch { every } => watch(&api, every.max(2)),
        Cmd::Serve { args } => serve(&args),
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("pythia: {e}");
            ExitCode::FAILURE
        }
    }
}

fn steer(api: &Api, cmd: Value, id: &str, done: &str) -> Result<(), String> {
    let state = api.command(cmd)?;
    let ap = find_autopilot(&state, id)?;
    println!("{} {done}. {}", name_of(ap), str_of(&ap["lastAction"]));
    Ok(())
}

fn kill(api: &Api, yes: bool) -> Result<(), String> {
    let state = api.get("/api/state")?;
    let on = state["limits"]["killSwitch"].as_bool().unwrap_or(false);
    let next = if on { "off" } else { "on" };
    if !yes {
        print!("The kill switch is {}. Switch it {next}? [y/N] ", if on { "on" } else { "off" });
        std::io::stdout().flush().ok();
        let mut line = String::new();
        std::io::stdin().read_line(&mut line).ok();
        if !matches!(line.trim(), "y" | "Y" | "yes") {
            println!("Nothing changed.");
            return Ok(());
        }
    }
    let state = api.command(json!({ "cmd": "toggleKill" }))?;
    let now = state["limits"]["killSwitch"].as_bool().unwrap_or(false);
    println!("Kill switch {}.", if now { "on: no new orders" } else { "off" });
    Ok(())
}

fn watch(api: &Api, every: u64) -> Result<(), String> {
    loop {
        let state = api.get("/api/state")?;
        // Clear the screen and go home, so the table redraws in place.
        print!("\x1b[2J\x1b[H");
        print_status(&state);
        println!("\nevery {every}s, Ctrl+C to quit");
        std::thread::sleep(Duration::from_secs(every));
    }
}

/// Run `pythia-server` from the folder this binary lives in, or from PATH.
fn serve(args: &[String]) -> Result<(), String> {
    let exe = if cfg!(windows) { "pythia-server.exe" } else { "pythia-server" };
    let beside = std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.join(exe))).filter(|p| p.exists());
    let program = beside.map(|p| p.into_os_string()).unwrap_or_else(|| exe.into());
    let status = std::process::Command::new(&program)
        .args(args)
        .status()
        .map_err(|e| format!("could not start {} ({e}). It ships next to `pythia` in the release archive.", program.to_string_lossy()))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("pythia-server exited with {status}"))
    }
}

fn find_autopilot<'a>(state: &'a Value, id: &str) -> Result<&'a Value, String> {
    state["autopilots"]
        .as_array()
        .into_iter()
        .flatten()
        .find(|a| a["config"]["id"].as_str() == Some(id))
        .ok_or_else(|| format!("no autopilot `{id}`. `pythia ls --all` lists them."))
}

fn print_json(v: &Value) {
    println!("{}", serde_json::to_string_pretty(v).unwrap_or_default());
}

fn print_status(s: &Value) {
    let p = &s["portfolio"];
    let live = &s["live"];
    let mode = if live["armed"].as_bool() == Some(true) && live["paper"].as_bool() == Some(false) {
        "LIVE"
    } else {
        "paper"
    };
    let kill = if s["limits"]["killSwitch"].as_bool() == Some(true) { "ON" } else { "off" };
    println!("engine    {mode}, kill switch {kill}");
    println!(
        "account   equity {}  cash {}  day {}",
        usd(num(&p["equity"])),
        usd(num(&p["cash"])),
        signed_usd(num(&p["equity"]) - num(&p["dayStartEquity"]))
    );
    if s["dataHealth"]["ok"].as_bool() == Some(false) {
        println!("data      stale: quotes are not arriving");
    }
    println!();
    print_autopilots(s, false);
}

fn print_autopilots(s: &Value, all: bool) {
    let aps: Vec<&Value> = s["autopilots"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|a| all || a["state"].as_str() != Some("stopped"))
        .collect();
    if aps.is_empty() {
        println!("no autopilots{}", if all { "" } else { " running (--all shows stopped ones)" });
        return;
    }
    let rows: Vec<[String; 7]> = aps
        .iter()
        .map(|a| {
            [
                str_of(&a["config"]["id"]),
                name_of(a),
                str_of(&a["state"]),
                format!("{} {}", str_of(&a["config"]["mode"]), str_of(&a["config"]["venue"])),
                usd(num(&a["equity"])),
                pct(a["pnlPct"].as_f64()),
                pct(a["btcReturnPct"].as_f64()),
            ]
        })
        .collect();
    table(&["id", "name", "state", "route", "equity", "p&l", "btc"], &rows);
}

fn print_autopilot(a: &Value) {
    let c = &a["config"];
    println!("{}  ({})", name_of(a), str_of(&c["id"]));
    println!("state       {}", str_of(&a["state"]));
    for (label, key) in [("stop reason", "stopReason"), ("paused", "pausedReason")] {
        if let Some(r) = a[key].as_str() {
            println!("{label:<11} {r}");
        }
    }
    println!("route       {} on {}", str_of(&c["mode"]), str_of(&c["venue"]));
    println!("amount      {}", usd(num(&c["capitalUsd"])));
    println!("equity      {}  ({})", usd(num(&a["equity"])), pct(a["pnlPct"].as_f64()));
    println!("btc         {}", pct(a["btcReturnPct"].as_f64()));
    println!("drawdown    {}", pct(a["drawdownPct"].as_f64().map(|d| -d)));
    println!("positions   {}", num(&a["openPositions"]) as i64);
    println!("trades      {}, fees {}", num(&a["trades"]) as i64, usd(num(&a["fees"])));
    if let Some(ms) = a["startedMs"].as_f64() {
        println!("running     {}", age(ms));
    }
    let sleeves: Vec<String> = c["sleeves"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|sl| format!("{} x{}", str_of(&sl["strategyId"]), num(&sl["weight"])))
        .collect();
    if !sleeves.is_empty() {
        println!("books       {}", sleeves.join(", "));
    }
    let stop = &c["stop"];
    let mut rules = Vec::new();
    if let Some(v) = stop["maxLossPct"].as_f64() {
        rules.push(format!("max loss {v}%"));
    }
    if let Some(v) = stop["takeProfitPct"].as_f64() {
        rules.push(format!("take profit {v}%"));
    }
    if let Some(v) = stop["trailingPct"].as_f64() {
        rules.push(format!("trailing {v}%"));
    }
    if !rules.is_empty() {
        println!("stop rules  {}", rules.join(", "));
    }
    if let Some(last) = a["lastAction"].as_str() {
        println!("\n{last}");
    }
}

fn print_preflight(p: &Value) {
    let checks = p["checks"].as_array().cloned().unwrap_or_default();
    let width = checks.iter().map(|c| str_of(&c["name"]).len()).max().unwrap_or(0);
    for c in &checks {
        let mark = if c["ok"].as_bool() == Some(true) { "ok  " } else { "FAIL" };
        println!("{mark}  {:<width$}  {}", str_of(&c["name"]), str_of(&c["detail"]));
    }
}

fn table<const N: usize>(head: &[&str; N], rows: &[[String; N]]) {
    let mut w = head.map(str::len);
    for r in rows {
        for (i, cell) in r.iter().enumerate() {
            w[i] = w[i].max(cell.chars().count());
        }
    }
    // Text columns left, number columns (the last three) right.
    let line = |cells: Vec<String>| {
        let out: Vec<String> = cells
            .iter()
            .enumerate()
            .map(|(i, c)| if i + 3 >= N { format!("{c:>width$}", width = w[i]) } else { format!("{c:<width$}", width = w[i]) })
            .collect();
        println!("{}", out.join("  ").trim_end());
    };
    line(head.iter().map(|h| h.to_string()).collect());
    for r in rows {
        line(r.to_vec());
    }
}

fn name_of(a: &Value) -> String {
    a["config"]["name"].as_str().or(a["config"]["id"].as_str()).unwrap_or("?").to_string()
}

fn str_of(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Null => "-".into(),
        other => other.to_string(),
    }
}

fn num(v: &Value) -> f64 {
    v.as_f64().unwrap_or(0.0)
}

fn usd(x: f64) -> String {
    let cents = (x.abs() * 100.0).round() as u64;
    let (whole, frac) = (cents / 100, cents % 100);
    let digits = whole.to_string();
    let mut grouped = String::new();
    for (i, ch) in digits.chars().enumerate() {
        if i > 0 && (digits.len() - i) % 3 == 0 {
            grouped.push(',');
        }
        grouped.push(ch);
    }
    format!("{}${grouped}.{frac:02}", if x < 0.0 && cents > 0 { "-" } else { "" })
}

fn signed_usd(x: f64) -> String {
    if x >= 0.0 {
        format!("+{}", usd(x))
    } else {
        usd(x)
    }
}

fn pct(x: Option<f64>) -> String {
    x.map(|v| format!("{v:+.2} %")).unwrap_or_else(|| "-".into())
}

fn age(started_ms: f64) -> String {
    let now = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as f64).unwrap_or(started_ms);
    let mins = ((now - started_ms) / 60_000.0).max(0.0) as u64;
    match mins {
        m if m < 60 => format!("{m} min"),
        m if m < 48 * 60 => format!("{}h {}m", m / 60, m % 60),
        m => format!("{}d {}h", m / 1440, (m % 1440) / 60),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn money_is_grouped_and_signed() {
        assert_eq!(usd(1234567.891), "$1,234,567.89");
        assert_eq!(usd(-47.494), "-$47.49");
        assert_eq!(usd(0.001), "$0.00");
        assert_eq!(signed_usd(12.0), "+$12.00");
    }

    #[test]
    fn finds_an_autopilot_by_id() {
        let s = json!({ "autopilots": [{ "config": { "id": "ap_1", "name": "One" } }] });
        assert_eq!(name_of(find_autopilot(&s, "ap_1").unwrap()), "One");
        assert!(find_autopilot(&s, "ap_2").is_err());
    }
}
