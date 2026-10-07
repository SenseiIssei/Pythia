//! Live crypto market data with failover, sanity checks and a health report.
//!
//! The engine trades on three kinds of public data for the crypto universe:
//! quotes (the mark every stop and P&L is computed from), candles (what every
//! indicator runs on) and top-20 books (what a fill's spread and depth cost).
//! Each kind has a priority list of public, keyless sources. This module
//! decides, per kind and per market, which source the engine listens to:
//!
//! * **Failover.** A market moves to the next source in the list when its
//!   current one has not delivered a sane value for the kind's stale time, or
//!   has failed `fail_limit` polls in a row. One coin missing on a venue only
//!   moves that coin.
//! * **Switching back.** A higher source takes a market back only after it has
//!   delivered continuously for `recover_hold_ms`, so a flapping primary does
//!   not drag the book back and forth.
//! * **No mixing.** A candle series always comes whole from one source. When a
//!   market's candles change source the engine installs the new venue's whole
//!   series, journals that it is a different series, and takes no entry on the
//!   switch bar (see `Engine::apply_feed_candles`).
//! * **Sanity.** A quote is compared with the other venues' recent prices
//!   first. One that is more than `max_deviation` away from every other venue
//!   is rejected and never becomes the mark, so a bad tick cannot trigger a
//!   stop. With no other venue to ask, a jump of more than `max_jump` against
//!   the last good price is held until a second venue agrees or the same venue
//!   has repeated it for `confirm_ms`.
//!
//! Everything here is synchronous and takes the time as an argument, so the
//! rules are tested with a fake clock. The network side lives in
//! [`sources`] (REST), [`ws`] (the push stream) and [`runner`] (the loops).

pub mod runner;
pub mod sources;
pub mod ws;

use serde::{Deserialize, Serialize};
use std::collections::{HashMap, VecDeque};

use crate::costs::CostVenue;

/// A public, keyless market data source.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum FeedSource {
    /// Kraken's websocket ticker: pushed, not polled.
    KrakenWs,
    Kraken,
    Binance,
    /// Binance's market-data-only host. Same venue and books as `Binance`,
    /// different servers, so it is a real fallback for Binance books.
    BinanceVision,
    Coinbase,
    Bybit,
    Okx,
}

impl FeedSource {
    pub const ALL: [FeedSource; 7] = [
        FeedSource::KrakenWs,
        FeedSource::Kraken,
        FeedSource::Binance,
        FeedSource::BinanceVision,
        FeedSource::Coinbase,
        FeedSource::Bybit,
        FeedSource::Okx,
    ];

    pub fn id(self) -> &'static str {
        match self {
            FeedSource::KrakenWs => "kraken-ws",
            FeedSource::Kraken => "kraken",
            FeedSource::Binance => "binance",
            FeedSource::BinanceVision => "binance-vision",
            FeedSource::Coinbase => "coinbase",
            FeedSource::Bybit => "bybit",
            FeedSource::Okx => "okx",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            FeedSource::KrakenWs => "Kraken stream",
            FeedSource::Kraken => "Kraken",
            FeedSource::Binance => "Binance",
            FeedSource::BinanceVision => "Binance mirror",
            FeedSource::Coinbase => "Coinbase",
            FeedSource::Bybit => "Bybit",
            FeedSource::Okx => "OKX",
        }
    }

    pub fn parse(s: &str) -> Option<FeedSource> {
        let s = s.trim().to_ascii_lowercase();
        FeedSource::ALL.into_iter().find(|f| f.id() == s)
    }

    /// The exchange behind the source. Two sources of one venue are not two
    /// opinions about a price: the sanity check only trusts other venues.
    pub fn venue(self) -> &'static str {
        match self {
            FeedSource::KrakenWs | FeedSource::Kraken => "kraken",
            FeedSource::Binance | FeedSource::BinanceVision => "binance",
            FeedSource::Coinbase => "coinbase",
            FeedSource::Bybit => "bybit",
            FeedSource::Okx => "okx",
        }
    }

    /// Pushed by a stream rather than polled.
    pub fn is_push(self) -> bool {
        matches!(self, FeedSource::KrakenWs)
    }

    /// Book sources for the exchange whose costs crypto fills pay. Only that
    /// exchange's own book describes its fills (`ExecCost::for_order` ignores
    /// any other), so the fallback is another host of the same venue, and past
    /// that the calibrated defaults. Venues without a calibrated book get none.
    pub fn for_books(venue: CostVenue) -> Vec<FeedSource> {
        match venue {
            CostVenue::Kraken => vec![FeedSource::Kraken],
            CostVenue::Binance => vec![FeedSource::Binance, FeedSource::BinanceVision],
            _ => vec![],
        }
    }
}

/// What a feed delivers.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum DataKind {
    Quotes,
    Candles,
    Books,
}

impl DataKind {
    pub const ALL: [DataKind; 3] = [DataKind::Quotes, DataKind::Candles, DataKind::Books];

    fn idx(self) -> usize {
        match self {
            DataKind::Quotes => 0,
            DataKind::Candles => 1,
            DataKind::Books => 2,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            DataKind::Quotes => "Quotes",
            DataKind::Candles => "Candles",
            DataKind::Books => "Order books",
        }
    }
}

