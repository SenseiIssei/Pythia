//! M2 "Picks" in shadow mode: a weekly ranking of every liquid Binance coin by
//! its expected next-week return against the others, scored a week later.
//!
//! Once a week (or when asked) this pulls ~80 days of hourly spot bars for
//! every Binance USDT pair the lab's universe would contain, the daily bars and
//! funding of their USDT perpetuals, rebuilds the 19 raw features exactly as
//! the lab does (pythia-ml, held to the lab by a parity test), ranks the whole
//! cross-section and scores it with the exported LambdaRank model. Seven days
//! later the same coins' realised returns give that week's Rank-IC.
//!
//! Nothing here places or sizes an order. The model file is the lab's
//! `picks_7d/<date>/` under `PYTHIA_MODELS`; without one the status says
//! "no model" and the task idles.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::OnceLock;
use std::time::Duration;

use pythia_ml::drift;
use pythia_ml::picks::{
    ages, attach_perp, daily_from_hourly, eligible, in_universe, largest_perp_by_day, perp_base, perp_days,
    rank_cross_section, segment_start, spot_features, DayBar, Funding, HourBar, PerpKline, PicksModel, Row, DAY_MS,
    FEATURES, HORIZON_DAYS, MIN_COINS, PERP_SHARE,
};
use pythia_ml::picks_shadow::{Pick, PicksBook, PicksShadowSummary, Ranking, RawDrift};
use serde::Serialize;
use serde_json::Value;

use crate::ml::{MlState, SharedMl, UNIVERSE};

