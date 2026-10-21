//! Strategies decided in the research lab and executed here.
//!
//! Python decides, Rust executes. The lab computes a strategy's target weights
//! every day with exactly the code its backtest used and writes them to
//! `signals/<strategy>/latest.json`. This module reads that file, turns the
//! lab's evidence into gates 1 to 6 of the Strategy Passport (with the same
//! thresholds as `validation`), and works out the orders that move a book to
//! its targets. Gate 7 is still earned here, by the engine's own paper record.
//!
//! Nothing in this module places an order; the engine does that, through the
//! same risk manager, passport check and cost model as every other strategy.

use std::collections::{BTreeMap, HashMap};
use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::connectors::Side;
use crate::costs::CostVenue;
use crate::validation::{Figure, Gate, GateStatus, ResearchVerdict, Unit};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LabSignal {
    pub strategy: String,
    pub variant: String,
    /// The daily close the weights were computed from.
    pub as_of_ms: i64,
    pub generated_ms: i64,
    /// After this the signal is stale and the engine holds still.
    pub valid_until_ms: i64,
    pub quote: String,
    /// Coin -> fraction of the strategy's capital. Coins left out are held at zero.
    pub weights: BTreeMap<String, f64>,
    #[serde(default)]
    pub regime_on: Option<bool>,
    #[serde(default)]
    pub evidence: LabEvidence,
    /// The book trades only inside an autopilot, never on its own: the lab
    /// writes this for candidates that overlap a book the engine already
    /// runs, or that have not earned a standalone run (they fail deflation).
    /// Old signals without the field run standalone, as before.
    #[serde(default)]
    pub autopilot_only: bool,
    /// Coins the lab's book holds that Pythia has no market for. They are
    /// left out of `weights`, so that share of the book stays in cash here.
    #[serde(default)]
    pub dropped: Vec<String>,
    /// What the weights' keys name. Absent (every signal so far): coins,
    /// traded as `crypto:<COIN>/USD`. [`US_EQUITY`]: US shares and ETFs,
    /// traded as `alpaca:<SYMBOL>` on Alpaca in the regular session.
    #[serde(default)]
    pub asset_class: Option<String>,
    /// An experiment: a rule that failed the lab's bar (deflation), run on
    /// paper for forward evidence because the owner asked for more risk. It
    /// is autopilot-only whatever `autopilot_only` says, the auto pick never
    /// picks it, a live autopilot never runs it, and every place it shows up
    /// says "experiment". The lab writes the flag here and in the evidence;
    /// either one is enough ([`LabSignal::is_experimental`]).
    #[serde(default)]
    pub experimental: bool,
}

/// [`LabSignal::asset_class`] of a book of US shares and ETFs.
pub const US_EQUITY: &str = "us_equity";

/// [`LabSignal::asset_class`] of a book of perpetual futures: weights may be
/// negative (shorts), keys are coins, traded as `perp:<COIN>` on the perps
/// venue (demo or paper only, see `engine::perps`).
pub const PERP: &str = "perp";

/// What the lab measured for the variant (reports/tsmom, reports/momentum2).
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct LabEvidence {
    #[serde(default)]
    pub report: String,
    #[serde(default)]
    pub missing: Option<bool>,
    pub is_sharpe: Option<f64>,
    pub oos_sharpe: Option<f64>,
    pub oos_max_dd: Option<f64>,
    pub deflated_p: Option<f64>,
    pub sharpe_2x_cost: Option<f64>,
    pub variants_tried: Option<usize>,
    /// Share of the neighbouring variants that were profitable out of sample.
    pub plateau_share: Option<f64>,
    /// How many variants `plateau_share` counts, when that is fewer than
    /// `variants_tried` (the plateau of one sub-family inside a larger sweep).
    #[serde(default)]
    pub plateau_variants: Option<usize>,
    #[serde(default)]
    pub regime_sharpes: BTreeMap<String, f64>,
    #[serde(default)]
    pub regime_filter: bool,
    /// The same rule's out-of-sample Sharpe on a survivorship-free universe,
    /// when the lab has measured it. Lower than `oos_sharpe` means the
    /// headline result leaned on coins that happened to survive.
    #[serde(default)]
    pub oos_sharpe_survivorship_free: Option<f64>,
    /// A known weakness of this evidence, in one plain sentence.
    #[serde(default)]
    pub caveat: Option<String>,
    /// The rule failed the bar and runs as an experiment (see
    /// [`LabSignal::experimental`]).
    #[serde(default)]
    pub experimental: bool,
    /// Why the experiment failed the bar, in the lab's words.
    #[serde(default)]
    pub why_failed: Option<String>,
}