/// Every tunable of the feed layer. `from_env` reads the `PYTHIA_FEED_*`
/// overrides; the defaults are what the VPS runs.
#[derive(Debug, Clone, PartialEq)]
pub struct FeedConfig {
    /// Quote sources, best first. The stream, when listed, is pushed.
    pub quotes: Vec<FeedSource>,
    /// Candle sources, best first.
    pub candles: Vec<FeedSource>,
    /// Run the push stream at all.
    pub stream: bool,
    /// A polled quote source older than this has failed over. Inside the
    /// risk manager's 30 s staleness limit, so a failover normally lands
    /// before entries are refused.
    pub quote_stale_ms: i64,
    /// The stream sends a heartbeat every second; silence this long is down.
    pub push_stale_ms: i64,
    /// Candles are polled every minute: two missed refreshes and a bit.
    pub candle_stale_ms: i64,
    /// Matches `orderbook::MAX_BOOK_AGE_MS`: past it the book is not used.
    pub book_stale_ms: i64,
    /// Consecutive failed polls after which a source counts as down even if
    /// its last value is still young.
    pub fail_limit: u32,
    /// A better source must deliver this long without a gap before it takes
    /// a market back.
    pub recover_hold_ms: i64,
    /// Furthest a quote may sit from another venue's recent price (fraction).
    pub max_deviation: f64,
    /// Furthest a quote may jump from the last good price when no other venue
    /// is known (fraction).
    pub max_jump: f64,
    /// How long one venue must repeat a jump before it is believed without a
    /// second venue.
    pub confirm_ms: i64,
    /// How old another venue's price may be and still serve as a reference.
    pub reference_age_ms: i64,
    /// How often a second venue is polled as the reference for the sanity check.
    pub reference_every_ms: i64,
    /// Stale this long and the webhook hears about it, once.
    pub alert_after_ms: i64,
    pub quotes_every_ms: i64,
    pub candles_every_ms: i64,
    pub books_every_ms: i64,
}

impl Default for FeedConfig {
    fn default() -> Self {
        FeedConfig {
            quotes: vec![
                FeedSource::KrakenWs,
                FeedSource::Kraken,
                FeedSource::Binance,
                FeedSource::Coinbase,
                FeedSource::Bybit,
                FeedSource::Okx,
            ],
            candles: vec![
                FeedSource::Kraken,
                FeedSource::Binance,
                FeedSource::Coinbase,
                FeedSource::Bybit,
                FeedSource::Okx,
            ],
            stream: true,
            quote_stale_ms: 25_000,
            push_stale_ms: 10_000,
            candle_stale_ms: 150_000,
            book_stale_ms: crate::orderbook::MAX_BOOK_AGE_MS,
            fail_limit: 2,
            recover_hold_ms: 60_000,
            max_deviation: 0.05,
            max_jump: 0.15,
            confirm_ms: 30_000,
            reference_age_ms: 180_000,
            reference_every_ms: 60_000,
            alert_after_ms: 5 * 60_000,
            quotes_every_ms: 12_000,
            candles_every_ms: 60_000,
            books_every_ms: 30_000,
        }
    }
}

impl FeedConfig {
    /// Defaults with the environment's overrides:
    ///
    /// * `PYTHIA_FEED_QUOTES`, `PYTHIA_FEED_CANDLES`: comma lists of source
    ///   ids (`kraken-ws,kraken,binance,coinbase,bybit,okx`), best first
    /// * `PYTHIA_FEED_STREAM=0`: no websocket, quotes are polled only
    /// * `PYTHIA_FEED_STALE_SEC`: polled quote stale time (default 25)
    /// * `PYTHIA_FEED_RECOVER_SEC`: hold before switching back (default 60)
    /// * `PYTHIA_FEED_MAX_DEVIATION_PCT`: cross-venue tolerance (default 5)
    /// * `PYTHIA_FEED_ALERT_MIN`: stale minutes before the webhook alert (default 5)
    pub fn from_env() -> FeedConfig {
        let get = |k: &str| std::env::var(k).ok().map(|v| v.trim().to_string()).filter(|v| !v.is_empty());
        let num = |k: &str| get(k).and_then(|v| v.parse::<f64>().ok()).filter(|v| v.is_finite() && *v > 0.0);
        let list = |k: &str| -> Option<Vec<FeedSource>> {
            let v: Vec<FeedSource> = get(k)?.split(',').filter_map(FeedSource::parse).collect();
            (!v.is_empty()).then_some(v)
        };
        let mut c = FeedConfig::default();
        if let Some(v) = list("PYTHIA_FEED_QUOTES") {
            c.quotes = v;
        }
        if let Some(v) = list("PYTHIA_FEED_CANDLES") {
            // The stream carries no candles.
            c.candles = v.into_iter().filter(|s| !s.is_push()).collect();
        }
        if matches!(get("PYTHIA_FEED_STREAM").as_deref(), Some("0" | "false" | "off" | "no")) {
            c.stream = false;
        }
        if let Some(s) = num("PYTHIA_FEED_STALE_SEC") {
            c.quote_stale_ms = (s * 1000.0) as i64;
        }
        if let Some(s) = num("PYTHIA_FEED_RECOVER_SEC") {
            c.recover_hold_ms = (s * 1000.0) as i64;
        }
        if let Some(p) = num("PYTHIA_FEED_MAX_DEVIATION_PCT") {
            c.max_deviation = p / 100.0;
        }
        if let Some(m) = num("PYTHIA_FEED_ALERT_MIN") {
            c.alert_after_ms = (m * 60_000.0) as i64;
        }
        c
    }
}

/// One market changing source.
#[derive(Debug, Clone, PartialEq)]
pub struct Switch {
    pub market: String,
    pub from: Option<FeedSource>,
    pub to: FeedSource,
}

impl Switch {
    /// A move further down the list: a failover rather than a first pick or a
    /// return to a better source.
    pub fn is_failover(&self, priority: &[FeedSource]) -> bool {
        let rank = |s: FeedSource| priority.iter().position(|p| *p == s).unwrap_or(usize::MAX);
        self.from.is_some_and(|f| rank(self.to) > rank(f))
    }
}

/// A value the sanity check refused.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Rejection {
    pub ts: i64,
    pub kind: DataKind,
    pub market: String,
    pub source: FeedSource,
    pub reason: String,
}

/// A run of refused quotes from one venue that agree with each other.
#[derive(Debug, Clone, Copy)]
struct Suspect {
    since: i64,
    price: f64,
    at: i64,
}