pub const NAME: &str = "picks_7d";
/// Days of hourly bars fetched: 56 rows of lookback plus margin for missing days.
const WINDOW_DAYS: i64 = 80;
/// Days of perpetual bars and funding: seven for fund7, with margin.
const PERP_DAYS: i64 = 30;
/// Binance finalises the daily bar a little after midnight UTC.
const SETTLE_MS: i64 = 30 * 60_000;
const SPOT: &str = "https://api.binance.com/api/v3";
const FAPI: &str = "https://fapi.binance.com/fapi/v1";

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PicksModelInfo {
    pub name: String,
    pub version: String,
    pub trees: usize,
    pub train_from_ms: i64,
    pub train_to_ms: i64,
    pub horizon_days: i64,
    /// The lab's out-of-sample mean daily Rank-IC, the bar for the live number.
    pub lab_rank_ic: Option<f64>,
    pub lab_rank_ic_t: Option<f64>,
    pub lab_rank_ic_liquid50: Option<f64>,
    /// Eligible coins on a typical training day, and the share with a perpetual.
    pub typical_coins: Option<f64>,
    pub typical_with_perp_pct: Option<f64>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PickView {
    pub symbol: String,
    /// 1 = best.
    pub rank: usize,
    /// 100 = best of the day, 0 = worst.
    pub percentile: f64,
    pub score: f64,
    pub perp: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RankingView {
    pub day_ms: i64,
    pub made_ms: i64,
    pub version: String,
    pub coins: usize,
    pub with_perp: usize,
    pub top: Vec<PickView>,
    pub bottom: Vec<PickView>,
    /// Where the engine's own coins stand.
    pub engine: Vec<PickView>,
    pub notes: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PicksStatus {
    pub state: MlState,
    pub message: String,
    pub model: Option<PicksModelInfo>,
    /// A ranking or scoring run is in progress.
    pub running: bool,
    pub latest: Option<RankingView>,
    pub shadow: PicksShadowSummary,
    /// Raw inputs of the latest ranking against the training data.
    pub drift: Vec<RawDrift>,
    /// Where the engine's inputs can differ from the lab's (from the model card).
    pub engine_notes: Vec<String>,
    pub updated_ms: i64,
}

impl Default for PicksStatus {
    fn default() -> Self {
        Self {
            state: MlState::NoModel,
            message: "Starting".into(),
            model: None,
            running: false,
            latest: None,
            shadow: PicksShadowSummary::default(),
            drift: vec![],
            engine_notes: vec![],
            updated_ms: 0,
        }
    }
}

static DEMAND: AtomicBool = AtomicBool::new(false);
fn wake() -> &'static tokio::sync::Notify {
    static N: OnceLock<tokio::sync::Notify> = OnceLock::new();
    N.get_or_init(tokio::sync::Notify::new)
}

/// Asks for a ranking of the latest complete day now, instead of waiting for
/// the week to come round. Read-only: it ranks and records, it never trades.
pub fn request_run() {
    DEMAND.store(true, Ordering::SeqCst);
    wake().notify_one();
}

fn now_ms() -> i64 {
    chrono::Utc::now().timestamp_millis()
}

fn set(shared: &SharedMl, f: impl FnOnce(&mut PicksStatus)) {
    if let Ok(mut s) = shared.write() {
        f(&mut s.picks);
        s.picks.updated_ms = now_ms();
    }
}

/// The newest UTC day whose daily bar is final.
pub fn latest_complete_day(now: i64) -> i64 {
    (now - SETTLE_MS).div_euclid(DAY_MS) * DAY_MS - DAY_MS
}

fn load_model() -> Result<(PicksModel, PathBuf), (MlState, String)> {
    let Ok(dir) = std::env::var("PYTHIA_MODELS") else {
        return Err((
            MlState::NoModel,
            "PYTHIA_MODELS is not set. Point it at the lab's model folder (the synced PythiaData/models).".into(),
        ));
    };
    let Some(version) = pythia_ml::latest_version(Path::new(&dir), NAME) else {
        return Err((MlState::NoModel, format!("No {NAME} model with card.json and model.json under {dir}.")));
    };
    PicksModel::load(&version)
        .map(|m| (m, version.clone()))
        .map_err(|e| (MlState::Rejected, format!("{}: {e}", version.display())))
}

fn model_info(m: &PicksModel, version: &Path) -> PicksModelInfo {
    let oos = &m.card.out_of_sample;
    let td = &m.card.typical_day;
    PicksModelInfo {
        name: m.card.name.clone(),
        version: version.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default(),
        trees: m.n_trees(),
        train_from_ms: m.card.train_from_us / 1000,
        train_to_ms: m.card.train_to_us / 1000,
        horizon_days: if m.card.horizon_days > 0 { m.card.horizon_days } else { HORIZON_DAYS },
        lab_rank_ic: m.card.lab_rank_ic(),
        lab_rank_ic_t: oos.get("rank_ic_t").and_then(Value::as_f64),
        lab_rank_ic_liquid50: oos.get("rank_ic_liquid50").and_then(Value::as_f64),
        typical_coins: td.get("eligible_coins").and_then(Value::as_f64),
        typical_with_perp_pct: td.get("with_perp_pct").and_then(Value::as_f64),
    }
}

fn view(r: &Ranking) -> RankingView {
    let n = r.picks.len();
    let pv = |i: usize, p: &Pick| PickView {
        symbol: p.symbol.clone(),
        rank: i + 1,
        percentile: if n > 1 { 100.0 * (n - 1 - i) as f64 / (n - 1) as f64 } else { 100.0 },
        score: p.score,
        perp: p.perp,
    };
    let engine: HashSet<String> = UNIVERSE.iter().map(|c| format!("{c}USDT")).collect();
    RankingView {
        day_ms: r.day_ms,
        made_ms: r.made_ms,
        version: r.version.clone(),
        coins: n,
        with_perp: r.picks.iter().filter(|p| p.perp).count(),
        top: r.picks.iter().enumerate().take(10).map(|(i, p)| pv(i, p)).collect(),
        bottom: r.picks.iter().enumerate().skip(n.saturating_sub(10)).map(|(i, p)| pv(i, p)).collect(),
        engine: r.picks.iter().enumerate().filter(|(_, p)| engine.contains(&p.symbol)).map(|(i, p)| pv(i, p)).collect(),
        notes: r.notes.clone(),
    }
}

fn publish(shared: &SharedMl, book: &PicksBook) {
    let latest = book.latest().cloned();
    let summary = book.summary();
    set(shared, |s| {
        s.drift = latest.as_ref().map(|r| r.drift.clone()).unwrap_or_default();
        s.latest = latest.as_ref().map(view);
        s.shadow = summary;
    });
}

pub async fn run(shared: SharedMl) {
    let (mut model, mut version) = loop {
        match tokio::task::spawn_blocking(load_model).await {
            Ok(Ok(ok)) => break ok,
            Ok(Err((state, msg))) => set(&shared, |s| {
                s.state = state;
                s.message = msg;
            }),
            Err(e) => set(&shared, |s| {
                s.state = MlState::Rejected;
                s.message = format!("model loader crashed: {e}");
            }),
        }
        // A sync may deliver the model later.
        tokio::time::sleep(Duration::from_secs(600)).await;
    };
    let shadow_file = version.parent().map(|p| p.join("shadow.json"));
    let mut book = shadow_file
        .as_deref()
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|t| serde_json::from_str::<Vec<Ranking>>(&t).ok())
        .map(PicksBook::restore)
        .unwrap_or_default();
    set(&shared, |s| {
        s.state = MlState::Live;
        s.message = "Ranks weekly, in shadow mode: scored a week later, never traded".into();
        s.model = Some(model_info(&model, &version));
        s.engine_notes = model.card.engine_notes.clone();
    });
    publish(&shared, &book);

    let http = reqwest::Client::builder().timeout(Duration::from_secs(20)).build().unwrap_or_default();
    loop {
        let day = latest_complete_day(now_ms());
        let demand = DEMAND.swap(false, Ordering::SeqCst);
        let rank = demand || book.ranking_due(day);
        let score = book.due_for_scoring(day);
        if rank || !score.is_empty() {
            set(&shared, |s| {
                s.running = true;
                s.message = if rank { "Ranking the latest complete day".into() } else { "Scoring last week's ranking".into() };
            });
            let msg = match work(&http, &model, &version, &mut book, day, rank, &score).await {
                Ok(m) => m,
                Err(e) => format!("Last run failed, retrying within the hour: {e}"),
            };
            if let Some(p) = &shadow_file {
                if let Ok(text) = serde_json::to_string(book.rankings()) {
                    let tmp = p.with_extension("json.tmp");
                    if std::fs::write(&tmp, text).is_ok() {
                        let _ = std::fs::rename(&tmp, p);
                    }
                }
            }
            publish(&shared, &book);
            set(&shared, |s| {
                s.running = false;
                s.message = msg;
            });
        }
        // A newer retrain that passes its probes takes over; the live record carries on.
        if let Ok(dir) = std::env::var("PYTHIA_MODELS") {
            if let Some(newest) = pythia_ml::latest_version(Path::new(&dir), NAME) {
                if newest != version {
                    let cand = newest.clone();
                    match tokio::task::spawn_blocking(move || PicksModel::load(&cand)).await {
                        Ok(Ok(m)) => {
                            let info = model_info(&m, &newest);
                            let notes = m.card.engine_notes.clone();
                            model = m;
                            set(&shared, |s| {
                                s.model = Some(info);
                                s.engine_notes = notes;
                            });
                        }
                        Ok(Err(e)) => {
                            set(&shared, |s| s.message = format!("A newer M2 model was refused and the current one kept: {e}"))
                        }
                        Err(_) => {}
                    }
                    version = newest;
                }
            }
        }
        tokio::select! {
            _ = tokio::time::sleep(Duration::from_secs(3600)) => {}
            _ = wake().notified() => {}
        }
    }
}

/// One run: fetch, score the weeks that have closed, rank `day` if asked.
async fn work(
    http: &reqwest::Client,
    model: &PicksModel,
    version: &Path,
    book: &mut PicksBook,
    day: i64,
    rank: bool,
    score: &[i64],
) -> Result<String, String> {
    let api = Api { http };
    let symbols: Vec<String> = api.spot_symbols().await?.into_iter().filter(|s| in_universe(s)).collect();
    let from = day - (WINDOW_DAYS - 1) * DAY_MS;
    // Four symbols at a time: ~900 requests, well inside Binance's weight limit.
    let mut hours: HashMap<String, Vec<HourBar>> = HashMap::new();
    let mut tasks = tokio::task::JoinSet::new();
    for s in symbols.iter().cloned() {
        if tasks.len() >= 4 {
            if let Some(Ok((s, h))) = tasks.join_next().await {
                hours.insert(s, h);
            }
        }
        let http = http.clone();
        tasks.spawn(async move {
            let h = Api { http: &http }.hours(&s, from, day + DAY_MS - 1).await;
            (s, h)
        });
    }
    while let Some(r) = tasks.join_next().await {
        if let Ok((s, h)) = r {
            hours.insert(s, h);
        }
    }
    hours.retain(|_, h| !h.is_empty());
    let mut out = vec![];

    // 1. Score every ranking whose week has closed.
    for &d in score {
        let end = d + HORIZON_DAYS * DAY_MS;
        let Some(picks) = book.rankings().iter().find(|r| r.day_ms == d).map(|r| r.picks.clone()) else { continue };
        let mut closes = HashMap::new();
        for p in &picks {
            let c = match hours.get(&p.symbol) {
                Some(h) if end >= from => daily_from_hourly(h).iter().find(|x| x.day_ms == end).map(|x| x.close),
                // Not trading any more (or the week is older than the bars held): its own daily bars;
                // a coin delisted inside the week is scored at its last close, as in the lab.
                _ => api.close_at(&p.symbol, d, end).await,
            };
            if let Some(c) = c {
                closes.insert(p.symbol.clone(), c);
            }
        }
        if let Some(x) = book.score(d, &closes, now_ms()) {
            out.push(format!("week from {} scored: Rank-IC {:.3} over {} coins", fmt_day(d), x.rank_ic, x.coins));
        }
    }

    if !rank {
        return Ok(out.join("; "));
    }

    // 2. Raw spot features for every coin on `day`.
    let btc_days = hours.get("BTCUSDT").map(|h| daily_from_hourly(&h[segment_start(h)..])).ok_or("no BTC bars")?;
    let mut rows: Vec<(String, Row, DayBar)> = vec![];
    let (mut listed_here, mut listing_lookups) = (0, 0);
    for s in &symbols {
        let Some(h) = hours.get(s) else { continue };
        let start = segment_start(h);
        let days = daily_from_hourly(&h[start..]);
        let Some(last) = days.last().copied() else { continue };
        if last.day_ms != day {
            continue;
        }
        let mut anchor = model.card.anchor(s);
        if anchor.is_none() && start == 0 {
            if h[0].open_time_ms <= from {
                // Older than the bars held but unknown to the card: its first full day on Binance.
                listing_lookups += 1;
                anchor = api.first_full_day(s).await.map(|d| (d, 0.0));
            } else {
                listed_here += 1;
            }
        }
        let ag = ages(&days, anchor, start > 0);
        let x = *spot_features(&days, &btc_days, &ag).last().expect("non-empty");
        if eligible(&x, x[pythia_ml::picks::AGE] + 1.0) {
            rows.push((s.clone(), x, last));
        }
    }
    if rows.len() < MIN_COINS {
        return Err(format!("only {} eligible coins on {}, the lab needs {MIN_COINS}", rows.len(), fmt_day(day)));
    }

    // 3. Perpetuals for the eligible bases.
    let bases: HashSet<String> = rows.iter().map(|(s, _, _)| s.trim_end_matches("USDT").to_string()).collect();
    let mut by_base: HashMap<String, Vec<Vec<pythia_ml::picks::PerpDay>>> = HashMap::new();
    for p in api.perp_symbols().await.unwrap_or_default() {
        let base = perp_base(&p).to_string();
        if !bases.contains(&base) {
            continue;
        }
        let k = api.perp_klines(&p, day - (PERP_DAYS - 1) * DAY_MS, day + DAY_MS - 1).await;
        if k.is_empty() {
            continue;
        }
        let f = api.funding(&p, day - (PERP_DAYS - 1) * DAY_MS, day + DAY_MS - 1).await;
        by_base.entry(base).or_default().push(perp_days(&k, &f));
    }
    for (s, x, d) in rows.iter_mut() {
        let best = by_base.get(s.trim_end_matches("USDT")).map(|v| largest_perp_by_day(v));
        attach_perp(x, d.close, d.qv, best.as_ref().and_then(|m| m.get(&day)));
    }

    // 4. Rank, score, record.
    let raw: Vec<Row> = rows.iter().map(|(_, x, _)| *x).collect();
    let ranked = rank_cross_section(&raw);
    let mut picks: Vec<Pick> = rows
        .iter()
        .zip(&ranked)
        .map(|((s, x, d), r)| Pick { symbol: s.clone(), score: model.score(r), close: d.close, perp: x[PERP_SHARE].is_finite() })
        .collect();
    picks.sort_by(|a, b| b.score.total_cmp(&a.score));
    let drift = FEATURES
        .iter()
        .enumerate()
        .filter_map(|(j, name)| {
            let bins = model.card.raw_feature_bins.get(*name)?;
            let vals: Vec<f64> = raw.iter().map(|x| x[j]).collect();
            let c = drift::check(bins, &vals)?;
            Some(RawDrift { feature: name.to_string(), psi: c.psi, outside_pct: c.outside_pct, level: c.level })
        })
        .collect();
    let mut notes = vec![];
    if listed_here > 0 {
        notes.push(format!("{listed_here} coins listed inside the last {WINDOW_DAYS} days were aged from their first day here."));
    }
    if listing_lookups > 0 {
        notes.push(format!("{listing_lookups} coins unknown to the model card were aged from their first full day on Binance."));
    }
    let n = picks.len();
    let with_perp = picks.iter().filter(|p| p.perp).count();
    book.record(Ranking {
        day_ms: day,
        made_ms: now_ms(),
        version: version.file_name().map(|v| v.to_string_lossy().into_owned()).unwrap_or_default(),
        picks,
        drift,
        notes,
        realised: None,
    });
    out.push(format!("ranked {n} coins for {} ({with_perp} with a perpetual)", fmt_day(day)));
    Ok(format!("{}. Shadow mode: recorded, never traded.", capitalise(&out.join("; "))))
}

fn fmt_day(ms: i64) -> String {
    chrono::DateTime::from_timestamp_millis(ms).map(|d| d.format("%Y-%m-%d").to_string()).unwrap_or_default()
}

fn capitalise(s: &str) -> String {
    let mut c = s.chars();
    c.next().map(|f| f.to_uppercase().collect::<String>() + c.as_str()).unwrap_or_default()
}

/// Binance public market data, paced well below the weight limits.
struct Api<'a> {
    http: &'a reqwest::Client,
}