// ── forward evidence ────────────────────────────────────────────────────────

/// A forward result counts in the auto pick only from this many days on.
/// Before that the band is wide and a single day can put it anywhere.
pub const FORWARD_MIN_DAYS: f64 = 10.0;

/// One paper book's (or autopilot's) forward record against its backtest, as
/// `lab.paper.forward_report` writes it to `reports/forward/evidence.json`.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct ForwardEvidence {
    /// Days the record spans (the horizon the band was computed for).
    pub days: f64,
    pub return_pct: Option<f64>,
    /// The backtest's 5 % and 95 % cumulative return over the same days.
    pub band_low_pct: Option<f64>,
    pub band_high_pct: Option<f64>,
    /// "bootstrap" or "approximate".
    pub band_method: Option<String>,
    /// early · ok · watch · below · none
    pub status: String,
    /// Autopilots only: running, paused, stopped, finished.
    pub state: Option<String>,
    /// Autopilots only: when this run started (epoch ms), so a row is never
    /// taken for a later autopilot that reuses the id.
    pub started_ms: Option<i64>,
    /// Books only: an experiment that failed the lab's bar.
    pub experimental: bool,
}

impl ForwardEvidence {
    /// Enough days for the record to count at all.
    pub fn counts(&self) -> bool {
        self.days.is_finite() && self.days >= FORWARD_MIN_DAYS
    }

    /// Below the backtest's band after at least [`FORWARD_MIN_DAYS`] days.
    /// Judged from the numbers themselves, not from the status word, so a
    /// report that says "below" too early (or without a band) changes nothing.
    pub fn below_band(&self) -> bool {
        self.counts()
            && matches!((self.return_pct, self.band_low_pct), (Some(r), Some(lo)) if r.is_finite() && lo.is_finite() && r < lo)
    }

    pub fn above_band(&self) -> bool {
        self.counts()
            && matches!((self.return_pct, self.band_high_pct), (Some(r), Some(hi)) if r.is_finite() && hi.is_finite() && r > hi)
    }

    pub fn has_band(&self) -> bool {
        self.band_low_pct.is_some_and(f64::is_finite) && self.band_high_pct.is_some_and(f64::is_finite)
    }
}

/// `reports/forward/evidence.json`: every paper book and autopilot by name.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct ForwardFile {
    pub generated_ms: i64,
    pub books: BTreeMap<String, ForwardEvidence>,
    pub autopilots: BTreeMap<String, ForwardEvidence>,
}

/// The forward evidence as the lab wrote it; `None` when it is not a JSON
/// object. Rows that do not parse are skipped, so one bad row costs that row.
pub fn parse_forward_evidence(text: &str) -> Option<ForwardFile> {
    let v: serde_json::Value = serde_json::from_str(text).ok()?;
    let obj = v.as_object()?;
    let rows = |k: &str| -> BTreeMap<String, ForwardEvidence> {
        obj.get(k)
            .and_then(|r| r.as_object())
            .map(|m| {
                m.iter()
                    .filter_map(|(name, r)| Some((name.clone(), serde_json::from_value(r.clone()).ok()?)))
                    .collect()
            })
            .unwrap_or_default()
    };
    Some(ForwardFile {
        generated_ms: obj.get("generated_ms").and_then(|g| g.as_i64()).unwrap_or(0),
        books: rows("books"),
        autopilots: rows("autopilots"),
    })
}

/// `<root>/reports/forward/evidence.json`, if there is one that parses.
pub fn read_forward_evidence(root: &Path) -> Option<ForwardFile> {
    let text = std::fs::read_to_string(root.join("reports").join("forward").join("evidence.json")).ok()?;
    parse_forward_evidence(&text)
}

/// Where the lab's signals live: `PYTHIA_SIGNALS`, else `signals/` next to the
/// `PYTHIA_MODELS` folder (the lab writes both under one data root).
pub fn signals_dir() -> Option<std::path::PathBuf> {
    if let Ok(d) = std::env::var("PYTHIA_SIGNALS") {
        return Some(d.into());
    }
    let models = std::env::var("PYTHIA_MODELS").ok()?;
    Some(Path::new(&models).parent()?.join("signals"))
}