#[derive(Debug, Default, Clone)]
struct KindState {
    /// Last sane value per (source, market).
    seen: HashMap<(FeedSource, String), i64>,
    /// Start of the current gap-free run per (source, market).
    ok_since: HashMap<(FeedSource, String), i64>,
    fail_streak: HashMap<FeedSource, u32>,
    last_error: HashMap<FeedSource, String>,
    last_ok: HashMap<FeedSource, i64>,
    current: HashMap<String, FeedSource>,
    /// When the engine last took a value for this market.
    updated: HashMap<String, i64>,
    failovers: VecDeque<i64>,
}

/// The stream's connection state, as the drain loop reports it.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StreamStatus {
    pub enabled: bool,
    pub source: Option<FeedSource>,
    pub connected: bool,
    /// When the current session connected.
    pub since: Option<i64>,
    pub last_message: Option<i64>,
    pub reconnects: u32,
    pub last_error: Option<String>,
}

/// One source's standing in a kind's list.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SourceHealth {
    pub source: FeedSource,
    /// Markets currently on this source.
    pub markets: usize,
    pub fail_streak: u32,
    pub last_error: Option<String>,
    pub last_ok_age_sec: Option<u64>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct KindHealth {
    pub kind: DataKind,
    pub primary: Option<FeedSource>,
    /// The source most markets are on right now.
    pub active: Option<FeedSource>,
    pub sources: Vec<SourceHealth>,
    /// Age of the newest value the engine took, any market.
    pub last_update_age_sec: Option<u64>,
    /// Age of the oldest one: the market the engine knows least about.
    pub oldest_update_age_sec: Option<u64>,
    pub failovers_24h: u32,
    /// Markets whose data of this kind is stale right now.
    pub stale: Vec<String>,
    pub markets: usize,
}

/// Which source each market is on, per kind.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MarketFeed {
    pub market: String,
    pub quotes: Option<FeedSource>,
    pub candles: Option<FeedSource>,
    pub books: Option<FeedSource>,
    /// Why the latest quote was refused, while it still is.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub suspect: Option<String>,
}

/// The `dataHealth` section of the engine state.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DataHealth {
    /// A host is running the feeds. False in tests and the browser build.
    pub running: bool,
    /// No stale quotes and no stale candles. Books are left out: a stale book
    /// only means the calibrated cost defaults stand in.
    pub ok: bool,
    /// Start of the current stale episode.
    pub stale_since: Option<i64>,
    /// The webhook has been told about this episode.
    pub alerted: bool,
    pub kinds: Vec<KindHealth>,
    pub stream: StreamStatus,
    pub markets: Vec<MarketFeed>,
    /// The latest refused values, newest first.
    pub rejections: Vec<Rejection>,
}