impl Api<'_> {
    async fn get(&self, url: &str) -> Option<Value> {
        for attempt in 0..3 {
            tokio::time::sleep(Duration::from_millis(80)).await;
            match self.http.get(url).send().await {
                Ok(r) if r.status().as_u16() == 429 || r.status().as_u16() == 418 => {
                    tokio::time::sleep(Duration::from_secs(60 * (attempt + 1))).await;
                }
                Ok(r) => return r.error_for_status().ok()?.json().await.ok(),
                Err(_) => tokio::time::sleep(Duration::from_secs(2)).await,
            }
        }
        None
    }

    async fn spot_symbols(&self) -> Result<Vec<String>, String> {
        let v = self.get(&format!("{SPOT}/exchangeInfo?permissions=SPOT")).await.ok_or("Binance exchangeInfo unreachable")?;
        Ok(trading_symbols(&v, |s| s["quoteAsset"] == "USDT"))
    }

    async fn perp_symbols(&self) -> Option<Vec<String>> {
        let v = self.get(&format!("{FAPI}/exchangeInfo")).await?;
        Some(trading_symbols(&v, |s| {
            s["contractType"] == "PERPETUAL" && s["quoteAsset"] == "USDT" && !s["symbol"].as_str().unwrap_or("_").contains('_')
        }))
    }

    async fn hours(&self, symbol: &str, from: i64, to: i64) -> Vec<HourBar> {
        let mut out: Vec<HourBar> = vec![];
        let mut start = from;
        for _ in 0..4 {
            let url = format!("{SPOT}/klines?symbol={symbol}&interval=1h&startTime={start}&endTime={to}&limit=1000");
            let Some(page) = self.get(&url).await.as_ref().and_then(parse_hours) else { break };
            let Some(last) = page.last().map(|h| h.open_time_ms) else { break };
            let have = out.last().map_or(i64::MIN, |l| l.open_time_ms);
            out.extend(page.into_iter().filter(|h| h.open_time_ms > have));
            if last + 3_600_000 > to {
                break;
            }
            start = last + 3_600_000;
        }
        out
    }

    /// The first UTC day with at least 20 hourly bars, as the lab's history would start.
    async fn first_full_day(&self, symbol: &str) -> Option<i64> {
        let v = self.get(&format!("{SPOT}/klines?symbol={symbol}&interval=1h&startTime=0&limit=72")).await?;
        let h = parse_hours(&v)?;
        let mut count: Vec<(i64, usize)> = vec![];
        for b in &h {
            let d = b.open_time_ms.div_euclid(DAY_MS) * DAY_MS;
            match count.last_mut() {
                Some((x, n)) if *x == d => *n += 1,
                _ => count.push((d, 1)),
            }
        }
        let first = count.iter().find(|(_, n)| *n >= 20).map(|(d, _)| *d)?;
        // The lab's data starts in 2020.
        Some(first.max(1_577_836_800_000))
    }

    /// Close of `end` from daily spot bars; the last close if the coin stopped trading before it.
    async fn close_at(&self, symbol: &str, start: i64, end: i64) -> Option<f64> {
        let url = format!("{SPOT}/klines?symbol={symbol}&interval=1d&startTime={start}&endTime={}&limit=30", end + DAY_MS - 1);
        let v = self.get(&url).await?;
        let rows: Vec<(i64, f64)> = v
            .as_array()?
            .iter()
            .filter_map(|r| Some((r.get(0)?.as_i64()?, num(r.get(4)?)?)))
            .collect();
        if let Some((_, c)) = rows.iter().find(|(t, _)| *t == end) {
            return Some(*c);
        }
        let (t, c) = *rows.last()?;
        // Bars that end early mean a delisting; a hole in the middle means nothing to score.
        (t < end && now_ms() - t > 3 * DAY_MS).then_some(c)
    }

    async fn perp_klines(&self, symbol: &str, from: i64, to: i64) -> Vec<PerpKline> {
        let url = format!("{FAPI}/klines?symbol={symbol}&interval=1d&startTime={from}&endTime={to}&limit=60");
        self.get(&url)
            .await
            .and_then(|v| {
                v.as_array().map(|a| {
                    a.iter()
                        .filter_map(|r| {
                            Some(PerpKline {
                                day_ms: r.get(0)?.as_i64()?.div_euclid(DAY_MS) * DAY_MS,
                                close: num(r.get(4)?)?,
                                quote_volume: num(r.get(7)?)?,
                            })
                        })
                        .collect()
                })
            })
            .unwrap_or_default()
    }

    async fn funding(&self, symbol: &str, from: i64, to: i64) -> Vec<Funding> {
        let url = format!("{FAPI}/fundingRate?symbol={symbol}&startTime={from}&endTime={to}&limit=1000");
        self.get(&url)
            .await
            .and_then(|v| {
                v.as_array().map(|a| {
                    a.iter()
                        .filter_map(|r| Some(Funding { time_ms: r.get("fundingTime")?.as_i64()?, rate: num(r.get("fundingRate")?)? }))
                        .collect()
                })
            })
            .unwrap_or_default()
    }
}