/// Every `<dir>/<strategy>/latest.json` that parses. Broken files are skipped
/// with their error, so one bad signal cannot stop the others.
pub fn read_all(dir: &Path) -> (Vec<LabSignal>, Vec<String>) {
    let mut ok = vec![];
    let mut errors = vec![];
    let Ok(entries) = std::fs::read_dir(dir) else { return (ok, errors) };
    for e in entries.flatten() {
        let p = e.path().join("latest.json");
        if p.is_file() {
            match read_signal(&p) {
                Ok(s) => ok.push(s),
                Err(e) => errors.push(e),
            }
        }
    }
    (ok, errors)
}

pub fn read_signal(path: &Path) -> Result<LabSignal, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))
}

impl LabSignal {
    pub fn is_fresh(&self, now_ms: i64) -> bool {
        now_ms <= self.valid_until_ms
    }

    /// An experiment that failed the lab's bar: flagged on the signal or in
    /// its evidence.
    pub fn is_experimental(&self) -> bool {
        self.experimental || self.evidence.experimental
    }

    /// A book of US shares and ETFs, traded on Alpaca.
    pub fn is_us_equity(&self) -> bool {
        self.asset_class.as_deref() == Some(US_EQUITY)
    }

    /// A book of perpetual futures, long and short.
    pub fn is_perp(&self) -> bool {
        self.asset_class.as_deref() == Some(PERP)
    }

    /// The engine market a weight's key names: a key that is already a market
    /// id (`alpaca:SPY`) as it is, else `alpaca:<KEY>` for a US equity book,
    /// `perp:<KEY>` for a perps book and `crypto:<KEY>/USD` for a coin book.
    pub fn market_id(&self, key: &str) -> String {
        if key.contains(':') {
            key.to_string()
        } else if self.is_us_equity() {
            format!("alpaca:{key}")
        } else if self.is_perp() {
            format!("perp:{}", crate::connectors::perps::alias(key))
        } else {
            format!("crypto:{key}/USD")
        }
    }

    /// The symbol of that market as the engine shows it (`SPY`, `BTC/USD`).
    pub fn market_symbol(&self, key: &str) -> String {
        let id = self.market_id(key);
        id.split_once(':').map(|(_, s)| s.to_string()).unwrap_or(id)
    }
}

fn fig(label: &str, value: f64, unit: Unit) -> Figure {
    Figure { label: label.to_string(), value, unit }
}

fn gate(id: u8, pass: Option<bool>, reason: String, value: Option<f64>, figures: Vec<Figure>) -> Gate {
    let status = match pass {
        Some(true) => GateStatus::Pass,
        Some(false) => GateStatus::Fail,
        None => GateStatus::Pending,
    };
    let mut g = Gate::new(id, status, reason, value);
    g.figures = figures;
    g
}