/// The feed layer's state: who each market listens to and why.
#[derive(Debug, Clone)]
pub struct FeedHealth {
    cfg: FeedConfig,
    book_sources: Vec<FeedSource>,
    kinds: [KindState; 3],
    /// Newest accepted quote per (venue, market).
    accepted: HashMap<(&'static str, String), (f64, i64)>,
    /// Refused quotes per (venue, market) that may yet be confirmed.
    suspects: HashMap<(&'static str, String), Suspect>,
    /// Why each market's latest quote was refused, while it is.
    suspect_reason: HashMap<String, String>,
    last_good: HashMap<String, (f64, i64)>,
    want_reference: bool,
    last_reference: i64,
    rejections: VecDeque<Rejection>,
    started_at: Option<i64>,
    stale_since: Option<i64>,
    alerted: bool,
    stream: StreamStatus,
    /// Candle interval of the last refresh, for the "series is behind" check.
    candle_interval_ms: i64,
}

impl Default for FeedHealth {
    fn default() -> Self {
        FeedHealth::new(FeedConfig::default())
    }
}

const DAY_MS: i64 = 86_400_000;

impl FeedHealth {
    pub fn new(cfg: FeedConfig) -> FeedHealth {
        FeedHealth {
            cfg,
            book_sources: FeedSource::for_books(CostVenue::Kraken),
            kinds: Default::default(),
            accepted: HashMap::new(),
            suspects: HashMap::new(),
            suspect_reason: HashMap::new(),
            last_good: HashMap::new(),
            want_reference: false,
            last_reference: i64::MIN / 2,
            rejections: VecDeque::new(),
            started_at: None,
            stale_since: None,
            alerted: false,
            stream: StreamStatus::default(),
            candle_interval_ms: 5 * 60_000,
        }
    }

    pub fn config(&self) -> &FeedConfig {
        &self.cfg
    }

    /// Keep what has been learned, take the new tunables.
    pub fn set_config(&mut self, cfg: FeedConfig) {
        self.cfg = cfg;
    }

    pub fn set_book_sources(&mut self, sources: Vec<FeedSource>) {
        self.book_sources = sources;
    }

    /// A host has started the feeds. From here on, a market without data is
    /// stale rather than "not wired up".
    pub fn start(&mut self, now: i64) {
        self.started_at.get_or_insert(now);
    }

    pub fn started_at(&self) -> Option<i64> {
        self.started_at
    }

    pub fn set_stream(&mut self, s: StreamStatus) {
        self.stream = s;
    }

    pub fn set_candle_interval_ms(&mut self, ms: i64) {
        if ms > 0 {
            self.candle_interval_ms = ms;
        }
    }

    pub fn candle_interval_ms(&self) -> i64 {
        self.candle_interval_ms
    }

    /// Sources for a kind, best first.
    pub fn priority(&self, kind: DataKind) -> Vec<FeedSource> {
        match kind {
            DataKind::Quotes => self.cfg.quotes.iter().copied().filter(|s| self.cfg.stream || !s.is_push()).collect(),
            DataKind::Candles => self.cfg.candles.clone(),
            DataKind::Books => self.book_sources.clone(),
        }
    }

    fn rank(&self, kind: DataKind, s: FeedSource) -> usize {
        self.priority(kind).iter().position(|p| *p == s).unwrap_or(usize::MAX)
    }

    fn stale_ms(&self, kind: DataKind, s: FeedSource) -> i64 {
        match kind {
            DataKind::Quotes if s.is_push() => self.cfg.push_stale_ms,
            DataKind::Quotes => self.cfg.quote_stale_ms,
            DataKind::Candles => self.cfg.candle_stale_ms,
            DataKind::Books => self.cfg.book_stale_ms,
        }
    }

    fn k(&self, kind: DataKind) -> &KindState {
        &self.kinds[kind.idx()]
    }

    fn km(&mut self, kind: DataKind) -> &mut KindState {
        &mut self.kinds[kind.idx()]
    }

    /// The source has delivered a sane value for `market` recently and is not
    /// failing its polls.
    pub fn fresh(&self, kind: DataKind, s: FeedSource, market: &str, now: i64) -> bool {
        let k = self.k(kind);
        if k.fail_streak.get(&s).copied().unwrap_or(0) >= self.cfg.fail_limit {
            return false;
        }
        k.seen.get(&(s, market.to_string())).is_some_and(|t| now - t <= self.stale_ms(kind, s))
    }

    /// Fresh, and without a gap for the recovery hold.
    fn held(&self, kind: DataKind, s: FeedSource, market: &str, now: i64) -> bool {
        self.fresh(kind, s, market, now)
            && self.k(kind).ok_since.get(&(s, market.to_string())).is_some_and(|t| now - t >= self.cfg.recover_hold_ms)
    }

    pub fn current(&self, kind: DataKind, market: &str) -> Option<FeedSource> {
        self.k(kind).current.get(market).copied()
    }

    /// Whether `s` has to be asked this round: it carries a market already,
    /// or some market has no fresh source above it.
    pub fn needs_poll(&self, kind: DataKind, s: FeedSource, markets: &[String], now: i64) -> bool {
        !self.wanted(kind, s, markets, now).is_empty()
    }

    /// The markets `s` has to be asked about this round, by the rule of
    /// [`FeedHealth::needs_poll`]. Per-coin fetches (candles, books) ask a
    /// fallback only about these, so a coin no venue serves costs one request
    /// per source rather than the whole universe from each.
    pub fn wanted(&self, kind: DataKind, s: FeedSource, markets: &[String], now: i64) -> Vec<String> {
        let pri = self.priority(kind);
        let Some(pos) = pri.iter().position(|p| *p == s) else { return vec![] };
        markets
            .iter()
            .filter(|m| self.current(kind, m) == Some(s) || !pri[..pos].iter().any(|p| self.fresh(kind, *p, m, now)))
            .cloned()
            .collect()
    }

    /// Some market's current source is no longer fresh: worth polling down
    /// the list now rather than at the next regular round.
    pub fn needs_failover(&self, kind: DataKind, markets: &[String], now: i64) -> bool {
        markets.iter().any(|m| match self.current(kind, m) {
            Some(s) => !self.fresh(kind, s, m, now),
            None => false,
        })
    }

    /// A sane value for `market` from `s`, observed at `t`.
    pub fn observe(&mut self, kind: DataKind, s: FeedSource, market: &str, t: i64) {
        let stale = self.stale_ms(kind, s);
        let k = self.km(kind);
        let key = (s, market.to_string());
        let prev = k.seen.get(&key).copied();
        let gap = prev.is_none_or(|p| t - p > stale);
        if gap || !k.ok_since.contains_key(&key) {
            k.ok_since.insert(key.clone(), t);
        }
        k.seen.insert(key, prev.map_or(t, |p| p.max(t)));
    }

    /// A poll of `s` answered. Resets its failure streak.
    pub fn poll_ok(&mut self, kind: DataKind, s: FeedSource, now: i64) {
        let k = self.km(kind);
        k.fail_streak.insert(s, 0);
        k.last_error.remove(&s);
        k.last_ok.insert(s, now);
    }

    /// A poll of `s` failed. Any recovery hold it had restarts.
    pub fn poll_failed(&mut self, kind: DataKind, s: FeedSource, error: &str) {
        let k = self.km(kind);
        *k.fail_streak.entry(s).or_default() += 1;
        k.last_error.insert(s, error.chars().take(200).collect());
        k.ok_since.retain(|(src, _), _| *src != s);
    }

    /// The error of the source's latest failed poll, while it is failing.
    pub fn last_error(&self, kind: DataKind, s: FeedSource) -> Option<&str> {
        self.k(kind).last_error.get(&s).map(String::as_str)
    }

    /// Re-decide every market's source for `kind`. Returns the switches; a
    /// round with at least one failover is counted once in the 24 h tally.
    pub fn reselect(&mut self, kind: DataKind, markets: &[String], now: i64) -> Vec<Switch> {
        let pri = self.priority(kind);
        let mut out = Vec::new();
        for m in markets {
            let cur = self.current(kind, m);
            let target = match cur {
                Some(c) if self.fresh(kind, c, m, now) => {
                    let rc = self.rank(kind, c);
                    pri.iter().take(rc.min(pri.len())).copied().find(|s| self.held(kind, *s, m, now))
                }
                // No source yet, or the current one went stale: the best fresh one, up or down.
                _ => pri.iter().copied().find(|s| self.fresh(kind, *s, m, now)),
            };
            if let Some(to) = target.filter(|t| Some(*t) != cur) {
                self.km(kind).current.insert(m.clone(), to);
                out.push(Switch { market: m.clone(), from: cur, to });
            }
        }
        if out.iter().any(|s| s.is_failover(&pri)) {
            let k = self.km(kind);
            k.failovers.push_back(now);
            while k.failovers.front().is_some_and(|t| now - *t > DAY_MS) {
                k.failovers.pop_front();
            }
        }
        out
    }

    /// The engine took a value of `kind` for `market` at `t`.
    pub fn mark_updated(&mut self, kind: DataKind, market: &str, t: i64) {
        self.km(kind).updated.insert(market.to_string(), t);
    }

    pub fn updated(&self, kind: DataKind, market: &str) -> Option<i64> {
        self.k(kind).updated.get(market).copied()
    }

    pub fn failovers_24h(&self, kind: DataKind, now: i64) -> u32 {
        self.k(kind).failovers.iter().filter(|t| now - **t <= DAY_MS).count() as u32
    }

    // ── sanity ───────────────────────────────────────────────────────────

    /// Decide whether a quote may become the mark. `Err` carries the reason.
    ///
    /// Other venues are asked first: agreeing with any recent price of
    /// another venue (accepted, or refused but itself waiting for a second
    /// opinion) is enough, which is how two venues that both moved 8 % in a
    /// minute confirm each other. Disagreeing with every one of them is a bad
    /// tick. Only without another venue does the jump rule apply.
    pub fn check_quote(&mut self, s: FeedSource, market: &str, price: f64, t: i64) -> Result<(), String> {
        if !(price.is_finite() && price > 0.0) {
            return Err(self.refuse(s, market, price, t, "not a positive price".into(), false));
        }
        let venue = s.venue();
        let tol = self.cfg.max_deviation;
        let max_age = self.cfg.reference_age_ms;
        let off = |x: f64| (price / x - 1.0).abs();

        let mut confirmed = false;
        let mut nearest: Option<(&'static str, f64)> = None;
        for ((v, m), (p, at)) in &self.accepted {
            if m != market || *v == venue || t - at > max_age {
                continue;
            }
            if off(*p) <= tol {
                confirmed = true;
            } else if nearest.is_none_or(|(_, q)| off(*p) < off(q)) {
                nearest = Some((v, *p));
            }
        }
        for ((v, m), sus) in &self.suspects {
            if m == market && *v != venue && t - sus.at <= max_age && off(sus.price) <= tol {
                confirmed = true;
            }
        }
        if !confirmed {
            if let Some((v, p)) = nearest {
                let why = format!("{:.1}% away from {v} ({})", off(p) * 100.0, fmt_price(p));
                return Err(self.refuse(s, market, price, t, why, true));
            }
            if let Some((g, at)) = self.last_good.get(market).copied() {
                let jump = off(g);
                if t - at <= 3_600_000 && jump > self.cfg.max_jump {
                    let repeated = self
                        .suspects
                        .get(&(venue, market.to_string()))
                        .is_some_and(|sus| off(sus.price) <= tol && t - sus.since >= self.cfg.confirm_ms);
                    if !repeated {
                        let why = format!(
                            "jumped {:.1}% from the last good price, waiting for a second venue or {} s of the same",
                            jump * 100.0,
                            self.cfg.confirm_ms / 1000
                        );
                        return Err(self.refuse(s, market, price, t, why, true));
                    }
                }
            }
        }
        self.accepted.insert((venue, market.to_string()), (price, t));
        self.last_good.insert(market.to_string(), (price, t));
        self.suspects.remove(&(venue, market.to_string()));
        self.suspect_reason.remove(market);
        Ok(())
    }

    fn refuse(&mut self, s: FeedSource, market: &str, price: f64, t: i64, why: String, keep: bool) -> String {
        if keep {
            let key = (s.venue(), market.to_string());
            let tol = self.cfg.max_deviation;
            match self.suspects.get_mut(&key) {
                Some(sus) if (price / sus.price - 1.0).abs() <= tol => {
                    sus.price = price;
                    sus.at = t;
                }
                _ => {
                    self.suspects.insert(key, Suspect { since: t, price, at: t });
                }
            }
            self.want_reference = true;
        }
        self.reject(DataKind::Quotes, s, market, t, &why);
        self.suspect_reason.insert(market.to_string(), format!("{}: {why}", s.label()));
        why
    }

    /// Note a refused value for the health report.
    pub fn reject(&mut self, kind: DataKind, s: FeedSource, market: &str, t: i64, why: &str) {
        self.rejections.push_front(Rejection { ts: t, kind, market: market.to_string(), source: s, reason: why.to_string() });
        self.rejections.truncate(20);
    }

    /// Why the market's latest quote was refused, while it still is.
    pub fn suspect(&self, market: &str) -> Option<&str> {
        self.suspect_reason.get(market).map(String::as_str)
    }

    /// The other venue to ask for a reference price now, if one is due: on a
    /// timer, or sooner after a refused quote. The pick is the best quote
    /// source of a different venue than the one most markets are on that is
    /// not currently failing.
    pub fn take_reference(&mut self, markets: &[String], now: i64) -> Option<FeedSource> {
        let due = now - self.last_reference >= self.cfg.reference_every_ms
            || (self.want_reference && now - self.last_reference >= 5_000);
        if !due {
            return None;
        }
        let active = self.active(DataKind::Quotes, markets).map(FeedSource::venue);
        let pri: Vec<FeedSource> = self.priority(DataKind::Quotes).into_iter().filter(|s| !s.is_push()).collect();
        let others: Vec<FeedSource> = pri.into_iter().filter(|s| Some(s.venue()) != active).collect();
        let streak = |s: &FeedSource| self.k(DataKind::Quotes).fail_streak.get(s).copied().unwrap_or(0);
        let pick = others.iter().copied().find(|s| streak(s) < self.cfg.fail_limit).or(others.first().copied())?;
        self.last_reference = now;
        self.want_reference = false;
        Some(pick)
    }

    /// The source most of `markets` are on.
    pub fn active(&self, kind: DataKind, markets: &[String]) -> Option<FeedSource> {
        let mut counts: HashMap<FeedSource, usize> = HashMap::new();
        for m in markets {
            if let Some(s) = self.current(kind, m) {
                *counts.entry(s).or_default() += 1;
            }
        }
        let rank = |s: &FeedSource| self.rank(kind, *s);
        counts.into_iter().max_by(|a, b| a.1.cmp(&b.1).then(rank(&b.0).cmp(&rank(&a.0)))).map(|(s, _)| s)
    }

    // ── staleness episodes, for the webhook ─────────────────────────────

    /// Feed the current stale state in once per tick. Returns what to say:
    /// `Some(true)` the moment an episode passes the alert time, `Some(false)`
    /// when an alerted episode ends.
    pub fn track_episode(&mut self, stale: bool, now: i64) -> Option<bool> {
        if stale {
            let since = *self.stale_since.get_or_insert(now);
            if !self.alerted && now - since >= self.cfg.alert_after_ms {
                self.alerted = true;
                return Some(true);
            }
            None
        } else {
            self.stale_since = None;
            if std::mem::take(&mut self.alerted) {
                return Some(false);
            }
            None
        }
    }

    pub fn stale_since(&self) -> Option<i64> {
        self.stale_since
    }

    // ── the report ──────────────────────────────────────────────────────

    pub fn kind_health(&self, kind: DataKind, markets: &[String], stale: Vec<String>, now: i64) -> KindHealth {
        let k = self.k(kind);
        let pri = self.priority(kind);
        let ages: Vec<i64> = markets.iter().filter_map(|m| k.updated.get(m)).map(|t| now - t).collect();
        let sec = |ms: i64| (ms.max(0) / 1000) as u64;
        KindHealth {
            kind,
            primary: pri.first().copied(),
            active: self.active(kind, markets),
            sources: pri
                .iter()
                .map(|s| SourceHealth {
                    source: *s,
                    markets: markets.iter().filter(|m| self.current(kind, m) == Some(*s)).count(),
                    fail_streak: k.fail_streak.get(s).copied().unwrap_or(0),
                    last_error: k.last_error.get(s).cloned(),
                    last_ok_age_sec: k.last_ok.get(s).map(|t| sec(now - t)),
                })
                .collect(),
            last_update_age_sec: ages.iter().min().map(|a| sec(*a)),
            oldest_update_age_sec: ages.iter().max().map(|a| sec(*a)),
            failovers_24h: self.failovers_24h(kind, now),
            stale,
            markets: markets.len(),
        }
    }

    pub fn report(&self, kinds: Vec<KindHealth>, markets: &[String]) -> DataHealth {
        let ok = kinds.iter().filter(|k| k.kind != DataKind::Books).all(|k| k.stale.is_empty());
        DataHealth {
            running: self.started_at.is_some(),
            ok,
            stale_since: self.stale_since,
            alerted: self.alerted,
            kinds,
            stream: self.stream.clone(),
            markets: markets
                .iter()
                .map(|m| MarketFeed {
                    market: m.clone(),
                    quotes: self.current(DataKind::Quotes, m),
                    candles: self.current(DataKind::Candles, m),
                    books: self.current(DataKind::Books, m),
                    suspect: self.suspect_reason.get(m).cloned(),
                })
                .collect(),
            rejections: self.rejections.iter().take(10).cloned().collect(),
        }
    }
}

/// A price for a journal line: enough digits for PEPE and for BTC alike.
pub fn fmt_price(p: f64) -> String {
    if p >= 100.0 {
        format!("{p:.2}")
    } else if p >= 1.0 {
        format!("{p:.4}")
    } else {
        format!("{p:.3e}")
    }
}

/// "BTC/USD, ETH/USD and 18 more", from market ids.
pub fn list_markets(ids: &[String]) -> String {
    let names: Vec<&str> = ids.iter().map(|i| i.split_once(':').map_or(i.as_str(), |(_, s)| s)).collect();
    match names.len() {
        0 => "no markets".into(),
        1..=3 => names.join(", "),
        n => format!("{} and {} more", names[..2].join(", "), n - 2),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use FeedSource::*;

    const T0: i64 = 1_790_000_000_000;

    fn ids(n: usize) -> Vec<String> {
        ["BTC/USD", "ETH/USD", "SOL/USD", "TRX/USD"].iter().take(n).map(|s| format!("crypto:{s}")).collect()
    }

    /// Polled quotes only, so the tests read like the REST cascade.
    fn rest() -> FeedHealth {
        FeedHealth::new(FeedConfig { stream: false, ..FeedConfig::default() })
    }

    /// One poll round of `s` delivering every market in `ms` at `now`.
    fn deliver(f: &mut FeedHealth, kind: DataKind, s: FeedSource, ms: &[String], now: i64) -> Vec<Switch> {
        for m in ms {
            f.observe(kind, s, m, now);
        }
        f.poll_ok(kind, s, now);
        f.reselect(kind, ms, now)
    }

    fn fail(f: &mut FeedHealth, kind: DataKind, s: FeedSource, ms: &[String], _now: i64) {
        f.poll_failed(kind, s, "timeout");
        let _ = ms;
    }

    #[test]
    fn the_first_source_to_deliver_is_adopted_without_counting_a_failover() {
        let mut f = rest();
        let ms = ids(2);
        let sw = deliver(&mut f, DataKind::Quotes, Kraken, &ms, T0);
        assert_eq!(sw.len(), 2);
        assert!(sw.iter().all(|s| s.from.is_none() && s.to == Kraken));
        assert_eq!(f.failovers_24h(DataKind::Quotes, T0), 0);
        assert_eq!(f.active(DataKind::Quotes, &ms), Some(Kraken));
    }

    #[test]
    fn failover_walks_the_priority_list_in_order() {
        let mut f = rest();
        let ms = ids(2);
        deliver(&mut f, DataKind::Quotes, Kraken, &ms, T0);

        // Kraken fails twice: down, even though its last value is young.
        let t = T0 + 12_000;
        fail(&mut f, DataKind::Quotes, Kraken, &ms, t);
        assert!(f.fresh(DataKind::Quotes, Kraken, &ms[0], t), "one failure is not an outage");
        let t = T0 + 24_000;
        fail(&mut f, DataKind::Quotes, Kraken, &ms, t);
        assert!(!f.fresh(DataKind::Quotes, Kraken, &ms[0], t));
        // The cascade now has to ask Binance, and Coinbase only if Binance fails too.
        assert!(f.needs_poll(DataKind::Quotes, Binance, &ms, t));
        let sw = deliver(&mut f, DataKind::Quotes, Binance, &ms, t);
        assert!(sw.iter().all(|s| s.from == Some(Kraken) && s.to == Binance));
        assert!(!f.needs_poll(DataKind::Quotes, Coinbase, &ms, t), "Binance covers every market");
        assert_eq!(f.failovers_24h(DataKind::Quotes, t), 1, "one round, one failover, however many markets");

        // Binance goes stale too: Coinbase next, never back up to a dead Kraken.
        let t = t + 26_000;
        assert!(f.needs_failover(DataKind::Quotes, &ms, t));
        assert!(f.needs_poll(DataKind::Quotes, Coinbase, &ms, t));
        let sw = deliver(&mut f, DataKind::Quotes, Coinbase, &ms, t);
        assert!(sw.iter().all(|s| s.from == Some(Binance) && s.to == Coinbase));
        assert_eq!(f.failovers_24h(DataKind::Quotes, t), 2);
        // A day later the tally has forgotten them.
        assert_eq!(f.failovers_24h(DataKind::Quotes, t + DAY_MS + 1), 0);
    }

    #[test]
    fn a_coin_missing_on_the_fallback_moves_on_alone() {
        let mut f = rest();
        let ms = ids(4); // TRX is not listed on Coinbase
        deliver(&mut f, DataKind::Quotes, Kraken, &ms, T0);
        let t = T0 + 30_000;
        for s in [Kraken, Binance] {
            f.poll_failed(DataKind::Quotes, s, "HTTP 503");
            f.poll_failed(DataKind::Quotes, s, "HTTP 503");
        }
        deliver(&mut f, DataKind::Quotes, Coinbase, &ms[..3], t);
        f.reselect(DataKind::Quotes, &ms, t);
        assert_eq!(f.current(DataKind::Quotes, "crypto:TRX/USD"), Some(Kraken), "nothing fresh yet: stays put, stale");
        assert!(f.needs_poll(DataKind::Quotes, Bybit, &ms, t), "TRX still needs a source");
        assert_eq!(f.wanted(DataKind::Quotes, Bybit, &ms, t), vec!["crypto:TRX/USD".to_string()], "and only TRX");
        deliver(&mut f, DataKind::Quotes, Bybit, &ms[3..], t);
        f.reselect(DataKind::Quotes, &ms, t);
        assert_eq!(f.current(DataKind::Quotes, "crypto:TRX/USD"), Some(Bybit));
        assert_eq!(f.current(DataKind::Quotes, "crypto:BTC/USD"), Some(Coinbase));
    }

    #[test]
    fn switching_back_waits_until_the_primary_has_held_for_the_recovery_time() {
        let mut f = rest();
        let ms = ids(1);
        deliver(&mut f, DataKind::Quotes, Kraken, &ms, T0);
        f.poll_failed(DataKind::Quotes, Kraken, "timeout");
        f.poll_failed(DataKind::Quotes, Kraken, "timeout");
        let mut t = T0 + 24_000;
        deliver(&mut f, DataKind::Quotes, Binance, &ms, t);
        assert_eq!(f.current(DataKind::Quotes, &ms[0]), Some(Binance));

        // Kraken answers again; Binance keeps delivering. 48 s is not enough.
        let back = t + 12_000;
        t = back;
        while t < back + 60_000 {
            deliver(&mut f, DataKind::Quotes, Kraken, &ms, t);
            let sw = deliver(&mut f, DataKind::Quotes, Binance, &ms, t);
            assert!(sw.is_empty(), "switched back after only {} s", (t - back) / 1000);
            t += 12_000;
        }
        // A wobble restarts the clock.
        f.poll_failed(DataKind::Quotes, Kraken, "timeout");
        deliver(&mut f, DataKind::Quotes, Kraken, &ms, t);
        assert!(deliver(&mut f, DataKind::Quotes, Binance, &ms, t).is_empty());
        let restart = t;
        while t - restart < 60_000 {
            t += 12_000;
            deliver(&mut f, DataKind::Quotes, Kraken, &ms, t);
            deliver(&mut f, DataKind::Quotes, Binance, &ms, t);
        }
        assert_eq!(f.current(DataKind::Quotes, &ms[0]), Some(Kraken), "a full minute of Kraken: back on it");
        assert_eq!(f.failovers_24h(DataKind::Quotes, t), 1, "the return is not a failover");
    }

    #[test]
    fn the_stream_fails_over_on_its_own_short_clock() {
        let mut f = FeedHealth::default();
        let ms = ids(1);
        deliver(&mut f, DataKind::Quotes, KrakenWs, &ms, T0);
        // 11 s of silence on a stream that beats every second.
        let t = T0 + 11_000;
        assert!(!f.fresh(DataKind::Quotes, KrakenWs, &ms[0], t));
        assert!(f.needs_poll(DataKind::Quotes, Kraken, &ms, t));
        let sw = deliver(&mut f, DataKind::Quotes, Kraken, &ms, t);
        assert_eq!(sw[0].to, Kraken);
        assert!(sw[0].is_failover(&f.priority(DataKind::Quotes)));
        // While the stream is healthy, REST Kraken is not polled at all.
        let mut g = FeedHealth::default();
        deliver(&mut g, DataKind::Quotes, KrakenWs, &ms, T0);
        assert!(!g.needs_poll(DataKind::Quotes, Kraken, &ms, T0 + 1_000));
    }

    #[test]
    fn a_quote_far_from_every_other_venue_is_rejected() {
        let mut f = rest();
        let m = "crypto:BTC/USD";
        f.check_quote(Binance, m, 80_000.0, T0).unwrap();
        // Kraken prints a fat finger 30% up.
        let why = f.check_quote(Kraken, m, 104_000.0, T0 + 5_000).unwrap_err();
        assert!(why.contains("away from binance"), "{why}");
        assert!(f.suspect(m).is_some());
        // A reference poll is wanted soon, not in a minute.
        let ms = vec![m.to_string()];
        f.last_reference = T0;
        assert_eq!(f.take_reference(&ms, T0 + 4_000), None, "5 s minimum between reference polls");
        assert!(f.take_reference(&ms, T0 + 5_000).is_some(), "but not the regular minute");
        // The next sane Kraken print is fine and clears the flag.
        f.check_quote(Kraken, m, 80_100.0, T0 + 12_000).unwrap();
        assert!(f.suspect(m).is_none());
    }

    #[test]
    fn two_venues_that_moved_together_confirm_each_other() {
        let mut f = rest();
        let m = "crypto:SOL/USD";
        f.check_quote(Kraken, m, 100.0, T0).unwrap();
        f.check_quote(Binance, m, 100.1, T0 + 1_000).unwrap();
        // A real crash: Kraken first, Binance's last view is still the old level.
        assert!(f.check_quote(Kraken, m, 88.0, T0 + 30_000).is_err());
        // Binance is polled as the reference and sees the same level: the
        // refused Kraken print vouches for it, and then it vouches for Kraken.
        f.check_quote(Binance, m, 88.2, T0 + 35_000).unwrap();
        f.check_quote(Kraken, m, 87.9, T0 + 42_000).unwrap();
    }

    #[test]
    fn a_lone_venue_jump_waits_for_confirmation() {
        let mut f = rest();
        let m = "crypto:ETH/USD";
        f.check_quote(Kraken, m, 2_500.0, T0).unwrap();
        // No other venue known; a 20% jump is held...
        assert!(f.check_quote(Kraken, m, 3_000.0, T0 + 12_000).is_err());
        assert!(f.check_quote(Kraken, m, 3_010.0, T0 + 24_000).is_err(), "12 s of the same is not enough");
        // ...until the same venue has said it for 30 s.
        f.check_quote(Kraken, m, 3_005.0, T0 + 42_000).unwrap();
        // A small move needs nothing.
        f.check_quote(Kraken, m, 3_050.0, T0 + 54_000).unwrap();
    }

    #[test]
    fn junk_is_never_a_price() {
        let mut f = rest();
        for p in [0.0, -1.0, f64::NAN, f64::INFINITY] {
            assert!(f.check_quote(Kraken, "crypto:BTC/USD", p, T0).is_err());
        }
    }

    #[test]
    fn a_reference_is_another_venue_than_the_active_one() {
        let mut f = rest();
        let ms = ids(2);
        deliver(&mut f, DataKind::Quotes, Kraken, &ms, T0);
        assert_eq!(f.take_reference(&ms, T0), Some(Binance));
        assert_eq!(f.take_reference(&ms, T0 + 30_000), None, "not due yet");
        // Binance is down: the next venue serves.
        f.poll_failed(DataKind::Quotes, Binance, "HTTP 451");
        f.poll_failed(DataKind::Quotes, Binance, "HTTP 451");
        assert_eq!(f.take_reference(&ms, T0 + 61_000), Some(Coinbase));
        // On Binance, Kraken is the reference.
        let mut g = rest();
        deliver(&mut g, DataKind::Quotes, Binance, &ms, T0);
        assert_eq!(g.take_reference(&ms, T0), Some(Kraken));
    }

    #[test]
    fn the_webhook_hears_once_when_stale_and_once_when_it_recovers() {
        let mut f = rest();
        assert_eq!(f.track_episode(true, T0), None);
        assert_eq!(f.track_episode(true, T0 + 4 * 60_000), None);
        assert_eq!(f.track_episode(true, T0 + 5 * 60_000), Some(true));
        assert_eq!(f.track_episode(true, T0 + 6 * 60_000), None, "once per episode");
        assert_eq!(f.track_episode(false, T0 + 7 * 60_000), Some(false));
        assert_eq!(f.track_episode(false, T0 + 8 * 60_000), None);
        // A short blip never alerts, so it never "recovers" either.
        assert_eq!(f.track_episode(true, T0 + 9 * 60_000), None);
        assert_eq!(f.track_episode(false, T0 + 10 * 60_000), None);
    }

    #[test]
    fn book_sources_are_the_executing_venue_only() {
        assert_eq!(FeedSource::for_books(CostVenue::Kraken), vec![Kraken]);
        assert_eq!(FeedSource::for_books(CostVenue::Binance), vec![Binance, BinanceVision]);
        assert!(FeedSource::for_books(CostVenue::Okx).is_empty());
    }

    #[test]
    fn source_ids_round_trip_and_serialise_as_kebab_case() {
        for s in FeedSource::ALL {
            assert_eq!(FeedSource::parse(s.id()), Some(s));
            assert_eq!(serde_json::to_value(s).unwrap(), s.id());
        }
        assert_eq!(FeedSource::parse(" Binance "), Some(Binance));
        assert_eq!(FeedSource::parse("nasdaq"), None);
    }

    #[test]
    fn market_lists_stay_short() {
        assert_eq!(list_markets(&ids(2)), "BTC/USD, ETH/USD");
        let many: Vec<String> = (0..20).map(|i| format!("crypto:C{i}/USD")).collect();
        assert_eq!(list_markets(&many), "C0/USD, C1/USD and 18 more");
    }
}