fn num(x: &Value) -> Option<f64> {
    x.as_str().and_then(|t| t.parse::<f64>().ok()).or_else(|| x.as_f64())
}

fn trading_symbols(v: &Value, keep: impl Fn(&Value) -> bool) -> Vec<String> {
    v["symbols"]
        .as_array()
        .map(|a| {
            a.iter()
                .filter(|s| s["status"] == "TRADING" && keep(s))
                .filter_map(|s| s["symbol"].as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}

/// `[[openTime, open, high, low, close, volume, closeTime, quoteVolume, …], …]`, numbers as strings.
fn parse_hours(v: &Value) -> Option<Vec<HourBar>> {
    v.as_array()?
        .iter()
        .map(|r| {
            let r = r.as_array()?;
            let mut t = r.first()?.as_i64()?;
            if t > 10_i64.pow(14) {
                t /= 1000;
            }
            Some(HourBar { open_time_ms: t, high: num(r.get(2)?)?, low: num(r.get(3)?)?, close: num(r.get(4)?)?, quote_volume: num(r.get(7)?)? })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_latest_day_waits_for_the_settle() {
        let midnight = 20_000 * DAY_MS;
        assert_eq!(latest_complete_day(midnight + 10 * 60_000), midnight - 2 * DAY_MS);
        assert_eq!(latest_complete_day(midnight + 31 * 60_000), midnight - DAY_MS);
    }

    #[test]
    fn parses_hourly_klines() {
        let v: Value = serde_json::from_str(
            r#"[[1790812800000,"62887.88","62900.00","62887.87","62893.06","7.71",1790816399999,"485038.09",873,"1.18","74456.29","0"]]"#,
        )
        .unwrap();
        let h = parse_hours(&v).unwrap();
        assert_eq!(h[0].open_time_ms, 1_790_812_800_000);
        assert_eq!(h[0].high, 62900.0);
        assert_eq!(h[0].quote_volume, 485038.09);
    }

    #[test]
    fn keeps_only_trading_symbols() {
        let v: Value = serde_json::from_str(
            r#"{"symbols":[{"symbol":"SOLUSDT","status":"TRADING","quoteAsset":"USDT"},
                {"symbol":"OLDUSDT","status":"BREAK","quoteAsset":"USDT"},
                {"symbol":"SOLBTC","status":"TRADING","quoteAsset":"BTC"}]}"#,
        )
        .unwrap();
        assert_eq!(trading_symbols(&v, |s| s["quoteAsset"] == "USDT"), vec!["SOLUSDT"]);
    }

    /// One real ranking against Binance's public market data with the local model:
    /// `PYTHIA_MODELS=... cargo test -p pythia-core live_ranking -- --ignored --nocapture`
    #[tokio::test]
    #[ignore]
    async fn live_ranking() {
        let (model, version) = load_model().map_err(|e| e.1).unwrap();
        let http = reqwest::Client::builder().timeout(Duration::from_secs(20)).build().unwrap();
        let mut book = PicksBook::default();
        let day = latest_complete_day(now_ms());
        let t = std::time::Instant::now();
        let msg = work(&http, &model, &version, &mut book, day, true, &[]).await.unwrap();
        let r = book.latest().unwrap();
        let v = view(r);
        eprintln!("{msg} ({:.0} s)", t.elapsed().as_secs_f64());
        eprintln!("top: {:?}", v.top.iter().map(|p| &p.symbol).collect::<Vec<_>>());
        eprintln!("bottom: {:?}", v.bottom.iter().map(|p| &p.symbol).collect::<Vec<_>>());
        eprintln!("engine: {:?}", v.engine.iter().map(|p| format!("{} {:.0}", p.symbol, p.percentile)).collect::<Vec<_>>());
        eprintln!("drift: {:?}", r.drift.iter().map(|d| format!("{} {:?} {:.1}%", d.feature, d.level, d.outside_pct)).collect::<Vec<_>>());
        eprintln!("notes: {:?}", r.notes);
        assert!(v.coins >= MIN_COINS);
    }

    #[test]
    fn status_serialises_camel_case() {
        let s = serde_json::to_value(PicksStatus::default()).unwrap();
        assert_eq!(s["state"], "noModel");
        assert!(s.get("engineNotes").is_some());
    }
}