/// Gates 1 to 6 from the lab's evidence, judged with the thresholds of
/// PROFIT-PLAN §2. Missing evidence leaves a gate pending, never passed.
pub fn verdict(strategy_id: &str, params: Vec<(String, f64)>, ev: &LabEvidence, now_ms: i64) -> ResearchVerdict {
    let src = if ev.report.is_empty() { "the lab".to_string() } else { format!("lab report `{}`", ev.report) };
    let missing = || format!("{src} does not say; run the experiment again");

    // 1 · in-sample
    let g1 = match ev.is_sharpe {
        Some(s) => gate(1, Some(s > 0.0), format!("in-sample Sharpe {s:.2} after costs, from {src}"), Some(s), vec![]),
        None => gate(1, None, missing(), None, vec![]),
    };
    // 2 · walk-forward: out-of-sample holds at least half of in-sample
    let g2 = match (ev.is_sharpe, ev.oos_sharpe) {
        (Some(is), Some(oos)) if is > 0.0 => {
            let ratio = oos / is;
            gate(
                2,
                Some(ratio >= 0.5),
                if ratio >= 0.5 {
                    format!("out of sample kept {:.0} % of the in-sample Sharpe", ratio * 100.0)
                } else {
                    format!("out of sample kept only {:.0} % of the in-sample Sharpe; under half means the fit was mostly noise", ratio * 100.0)
                },
                Some(ratio),
                vec![fig("in-sample Sharpe", is, Unit::Number), fig("out-of-sample Sharpe", oos, Unit::Number)],
            )
        }
        _ => gate(2, None, missing(), None, vec![]),
    };
    // 3 · costs: still profitable at twice the modelled cost
    let g3 = match ev.sharpe_2x_cost {
        Some(s) => gate(3, Some(s > 0.0), format!("Sharpe {s:.2} out of sample with costs doubled"), Some(s), vec![]),
        None => gate(3, None, missing(), None, vec![]),
    };
    // 4 · plateau: most neighbouring variants profitable too
    let g4 = match ev.plateau_share {
        Some(p) => gate(
            4,
            Some(p >= 0.6),
            format!(
                "{:.0} % of the {} variants tried were profitable out of sample",
                p * 100.0,
                ev.plateau_variants.or(ev.variants_tried).map(|n| n.to_string()).unwrap_or_else(|| "?".into())
            ),
            Some(p),
            vec![],
        ),
        None => gate(4, None, missing(), None, vec![]),
    };
    // 5 · regimes: profitable in every regime, unless the strategy carries the filter for it
    let g5 = if ev.regime_sharpes.is_empty() {
        gate(5, None, missing(), None, vec![])
    } else {
        let losing: Vec<&String> = ev.regime_sharpes.iter().filter(|(_, s)| **s <= 0.0).map(|(k, _)| k).collect();
        let figures = ev.regime_sharpes.iter().map(|(k, s)| fig(k, *s, Unit::Number)).collect();
        if losing.is_empty() {
            gate(5, Some(true), "profitable in every regime tested".into(), None, figures)
        } else if ev.regime_filter {
            gate(
                5,
                Some(true),
                format!(
                    "loses in {} but stays out of the market there by its own regime filter; the filter was added after \
                     looking at round one, which is why every variant of both rounds is counted in gate 6",
                    losing.iter().map(|s| s.as_str()).collect::<Vec<_>>().join(", ")
                ),
                None,
                figures,
            )
        } else {
            gate(
                5,
                Some(false),
                format!(
                    "loses in {} and has no filter that keeps it out",
                    losing.iter().map(|s| s.as_str()).collect::<Vec<_>>().join(", ")
                ),
                None,
                figures,
            )
        }
    };
    // 6 · deflated Sharpe over every variant tried
    let g6 = match ev.deflated_p {
        Some(p) => gate(
            6,
            Some(p > 0.95),
            if p > 0.95 {
                format!("the Sharpe survives deflation for {} variants (p {p:.2})", ev.variants_tried.unwrap_or(0))
            } else {
                format!(
                    "after deflating for {} variants the probability of real skill is {:.0} %; 95 % is needed",
                    ev.variants_tried.unwrap_or(0),
                    p * 100.0
                )
            },
            Some(p),
            vec![],
        ),
        None => gate(6, None, missing(), None, vec![]),
    };

    ResearchVerdict {
        strategy_id: strategy_id.to_string(),
        params,
        checked_at: now_ms,
        markets: 0,
        bars: 0,
        cost_venue: CostVenue::Binance,
        gates: vec![g1, g2, g3, g4, g5, g6],
    }
}

/// One order that moves a book towards its target weights.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Rebalance {
    pub market_id: String,
    pub side: Side,
    pub notional: f64,
    pub target_weight: f64,
    pub current_weight: f64,
}

/// The orders that move `holdings` (market id -> (qty, price), this strategy's
/// own positions) to `weights` of `capital`. Long-only: a sell never exceeds
/// what is held. Differences smaller than `band` of capital or the venue's
/// `min_notional` are left alone, so a book does not churn on rounding.
/// Coins that have no market here come back in the second list: the engine
/// says so instead of quietly running a different portfolio than the lab.
pub fn rebalance(
    weights: &BTreeMap<String, f64>,
    market_for: impl Fn(&str) -> Option<String>,
    holdings: &HashMap<String, (f64, f64)>,
    prices: &HashMap<String, f64>,
    capital: f64,
    min_notional: f64,
    band: f64,
) -> (Vec<Rebalance>, Vec<String>) {
    let mut targets: BTreeMap<String, f64> = BTreeMap::new();
    let mut untradable = vec![];
    for (coin, w) in weights {
        match market_for(coin) {
            Some(m) if prices.contains_key(&m) => {
                targets.insert(m, w.max(0.0));
            }
            _ => untradable.push(coin.clone()),
        }
    }
    for m in holdings.keys() {
        targets.entry(m.clone()).or_insert(0.0);
    }
    let threshold = min_notional.max(band * capital);
    let mut out = vec![];
    for (m, w) in targets {
        let (qty, _) = holdings.get(&m).copied().unwrap_or((0.0, 0.0));
        let Some(&price) = prices.get(&m) else { continue };
        let current = qty.max(0.0) * price;
        let target = w * capital;
        let diff = target - current;
        if diff.abs() < threshold {
            continue;
        }
        let (side, notional) = if diff > 0.0 { (Side::Buy, diff) } else { (Side::Sell, (-diff).min(current)) };
        if notional < min_notional {
            continue;
        }
        out.push(Rebalance {
            market_id: m,
            side,
            notional,
            target_weight: w,
            current_weight: if capital > 0.0 { current / capital } else { 0.0 },
        });
    }
    // Sells first: they free the cash the buys need.
    out.sort_by_key(|r| if r.side == Side::Sell { 0 } else { 1 });
    (out, untradable)
}

/// [`rebalance`] for a book that may be short (perps): `weights` are signed
/// fractions of `capital`, `holdings` signed quantities. Each market's order
/// moves its signed notional to the target, in one order even when that
/// crosses zero (long to short). Orders that shrink a position go first:
/// they free the margin the others need. `current_weight` is signed.
pub fn rebalance_signed(
    weights: &BTreeMap<String, f64>,
    market_for: impl Fn(&str) -> Option<String>,
    holdings: &HashMap<String, (f64, f64)>,
    prices: &HashMap<String, f64>,
    capital: f64,
    min_notional: f64,
    band: f64,
) -> (Vec<Rebalance>, Vec<String>) {
    let mut targets: BTreeMap<String, f64> = BTreeMap::new();
    let mut untradable = vec![];
    for (coin, w) in weights {
        match market_for(coin) {
            Some(m) if prices.contains_key(&m) && w.is_finite() => {
                *targets.entry(m).or_insert(0.0) += *w;
            }
            _ => untradable.push(coin.clone()),
        }
    }
    for m in holdings.keys() {
        targets.entry(m.clone()).or_insert(0.0);
    }
    let threshold = min_notional.max(band * capital);
    let mut out = vec![];
    for (m, w) in targets {
        let (qty, _) = holdings.get(&m).copied().unwrap_or((0.0, 0.0));
        let Some(&price) = prices.get(&m) else { continue };
        let current = qty * price;
        let target = w * capital;
        let diff = target - current;
        // Closing what the target no longer wants always goes out, however small.
        let closes = target == 0.0 && current != 0.0;
        if diff.abs() < threshold && !closes {
            continue;
        }
        out.push(Rebalance {
            market_id: m,
            side: if diff > 0.0 { Side::Buy } else { Side::Sell },
            notional: diff.abs(),
            target_weight: w,
            current_weight: if capital > 0.0 { current / capital } else { 0.0 },
        });
    }
    // Reductions first (the target is nearer zero than the position).
    out.sort_by_key(|r| if r.target_weight.abs() < r.current_weight.abs() { 0 } else { 1 });
    (out, untradable)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn market(coin: &str) -> Option<String> {
        ["BTC", "ETH", "SOL"].contains(&coin).then(|| format!("crypto:{coin}/USD"))
    }

    fn prices() -> HashMap<String, f64> {
        [("crypto:BTC/USD", 100_000.0), ("crypto:ETH/USD", 4_000.0), ("crypto:SOL/USD", 200.0)]
            .into_iter()
            .map(|(k, v)| (k.to_string(), v))
            .collect()
    }

    #[test]
    fn moves_an_empty_book_to_its_targets_and_names_what_it_cannot_trade() {
        let w: BTreeMap<String, f64> = [("BTC", 0.10), ("ETH", 0.05), ("PEPE", 0.02)].into_iter().map(|(k, v)| (k.into(), v)).collect();
        let (orders, missing) = rebalance(&w, market, &HashMap::new(), &prices(), 10_000.0, 5.0, 0.002);
        assert_eq!(missing, vec!["PEPE".to_string()]);
        assert_eq!(orders.len(), 2);
        assert!(orders.iter().all(|o| o.side == Side::Buy));
        let btc = orders.iter().find(|o| o.market_id == "crypto:BTC/USD").unwrap();
        assert!((btc.notional - 1_000.0).abs() < 1e-9);
    }

    #[test]
    fn sells_what_left_the_targets_first_and_never_more_than_it_holds() {
        let w: BTreeMap<String, f64> = [("ETH", 0.10)].into_iter().map(|(k, v)| (k.into(), v)).collect();
        let holdings: HashMap<String, (f64, f64)> =
            [("crypto:SOL/USD".to_string(), (5.0, 200.0))].into_iter().collect();
        let (orders, _) = rebalance(&w, market, &holdings, &prices(), 10_000.0, 5.0, 0.002);
        assert_eq!(orders[0].side, Side::Sell);
        assert_eq!(orders[0].market_id, "crypto:SOL/USD");
        assert!((orders[0].notional - 1_000.0).abs() < 1e-9);
        assert_eq!(orders[1].side, Side::Buy);
    }

    #[test]
    fn a_perps_book_goes_short_crosses_zero_in_one_order_and_shrinks_first() {
        let w: BTreeMap<String, f64> =
            [("BTC", 0.05), ("ETH", -0.05), ("SOL", -0.05), ("PEPE", 0.05)].into_iter().map(|(k, v)| (k.into(), v)).collect();
        let s: LabSignal = serde_json::from_str(
            r#"{"strategy":"m4_perps","variant":"x","as_of_ms":1,"generated_ms":2,"valid_until_ms":3,"quote":"USD",
                "asset_class":"perp","weights":{"BTC":0.05,"ETH":-0.05,"XBT":0.0}}"#,
        )
        .unwrap();
        assert!(s.is_perp());
        assert_eq!(s.market_id("ETH"), "perp:ETH");
        assert_eq!(s.market_id("XBT"), "perp:BTC", "one name per coin");
        let prices: HashMap<String, f64> =
            [("perp:BTC", 100_000.0), ("perp:ETH", 4_000.0), ("perp:SOL", 200.0)].into_iter().map(|(k, v)| (k.to_string(), v)).collect();
        let market = |c: &str| ["BTC", "ETH", "SOL"].contains(&c).then(|| format!("perp:{c}"));
        // Long 10 SOL ($2,000) that the target wants short $500: one sell of
        // $2,500 through zero. ETH new short $500. BTC long $500.
        let holdings: HashMap<String, (f64, f64)> = [("perp:SOL".to_string(), (10.0, 200.0))].into_iter().collect();
        let (orders, missing) = rebalance_signed(&w, market, &holdings, &prices, 10_000.0, 5.0, 0.002);
        assert_eq!(missing, vec!["PEPE".to_string()]);
        let sol = orders.iter().find(|o| o.market_id == "perp:SOL").unwrap();
        assert_eq!(sol.side, Side::Sell);
        assert!((sol.notional - 2_500.0).abs() < 1e-9);
        assert_eq!(orders[0].market_id, "perp:SOL", "the shrinking order goes first");
        let eth = orders.iter().find(|o| o.market_id == "perp:ETH").unwrap();
        assert_eq!(eth.side, Side::Sell);
        assert!((eth.notional - 500.0).abs() < 1e-9);
        assert!((eth.target_weight + 0.05).abs() < 1e-12);
        // A short held that the target drops is bought back, however small.
        let holdings: HashMap<String, (f64, f64)> = [("perp:ETH".to_string(), (-0.0005, 4_000.0))].into_iter().collect();
        let (orders, _) = rebalance_signed(&BTreeMap::new(), market, &holdings, &prices, 10_000.0, 5.0, 0.002);
        assert_eq!(orders.len(), 1);
        assert_eq!(orders[0].side, Side::Buy);
        assert!((orders[0].notional - 2.0).abs() < 1e-9);
    }

    #[test]
    fn small_differences_are_left_alone() {
        let w: BTreeMap<String, f64> = [("BTC", 0.10)].into_iter().map(|(k, v)| (k.into(), v)).collect();
        let holdings: HashMap<String, (f64, f64)> =
            [("crypto:BTC/USD".to_string(), (0.0099, 100_000.0))].into_iter().collect();
        let (orders, _) = rebalance(&w, market, &holdings, &prices(), 10_000.0, 5.0, 0.002);
        assert!(orders.is_empty(), "a 10 $ gap on a 10 000 $ book is noise: {orders:?}");
    }

    fn evidence(oos: f64, is: f64, p: f64, filter: bool) -> LabEvidence {
        LabEvidence {
            report: "tsmom".into(),
            is_sharpe: Some(is),
            oos_sharpe: Some(oos),
            deflated_p: Some(p),
            sharpe_2x_cost: Some(0.5),
            variants_tried: Some(16),
            plateau_share: Some(1.0),
            regime_sharpes: [("BTC above 200d average".to_string(), 1.8), ("BTC below 200d average".to_string(), -2.1)]
                .into_iter()
                .collect(),
            regime_filter: filter,
            ..Default::default()
        }
    }

    #[test]
    fn the_lab_numbers_go_through_the_same_bars_as_everything_else() {
        // Round one: kept 41 % of its in-sample Sharpe, loses below the 200-day average, deflated p 0.82.
        let v = verdict("tsmom", vec![], &evidence(0.72, 1.74, 0.82, false), 0);
        let status: Vec<GateStatus> = v.gates.iter().map(|g| g.status).collect();
        assert_eq!(
            status,
            vec![GateStatus::Pass, GateStatus::Fail, GateStatus::Pass, GateStatus::Pass, GateStatus::Fail, GateStatus::Fail]
        );
        // The regime variant: passes 1 to 5, still short on gate 6.
        let v = verdict("tsmom_regime", vec![], &evidence(1.05, 1.97, 0.86, true), 0);
        let status: Vec<GateStatus> = v.gates.iter().map(|g| g.status).collect();
        assert_eq!(status[..5], [GateStatus::Pass; 5]);
        assert_eq!(status[5], GateStatus::Fail);
    }

    #[test]
    fn missing_evidence_is_pending_never_passed() {
        let v = verdict("x", vec![], &LabEvidence::default(), 0);
        assert!(v.gates.iter().all(|g| g.status == GateStatus::Pending));
    }

    const EVIDENCE: &str = r#"{
      "generated_ms": 1791440100000, "min_days": 10,
      "books": {
        "tsmom": {"days": 11.0, "return_pct": -12.0, "band_low_pct": -3.1, "band_high_pct": 4.2,
                  "band_method": "bootstrap", "status": "below", "some_future_field": 1},
        "tsmom_regime": {"days": 2.0, "return_pct": -30.0, "band_low_pct": -2.0, "band_high_pct": 2.0,
                         "band_method": "bootstrap", "status": "early"},
        "m4_ls": {"days": 14.0, "return_pct": 1.0, "band_low_pct": null, "band_high_pct": null,
                  "band_method": null, "status": "none"},
        "broken": {"days": "eleven"}
      },
      "autopilots": {"ap_1": {"days": 3.5, "return_pct": 0.4, "band_low_pct": null, "band_high_pct": null,
                              "band_method": null, "status": "early", "state": "running"}}
    }"#;

    #[test]
    fn reads_the_forward_evidence_and_only_trusts_ten_days_and_a_band() {
        let f = parse_forward_evidence(EVIDENCE).unwrap();
        assert_eq!(f.generated_ms, 1791440100000);
        assert_eq!(f.books.len(), 3, "the broken row is skipped, the rest stays");
        assert!(f.books["tsmom"].below_band());
        assert!(!f.books["tsmom_regime"].below_band(), "two days count for nothing, however far below");
        assert!(!f.books["m4_ls"].below_band() && !f.books["m4_ls"].has_band());
        assert_eq!(f.autopilots["ap_1"].state.as_deref(), Some("running"));
        // A status word that says "below" without the numbers changes nothing.
        let liar = ForwardEvidence { days: 20.0, status: "below".into(), return_pct: Some(-5.0), ..Default::default() };
        assert!(!liar.below_band());
        let nan = ForwardEvidence { days: f64::NAN, return_pct: Some(-5.0), band_low_pct: Some(0.0), ..Default::default() };
        assert!(!nan.below_band());
        assert!(parse_forward_evidence("[1]").is_none() && parse_forward_evidence("").is_none());
        assert!(parse_forward_evidence("{}").unwrap().books.is_empty());

        let dir = std::env::temp_dir().join(format!("pythia-lab-fwd-{}", std::process::id()));
        assert!(read_forward_evidence(&dir).is_none());
        std::fs::create_dir_all(dir.join("reports").join("forward")).unwrap();
        std::fs::write(dir.join("reports").join("forward").join("evidence.json"), EVIDENCE).unwrap();
        assert_eq!(read_forward_evidence(&dir).map(|f| f.books.len()), Some(3));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn reads_what_the_lab_writes() {
        let j = r#"{"strategy":"tsmom_regime","variant":"28d","as_of_ms":1,"generated_ms":2,"valid_until_ms":3,
            "quote":"USD","weights":{"BTC":0.05},"regime_on":true,
            "evidence":{"report":"momentum2","is_sharpe":1.97,"oos_sharpe":1.05,"deflated_p":0.86,"sharpe_2x_cost":0.93,
            "variants_tried":50,"plateau_share":1.0,"regime_sharpes":{"a":1.0},"regime_filter":true,"oos_max_dd":0.19}}"#;
        let s: LabSignal = serde_json::from_str(j).unwrap();
        assert!(s.is_fresh(3) && !s.is_fresh(4));
        assert_eq!(s.weights["BTC"], 0.05);
        assert!(s.evidence.regime_filter);
        assert!(!s.autopilot_only && s.dropped.is_empty(), "an old signal runs standalone, as before");

        // The family candidates: autopilot only, coins without a market named,
        // the plateau counted over their own sub-family.
        let j = r#"{"strategy":"breakout_top10","variant":"Donchian 20/10","as_of_ms":1,"generated_ms":2,"valid_until_ms":3,
            "quote":"USD","weights":{"BTC":0.1},"regime_on":null,"autopilot_only":true,"dropped":["HYPE"],
            "evidence":{"report":"families_summary","oos_sharpe":1.2,"deflated_p":0.01,"variants_tried":100,
            "plateau_share":1.0,"plateau_variants":6,"cost_note":"ignored by the engine"}}"#;
        let s: LabSignal = serde_json::from_str(j).unwrap();
        assert!(s.autopilot_only);
        assert_eq!(s.dropped, vec!["HYPE".to_string()]);
        let v = verdict("lab:breakout_top10", vec![], &s.evidence, 0);
        assert!(v.gates[3].reason.contains("of the 6 variants tried"), "{}", v.gates[3].reason);
        assert!(!s.is_experimental());

        // An experiment: flagged on the signal, in the evidence, or both; the
        // lab's extra fields (bootstrap band, why it failed) do not break it.
        let j = r#"{"strategy":"memes_rotation","variant":"EXPERIMENT, failed deflation · memecoins","as_of_ms":1,
            "generated_ms":2,"valid_until_ms":3,"quote":"USD","weights":{"PEPE":0.37},"regime_on":true,
            "autopilot_only":true,"experimental":true,"experiment":{"label":"EXPERIMENT, failed deflation"},
            "evidence":{"report":"memecoins","experimental":true,"oos_sharpe":1.15,"deflated_p":0.01,
            "variants_tried":427,"bootstrap_90":[-0.24,2.27],"why_failed":"deflated p 0.01","verdict":"experiment, fails"}}"#;
        let s: LabSignal = serde_json::from_str(j).unwrap();
        assert!(s.is_experimental() && s.evidence.experimental);
        assert_eq!(s.evidence.why_failed.as_deref(), Some("deflated p 0.01"));
        let only_evidence = j.replace(r#""autopilot_only":true,"experimental":true,"#, "");
        let s: LabSignal = serde_json::from_str(&only_evidence).unwrap();
        assert!(!s.experimental && s.is_experimental(), "the evidence alone is enough");
    }

    #[test]
    fn an_equity_signal_maps_its_symbols_to_alpaca_markets() {
        let j = r#"{"strategy":"etf_trend","variant":"trend","as_of_ms":1,"generated_ms":2,"valid_until_ms":3,
            "quote":"USD","weights":{"SPY":0.3,"GLD":0.2},"asset_class":"us_equity","autopilot_only":true}"#;
        let s: LabSignal = serde_json::from_str(j).unwrap();
        assert!(s.is_us_equity());
        assert_eq!(s.market_id("SPY"), "alpaca:SPY");
        assert_eq!(s.market_symbol("GLD"), "GLD");
        assert_eq!(s.market_id("alpaca:IEF"), "alpaca:IEF", "a full market id is taken as it is");
        let w: BTreeMap<String, f64> = s.weights.clone();
        let p: HashMap<String, f64> =
            [("alpaca:SPY".to_string(), 500.0), ("alpaca:GLD".to_string(), 250.0)].into_iter().collect();
        let (orders, missing) = rebalance(&w, |k| Some(s.market_id(k)), &HashMap::new(), &p, 10_000.0, 1.0, 0.002);
        assert!(missing.is_empty());
        let spy = orders.iter().find(|o| o.market_id == "alpaca:SPY").unwrap();
        assert!((spy.notional - 3_000.0).abs() < 1e-9, "dollar sizing: fractional shares are fine on Alpaca");

        // Every signal so far names coins.
        let j = r#"{"strategy":"tsmom","variant":"28d","as_of_ms":1,"generated_ms":2,"valid_until_ms":3,
            "quote":"USD","weights":{"BTC":0.05}}"#;
        let s: LabSignal = serde_json::from_str(j).unwrap();
        assert!(!s.is_us_equity());
        assert_eq!(s.market_id("BTC"), "crypto:BTC/USD");
        assert_eq!(s.market_symbol("BTC"), "BTC/USD");
    }
}
