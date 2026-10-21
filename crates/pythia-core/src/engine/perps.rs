//! Perpetual futures in the engine: markets, the demo route's gates, funding
//! booked per position, and the reconciliation against the demo account.
//!
//! The lab's market-neutral M4 book (`lab:m4_perps`, signal `asset_class`
//! `"perp"`, signed weights) is the reason this exists: shorts are allowed
//! here and nowhere else in the engine. Its markets are `perp:<COIN>`
//! (`perp:BTC`), venue [`Venue::Perps`], quoted in the perps venue's own
//! contract unit at its mark price, created when a signal or a restored
//! position needs them (the venue lists hundreds of contracts; the engine
//! carries only the ones in play).
//!
//! - **Demo or paper, never live.** A live intent on a perps market is
//!   refused with [`PERPS_LIVE_REFUSED`] before anything is built, a perps
//!   strategy cannot be set Live, a live autopilot on perps is refused at
//!   start, and the connector layer has no live perps connector at all.
//! - **Sizing by notional, margin checked.** An order that grows a position
//!   must keep the autopilot's gross notional (positions plus orders still
//!   out) within [`PERP_MAX_GROSS_LEVERAGE`] times its equity, and on the demo
//!   route the account's available margin must cover the added notional at
//!   [`PERP_MARGIN_RATE`] (10x, the EU retail cap), read within
//!   [`PERP_ACCOUNT_MAX_AGE_MS`]. Reductions always pass.
//! - **Funding per position.** The host reads the venue's published funding
//!   history for every symbol held ([`Engine::perp_funding_due`]) and the
//!   engine books each settlement since the position's cursor: a long pays
//!   `rate x notional`, a short receives it (Kraken pro rata for the part of
//!   the hour held, Bybit in full to whoever holds at the settlement).
//!   Booked as realised P&L of the position's book and its autopilot, kept
//!   per position and in total, journaled once per symbol and batch.
//!   Paper positions accrue it too: the rates are the real market's.
//! - **Reconciliation every ten minutes** ([`PERP_RECONCILE_EVERY_MS`]), like
//!   the Alpaca paper route: the demo account's positions per symbol against
//!   the sum of every book's demo position there. Equal up to half a contract
//!   step is quiet; an order in flight waits; when only demo positions hold
//!   the symbol and they agree in sign with the venue, the venue wins (each
//!   book in proportion to what it held, booked to its autopilot at the
//!   mark); anything else is reported, never guessed.

use std::collections::{BTreeMap, HashMap};

use serde::{Deserialize, Serialize};

use super::{pos_key, Engine, FillRoute, JournalKind, Market, MarketKind, OrderStatus, RouteIntent};
use crate::connectors::perps::{
    FundingPoint, PerpAccount, PerpExchange, PerpInstrument, PerpTicker, KRAKEN_DEMO_GONE, PERPS_LIVE_REFUSED,
};
use crate::connectors::{BrokerPosition, OpenOrder, Side, Venue};
use crate::costs::CostVenue;

/// Market ids of perps: `perp:BTC`.
pub const PERP_PREFIX: &str = "perp:";
/// How often the host reconciles the perps demo account.
pub const PERP_RECONCILE_EVERY_MS: i64 = 10 * 60_000;
/// An autopilot's perps book may carry at most this gross notional per
/// dollar of its equity. M4 runs at about 1 (half long, half short).
pub const PERP_MAX_GROSS_LEVERAGE: f64 = 2.0;
/// Initial margin Pythia reserves per dollar of notional on the demo account:
/// 10x, the EU retail cap on Kraken's perps.
pub const PERP_MARGIN_RATE: f64 = 0.10;
/// The account read the margin check relies on must be this fresh.
pub const PERP_ACCOUNT_MAX_AGE_MS: i64 = 30 * 60_000;
/// Marks older than this keep perps orders back (the risk manager's own
/// staleness limit applies as well).
pub const PERP_TICKER_MAX_AGE_MS: i64 = 10 * 60_000;

/// The market id of a coin's perpetual.
pub fn perp_market_id(coin: &str) -> String {
    format!("{PERP_PREFIX}{}", coin.trim().to_ascii_uppercase())
}

/// How often the host asks for a symbol's funding history: Kraken's answer
/// is the whole hourly history (large), so every four hours; Bybit's is the
/// last 200 settlements, so every hour.
pub fn funding_check_every_ms(ex: PerpExchange) -> i64 {
    match ex {
        PerpExchange::KrakenFutures => 4 * 3_600_000,
        PerpExchange::Bybit => 3_600_000,
    }
}

/// One perps market as saved, so a restart can value and close what it holds
/// before the venue's contract list is read again.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PerpMarketSaved {
    pub id: String,
    pub coin: String,
    pub symbol: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub instrument: Option<PerpInstrument>,
}

/// What the perps layer saves with the engine state.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PerpsSaved {
    #[serde(default)]
    pub exchange: Option<PerpExchange>,
    #[serde(default)]
    pub markets: Vec<PerpMarketSaved>,
    /// Per position key: funding is booked for settlements after this time.
    #[serde(default)]
    pub funding_cursor: BTreeMap<String, i64>,
    /// Per position key: funding booked so far (negative = paid).
    #[serde(default)]
    pub funding_paid: BTreeMap<String, f64>,
    /// All funding booked so far, every book.
    #[serde(default)]
    pub funding_total: f64,
}

/// The perps layer's runtime state.
#[derive(Debug, Default)]
pub(crate) struct PerpsState {
    /// Whose contracts, marks and funding the perps markets use.
    pub(crate) exchange: Option<PerpExchange>,
    /// Demo keys are set for that venue.
    pub(crate) demo_ready: bool,
    /// Why the demo route cannot be used even with keys (Kraken's retired demo).
    pub(crate) route_error: Option<String>,
    /// The venue's contracts by coin.
    pub(crate) instruments: HashMap<String, PerpInstrument>,
    pub(crate) instruments_at: i64,
    pub(crate) tickers_at: i64,
    /// The funding rate the venue shows now, by symbol.
    pub(crate) funding_now: HashMap<String, f64>,
    pub(crate) account: Option<PerpAccount>,
    pub(crate) account_at: i64,
    pub(crate) account_error: Option<String>,
    pub(crate) reconcile: Option<PerpReconcile>,
    pub(crate) reconcile_noted: HashMap<String, String>,
    pub(crate) funding_cursor: HashMap<String, i64>,
    pub(crate) funding_paid: HashMap<String, f64>,
    pub(crate) funding_total: f64,
    /// When each symbol's funding was last read.
    pub(crate) funding_checked: HashMap<String, i64>,
}

/// What one symbol's reconciliation came out as.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum PerpCheckStatus {
    Ok,
    Pending,
    Corrected,
    StrayOrder,
    Mismatch,
    Untracked,
}

impl PerpCheckStatus {
    pub fn settled(self) -> bool {
        matches!(self, PerpCheckStatus::Ok | PerpCheckStatus::Pending | PerpCheckStatus::Corrected)
    }
}

/// One symbol of the perps demo account.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PerpCheck {
    pub symbol: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub market: Option<String>,
    /// The books' summed demo position (signed), before this run changed it.
    pub pythia: f64,
    /// What the venue holds (signed).
    pub venue: f64,
    pub diff: f64,
    pub diff_usd: f64,
    pub status: PerpCheckStatus,
    pub note: String,
}

/// The last reconciliation of the perps demo account.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PerpReconcile {
    pub checked_at: i64,
    pub symbols: Vec<PerpCheck>,
    pub mismatches: usize,
    pub open_orders: usize,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub stray_orders: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(default)]
    pub failed_at: i64,
}

/// The perps layer for the UI (`live.perps`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PerpsStatus {
    /// `kraken_futures` or `bybit_perps`.
    pub exchange: String,
    pub label: String,
    /// The demo route can take an order now (keys set, host answering).
    pub demo_ready: bool,
    /// Why it cannot, when it cannot.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub demo_blocked: Option<String>,
    /// Contracts listed, markets carried, marks read when.
    pub listed: usize,
    pub markets: usize,
    pub tickers_at: i64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub account: Option<PerpAccount>,
    pub account_at: i64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub account_error: Option<String>,
    /// Funding booked so far over every book (negative = paid).
    pub funding_total: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reconcile: Option<PerpReconcile>,
    /// Open perps positions, long and short.
    pub longs: usize,
    pub shorts: usize,
    /// Always the same sentence: real-money perps are switched off.
    pub live: String,
}

impl Engine {
    // ── setup ───────────────────────────────────────────────────────────────

    /// Which perps venue the perps markets follow, and whether its demo keys
    /// are set. Hosts call it at startup and whenever credentials change.
    /// Without keys the markets still get real marks and funding (paper perps).
    pub fn set_perps_route(&mut self, exchange: Option<PerpExchange>, demo_ready: bool) {
        let changed = exchange != self.perps.exchange || demo_ready != self.perps.demo_ready;
        if exchange != self.perps.exchange {
            self.perps.instruments.clear();
            self.perps.route_error = None;
        }
        self.perps.exchange = exchange;
        self.perps.demo_ready = demo_ready && exchange.is_some();
        if self.perps.demo_ready {
            self.demo_venues.insert(Venue::Perps);
        } else {
            self.demo_venues.remove(&Venue::Perps);
        }
        if changed {
            if let Some(ex) = exchange {
                let msg = if self.perps.demo_ready {
                    format!("Perps demo route: {} demo account (virtual money). Real-money perps stay switched off.", ex.label())
                } else {
                    format!("Perps: marks and funding from {}; no demo keys, so perps trade on paper only.", ex.label())
                };
                self.log(JournalKind::System, msg, None, None);
            }
        }
    }

    /// The perps venue in use, if any.
    pub fn perps_exchange(&self) -> Option<PerpExchange> {
        self.perps.exchange
    }

    /// The cost venue perps orders are modelled with.
    pub(super) fn perp_cost_venue(&self) -> CostVenue {
        CostVenue::for_perps(self.perps.exchange.unwrap_or(PerpExchange::KrakenFutures))
    }

    /// A read of the demo account failed in a way that says the route is
    /// gone, not that it blinked (Kraken's retired demo). Kept until a read
    /// succeeds; demo orders are refused with it meanwhile.
    pub fn set_perps_route_error(&mut self, why: Option<String>) {
        if why != self.perps.route_error {
            if let Some(w) = &why {
                self.log(JournalKind::Risk, format!("Perps demo route unavailable: {w}"), None, None);
            }
            self.perps.route_error = why;
        }
    }

    /// The venue's contract list. Markets for coins a perps signal names or
    /// a position holds are created (or get their symbol) now.
    pub fn set_perp_instruments(&mut self, list: Vec<PerpInstrument>) {
        if list.is_empty() {
            return;
        }
        let first = self.perps.instruments.is_empty();
        self.perps.instruments = list.into_iter().map(|i| (i.coin.clone(), i)).collect();
        self.perps.instruments_at = self.now();
        let wanted: Vec<String> = self
            .lab_signals
            .values()
            .filter(|s| s.is_perp())
            .flat_map(|s| s.weights.keys().cloned())
            .chain(self.markets.iter().filter(|m| m.venue == Venue::Perps).filter_map(|m| m.id.strip_prefix(PERP_PREFIX).map(str::to_string)))
            .collect();
        for coin in wanted {
            self.ensure_perp_market(&coin);
        }
        if first {
            let ex = self.perps.exchange.map(|e| e.label()).unwrap_or("the perps venue");
            let n = self.perps.instruments.len();
            self.log(JournalKind::System, format!("Perps: {ex} lists {n} perpetual contracts"), None, None);
        }
    }

    /// How often the marks should be read now: every 15 s while a perps
    /// position is open or a perps autopilot runs (the risk manager refuses
    /// orders on data older than 30 s), every 5 minutes while perps markets
    /// only exist, never without any. The venue's ticker list is the whole
    /// venue, so it is not read faster than needed.
    pub fn perp_marks_every_ms(&self) -> Option<i64> {
        let busy = self.positions.values().any(|p| p.venue == Venue::Perps && p.qty.abs() > 1e-12)
            || self.autopilots.iter().any(|a| {
                a.is_active() && a.config.asset_class == Some(Venue::Perps)
            });
        if busy {
            Some(15_000)
        } else if self.markets.iter().any(|m| m.venue == Venue::Perps) {
            Some(300_000)
        } else {
            None
        }
    }

    /// Whether the venue's contract list is due a read (every 24 h).
    pub fn perp_instruments_due(&self) -> bool {
        self.perps.exchange.is_some() && (self.perps.instruments.is_empty() || self.now() - self.perps.instruments_at > 24 * 3_600_000)
    }

    /// The perps market for `coin`, created when the venue lists it. `None`
    /// when it does not (or the list has not been read and no market exists).
    pub(super) fn ensure_perp_market(&mut self, coin: &str) -> Option<String> {
        let coin = crate::connectors::perps::alias(coin);
        let id = perp_market_id(&coin);
        let inst = self.perps.instruments.get(&coin).cloned();
        if let Some(m) = self.markets.iter_mut().find(|m| m.id == id) {
            if let Some(i) = &inst {
                m.symbol = i.symbol.clone();
            }
            return Some(id);
        }
        let i = inst?;
        self.markets.push(Market {
            id: id.clone(),
            venue: Venue::Perps,
            symbol: i.symbol.clone(),
            kind: MarketKind::Crypto,
            price: 0.0,
            change24h: 0.0,
            model_prob: None,
            liquidity: None,
            regime: None,
            trend_strength: None,
            no_price: None,
            resolves_at: None,
            updated_at: 0,
        });
        Some(id)
    }

    /// The contract of a perps market.
    pub(super) fn perp_instrument_of(&self, m: &Market) -> Option<&PerpInstrument> {
        let coin = m.id.strip_prefix(PERP_PREFIX)?;
        self.perps.instruments.get(coin).filter(|i| i.symbol == m.symbol)
    }

    /// A quantity rounded down to the contract's step (unchanged when the
    /// contract is unknown; the connector rounds again).
    pub(super) fn perp_round_qty(&self, m: &Market, qty: f64) -> f64 {
        match self.perp_instrument_of(m) {
            Some(i) => i.round_qty(qty),
            None => qty,
        }
    }

    /// Marks and current funding. Prices are the venue's mark; the markets are
    /// real-fed from the first ticker on, so the simulator never moves them.
    pub fn apply_perp_tickers(&mut self, tickers: &[PerpTicker]) {
        let now = self.now();
        let by: HashMap<&str, &PerpTicker> = tickers.iter().map(|t| (t.symbol.as_str(), t)).collect();
        let mut fed = Vec::new();
        for m in self.markets.iter_mut().filter(|m| m.venue == Venue::Perps) {
            let Some(t) = by.get(m.symbol.as_str()) else { continue };
            if !(t.mark > 0.0 && t.mark.is_finite()) || t.suspended {
                continue;
            }
            m.price = t.mark;
            m.updated_at = now;
            fed.push(m.id.clone());
        }
        for id in fed {
            self.real_ids.insert(id);
        }
        for t in tickers {
            if let Some(r) = t.funding_rate {
                self.perps.funding_now.insert(t.symbol.clone(), r);
            }
        }
        self.perps.tickers_at = now;
    }

    // ── funding ─────────────────────────────────────────────────────────────

    /// A fill on a perps market changed position `key`: a new (or flipped)
    /// position owes funding from now on; a closed one owes nothing more.
    pub(super) fn perp_note_fill(&mut self, key: &str, was: f64, now_qty: Option<f64>) {
        let now = self.now();
        match now_qty {
            None => {
                self.perps.funding_cursor.remove(key);
            }
            Some(q) if was == 0.0 || q.signum() != was.signum() => {
                self.perps.funding_cursor.insert(key.to_string(), now);
            }
            Some(_) => {
                self.perps.funding_cursor.entry(key.to_string()).or_insert(now);
            }
        }
    }

    /// Symbols whose funding history the host should read now, each with the
    /// time after which settlements are still unbooked.
    pub fn perp_funding_due(&self) -> Vec<(String, i64)> {
        let Some(ex) = self.perps.exchange else { return vec![] };
        let now = self.now();
        let every = funding_check_every_ms(ex);
        let mut since: BTreeMap<String, i64> = BTreeMap::new();
        for (key, p) in &self.positions {
            if p.venue != Venue::Perps || p.qty.abs() < 1e-12 {
                continue;
            }
            let c = self.perps.funding_cursor.get(key).copied().unwrap_or(now);
            let e = since.entry(p.symbol.clone()).or_insert(c);
            *e = (*e).min(c);
        }
        since
            .into_iter()
            .filter(|(s, c)| {
                let checked = self.perps.funding_checked.get(s).copied().unwrap_or(0);
                now - checked >= every && now > *c
            })
            .collect()
    }

    /// Book the settled funding of `symbol` for every position held there.
    /// Returns what was booked in total (negative = paid).
    pub fn apply_perp_funding(&mut self, symbol: &str, points: &[FundingPoint]) -> f64 {
        let now = self.now();
        self.perps.funding_checked.insert(symbol.to_string(), now);
        let keys: Vec<String> = self
            .positions
            .iter()
            .filter(|(_, p)| p.venue == Venue::Perps && p.symbol == symbol && p.qty.abs() > 1e-12)
            .map(|(k, _)| k.clone())
            .collect();
        let mut total = 0.0;
        let mut periods = 0usize;
        for key in keys {
            let Some(p) = self.positions.get(&key) else { continue };
            let (qty, market, book, sid) = (p.qty, p.market.clone(), p.book.clone(), p.strategy_id.clone());
            let mark = self.price_of(&market);
            let mark = if mark > 0.0 { mark } else { p.avg_price };
            let cursor = self.perps.funding_cursor.get(&key).copied().unwrap_or(now);
            let mut amount = 0.0;
            let mut last = cursor;
            for pt in points.iter().filter(|pt| pt.settled_ms > cursor && pt.settled_ms <= now) {
                let frac = if pt.prorated && pt.period_ms > 0 {
                    ((pt.settled_ms - cursor) as f64 / pt.period_ms as f64).clamp(0.0, 1.0)
                } else {
                    1.0
                };
                let per_unit = pt.per_unit_usd.unwrap_or(pt.rate * mark);
                // A long pays a positive rate, a short receives it.
                amount += -qty * per_unit * frac;
                last = last.max(pt.settled_ms);
                periods += 1;
            }
            if last > cursor {
                self.perps.funding_cursor.insert(key.clone(), last);
            }
            if amount == 0.0 || !amount.is_finite() {
                continue;
            }
            total += amount;
            *self.perps.funding_paid.entry(key.clone()).or_insert(0.0) += amount;
            self.perps.funding_total += amount;
            self.realized_pnl += amount;
            self.cash += amount;
            if let Some(s) = self.strategies.iter_mut().find(|s| s.id == sid) {
                s.pnl += amount;
            }
            self.autopilot_on_funding(&book, &market, &sid, amount);
        }
        if total != 0.0 {
            self.log(
                JournalKind::Fill,
                format!(
                    "Funding {symbol}: {} over {periods} settlement(s) since the last booking ({}), booked as realised P&L of the positions held",
                    if total >= 0.0 { format!("received ${total:.4}") } else { format!("paid ${:.4}", -total) },
                    self.perps.exchange.map(|e| e.label()).unwrap_or("perps")
                ),
                None,
                Some(format!("{PERP_PREFIX}{symbol}")),
            );
        }
        total
    }

    /// Funding booked on one position so far.
    pub(super) fn perp_funding_of(&self, key: &str) -> Option<f64> {
        self.perps.funding_paid.get(key).copied()
    }

    // ── the gates ───────────────────────────────────────────────────────────

    /// Why an order on a perps market must not go out, or `None`. Live is
    /// refused outright; an order that grows a position must fit the
    /// autopilot's gross cap and, on the demo route, the account's margin.
    pub(super) fn perp_order_block(&self, book: &str, m: &Market, side: Side, qty: f64, price: f64, intent: RouteIntent) -> Option<String> {
        if m.venue != Venue::Perps {
            return None;
        }
        if matches!(intent, RouteIntent::Live | RouteIntent::LiveExit) {
            return Some(PERPS_LIVE_REFUSED.to_string());
        }
        let held = self.positions.get(&pos_key(book, &m.id)).map(|p| p.qty).unwrap_or(0.0);
        let signed = if side == Side::Buy { qty } else { -qty };
        let grows = (held + signed).abs() > held.abs() + 1e-12;
        if !grows {
            return None;
        }
        // The risk manager's kill switch stops buys; on perps a sell can open
        // a short, so it stops every order that grows a position.
        if self.limits.kill_switch {
            return Some("kill switch active".into());
        }
        let px = if price > 0.0 { price } else { m.price };
        let added = ((held + signed).abs() - held.abs()) * px;
        if let Some(i) = self.ap_of_book(book) {
            let ap = &self.autopilots[i];
            let equity = self.ap_equity(ap).max(0.0);
            let gross = self.ap_class_gross(ap, |v| v == Venue::Perps);
            let cap = equity * PERP_MAX_GROSS_LEVERAGE;
            if gross + added > cap + 1e-6 {
                return Some(format!(
                    "perps margin check: the autopilot would carry ${:.0} of gross notional, more than {PERP_MAX_GROSS_LEVERAGE:.0}x its equity of ${equity:.0}",
                    gross + added
                ));
            }
        }
        if intent == RouteIntent::Demo {
            let now = self.now();
            let Some(acc) = self.perps.account.as_ref().filter(|_| now - self.perps.account_at <= PERP_ACCOUNT_MAX_AGE_MS) else {
                return Some("perps margin check: the demo account's margin has not been read in the last 30 minutes".into());
            };
            // Orders already out that grow positions use margin too.
            let out: f64 = self
                .inflight
                .values()
                .filter(|f| f.demo && f.venue == Venue::Perps)
                .map(|f| (f.qty - f.booked_qty).max(0.0) * if f.arrival > 0.0 { f.arrival } else { px })
                .sum();
            let need = (added + out) * PERP_MARGIN_RATE;
            if acc.available_margin < need {
                return Some(format!(
                    "perps margin check: the demo account has ${:.2} of available margin, this order and those still out need about ${need:.2} at {:.0}x",
                    acc.available_margin,
                    1.0 / PERP_MARGIN_RATE
                ));
            }
        }
        None
    }

    /// Why the perps demo route cannot take an order now, or `None`.
    pub(super) fn perp_demo_block(&self) -> Option<String> {
        let Some(ex) = self.perps.exchange else {
            return Some("no perps venue is configured (PYTHIA_PERPS_DEMO)".into());
        };
        if !self.perps.demo_ready {
            return Some(format!(
                "no {} demo keys: perps demo orders need them (docs/KRAKEN-FUTURES-DEMO.md); paper perps work without",
                ex.label()
            ));
        }
        self.perps.route_error.clone()
    }

    // ── the account ─────────────────────────────────────────────────────────

    /// The demo account's margin, read by the host every minute or so.
    pub fn set_perp_account(&mut self, read: Result<PerpAccount, String>) {
        match read {
            Ok(a) => {
                self.perps.account = Some(a);
                self.perps.account_at = self.now();
                self.perps.account_error = None;
                if self.perps.route_error.is_some() {
                    self.set_perps_route_error(None);
                    self.log(JournalKind::System, "Perps demo route answers again".into(), None, None);
                }
            }
            Err(e) => {
                // Kraken's retired demo: the route is gone, not blinking.
                if e.contains(KRAKEN_DEMO_GONE) || e.contains("shut its futures demo") {
                    self.set_perps_route_error(Some(KRAKEN_DEMO_GONE.to_string()));
                }
                self.perps.account_error = Some(e);
            }
        }
    }

    /// The demo account's equity, when read recently: the cap on what demo
    /// perps autopilots may be given together.
    pub(super) fn perp_account_equity(&self) -> Option<f64> {
        let a = self.perps.account.as_ref()?;
        (self.now() - self.perps.account_at <= PERP_ACCOUNT_MAX_AGE_MS).then_some(a.equity)
    }

    // ── reconciliation ──────────────────────────────────────────────────────

    /// Whether the perps demo account should be reconciled at all.
    pub fn perp_reconcile_wanted(&self) -> bool {
        self.perps.demo_ready
    }

    /// A read for the reconciliation failed.
    pub fn perp_reconcile_failed(&mut self, why: &str) {
        let now = self.now();
        let r = self.perps.reconcile.get_or_insert_with(PerpReconcile::default);
        r.error = Some(why.to_string());
        r.failed_at = now;
    }

    /// Compare the demo account's positions (and open orders) with every
    /// book's demo perps positions, per symbol. Returns how many symbols are
    /// not settled. See the module docs for the rules.
    pub fn apply_perp_reconcile(&mut self, venue_positions: &[BrokerPosition], open: &[OpenOrder]) -> usize {
        let now = self.now();
        let label = self.perps.exchange.map(|e| e.label()).unwrap_or("perps").to_string();
        let mut venue: BTreeMap<String, (f64, f64)> = BTreeMap::new();
        for bp in venue_positions {
            let e = venue.entry(bp.symbol.clone()).or_insert((0.0, 0.0));
            e.0 += bp.qty;
            e.1 = bp.avg_price;
        }
        let mut holders: BTreeMap<String, Vec<(String, f64)>> = BTreeMap::new();
        for (key, p) in &self.positions {
            if p.venue == Venue::Perps && p.demo && p.qty.abs() > 1e-12 {
                holders.entry(p.symbol.clone()).or_default().push((key.clone(), p.qty));
            }
        }
        // Orders Pythia follows on the route, and the venue's open orders it does not.
        let followed: Vec<_> = self.inflight.values().filter(|f| f.demo && f.venue == Venue::Perps).collect();
        let pending: std::collections::HashSet<String> = followed.iter().map(|f| f.symbol.clone()).collect();
        let known_ids: std::collections::HashSet<String> = followed.iter().filter_map(|f| f.broker_id.clone()).collect();
        let known_cids: std::collections::HashSet<String> = followed.iter().map(|f| f.client_order_id.clone()).collect();
        let stray: Vec<&OpenOrder> = open
            .iter()
            .filter(|o| !known_ids.contains(&o.order.id))
            .filter(|o| o.order.client_order_id.as_ref().is_none_or(|c| !known_cids.contains(c)))
            .collect();
        let stray_symbols: std::collections::HashSet<String> = stray.iter().map(|o| o.symbol.clone()).collect();

        let mut symbols: Vec<String> = venue.keys().chain(holders.keys()).cloned().collect();
        symbols.sort();
        symbols.dedup();
        let mut checks = Vec::new();
        for sym in symbols {
            let (v, v_avg) = venue.get(&sym).copied().unwrap_or((0.0, 0.0));
            let hs = holders.get(&sym).cloned().unwrap_or_default();
            let mine: f64 = hs.iter().map(|h| h.1).sum();
            let market = self.markets.iter().find(|m| m.venue == Venue::Perps && m.symbol == sym).map(|m| m.id.clone());
            let price = market.as_deref().map(|m| self.price_of(m)).filter(|p| *p > 0.0).unwrap_or(v_avg);
            let step = market
                .as_deref()
                .and_then(|id| self.markets.iter().find(|m| m.id == id))
                .and_then(|m| self.perp_instrument_of(m))
                .map(|i| i.qty_step)
                .unwrap_or(0.0);
            let diff = mine - v;
            let tol = (step / 2.0).max(mine.abs().max(v.abs()) * 1e-9).max(1e-12);
            let (status, note) = if diff.abs() <= tol {
                (PerpCheckStatus::Ok, "equal".to_string())
            } else if pending.contains(&sym) {
                (PerpCheckStatus::Pending, "an order is in flight; its own report settles it".to_string())
            } else if stray_symbols.contains(&sym) {
                (PerpCheckStatus::StrayOrder, format!("{label} has an open order here that Pythia does not follow; nothing corrected while it can fill"))
            } else if hs.is_empty() {
                (PerpCheckStatus::Untracked, format!("{label} holds {v} here and no Pythia book does; reported, not adopted"))
            } else if v.abs() > 1e-12 && v.signum() != mine.signum() {
                (PerpCheckStatus::Mismatch, format!("the books are {} and {label} is {}; which side is right cannot be told, so nothing is changed",
                    if mine > 0.0 { "long" } else { "short" }, if v > 0.0 { "long" } else { "short" }))
            } else {
                // The venue wins: each holder takes its share of the venue's
                // position, in proportion to what it held, booked at the mark.
                let n = hs.len();
                let mkt = market.clone().unwrap_or_default();
                for (key, was) in &hs {
                    let Some(p) = self.positions.get_mut(key) else { continue };
                    let was_avg = p.avg_price;
                    let new = if mine.abs() < 1e-12 { 0.0 } else { v * was / mine };
                    let avg = if n == 1 && v_avg > 0.0 { v_avg } else { was_avg };
                    let book = p.book.clone();
                    if new.abs() < 1e-12 {
                        self.positions.remove(key);
                        self.ref_prices.remove(key);
                        self.perps.funding_cursor.remove(key);
                    } else {
                        p.qty = new;
                        p.avg_price = avg;
                        p.stop = 0.0;
                        p.target = 0.0;
                        p.trail_ref = avg;
                        self.ref_prices.remove(key);
                    }
                    self.autopilot_on_correction(&book, &mkt, (*was, was_avg), (new, avg), &format!("{label} demo"));
                }
                (PerpCheckStatus::Corrected, format!("set to {label}'s {v} (the books had {mine}); the venue wins"))
            };
            checks.push(PerpCheck { symbol: sym, market, pythia: mine, venue: v, diff, diff_usd: diff * price, status, note });
        }
        let mismatches = checks.iter().filter(|c| !c.status.settled()).count();
        for c in &checks {
            if c.status == PerpCheckStatus::Ok || c.status == PerpCheckStatus::Pending {
                self.perps.reconcile_noted.remove(&c.symbol);
                continue;
            }
            let said = format!("{:?}:{:.10}:{:.10}", c.status, c.pythia, c.venue);
            if self.perps.reconcile_noted.get(&c.symbol) == Some(&said) {
                continue;
            }
            self.perps.reconcile_noted.insert(c.symbol.clone(), said);
            let kind = if c.status == PerpCheckStatus::Corrected { JournalKind::Risk } else { JournalKind::System };
            self.log(
                kind,
                format!("Perps demo reconcile {}: {} (book {}, {label} {})", c.symbol, c.note, c.pythia, c.venue),
                None,
                c.market.clone(),
            );
        }
        self.perps.reconcile = Some(PerpReconcile {
            checked_at: now,
            symbols: checks,
            mismatches,
            open_orders: open.len(),
            stray_orders: stray.iter().map(|o| format!("{} {}", o.symbol, o.order.id)).collect(),
            error: None,
            failed_at: 0,
        });
        mismatches
    }

    // ── state and persistence ───────────────────────────────────────────────

    pub(super) fn perps_status(&self) -> Option<PerpsStatus> {
        let ex = self.perps.exchange?;
        let open: Vec<f64> = self
            .positions
            .values()
            .filter(|p| p.venue == Venue::Perps && p.qty.abs() > 1e-12)
            .map(|p| p.qty)
            .collect();
        Some(PerpsStatus {
            exchange: ex.id().to_string(),
            label: ex.label().to_string(),
            demo_ready: self.perp_demo_block().is_none(),
            demo_blocked: self.perp_demo_block(),
            listed: self.perps.instruments.len(),
            markets: self.markets.iter().filter(|m| m.venue == Venue::Perps).count(),
            tickers_at: self.perps.tickers_at,
            account: self.perps.account.clone(),
            account_at: self.perps.account_at,
            account_error: self.perps.account_error.clone(),
            funding_total: self.perps.funding_total,
            reconcile: self.perps.reconcile.clone(),
            longs: open.iter().filter(|q| **q > 0.0).count(),
            shorts: open.iter().filter(|q| **q < 0.0).count(),
            live: PERPS_LIVE_REFUSED.to_string(),
        })
    }

    pub(super) fn perps_saved(&self) -> PerpsSaved {
        PerpsSaved {
            exchange: self.perps.exchange,
            markets: self
                .markets
                .iter()
                .filter(|m| m.venue == Venue::Perps)
                .filter_map(|m| {
                    let coin = m.id.strip_prefix(PERP_PREFIX)?.to_string();
                    Some(PerpMarketSaved {
                        id: m.id.clone(),
                        instrument: self.perps.instruments.get(&coin).cloned(),
                        coin,
                        symbol: m.symbol.clone(),
                    })
                })
                .collect(),
            funding_cursor: self.perps.funding_cursor.iter().map(|(k, v)| (k.clone(), *v)).collect(),
            funding_paid: self.perps.funding_paid.iter().map(|(k, v)| (k.clone(), *v)).collect(),
            funding_total: self.perps.funding_total,
        }
    }

    /// Put the saved perps markets back before prices and positions are
    /// restored, so what a book holds has a market to be valued and closed in.
    pub(super) fn perps_restore(&mut self, saved: PerpsSaved) {
        if self.perps.exchange.is_none() {
            self.perps.exchange = saved.exchange;
        }
        for m in saved.markets {
            if let Some(i) = m.instrument.clone() {
                self.perps.instruments.entry(i.coin.clone()).or_insert(i);
            }
            if !self.markets.iter().any(|x| x.id == m.id) {
                self.markets.push(Market {
                    id: m.id,
                    venue: Venue::Perps,
                    symbol: m.symbol,
                    kind: MarketKind::Crypto,
                    price: 0.0,
                    change24h: 0.0,
                    model_prob: None,
                    liquidity: None,
                    regime: None,
                    trend_strength: None,
                    no_price: None,
                    resolves_at: None,
                    updated_at: 0,
                });
            }
        }
        self.perps.funding_cursor = saved.funding_cursor.into_iter().collect();
        self.perps.funding_paid = saved.funding_paid.into_iter().collect();
        self.perps.funding_total = saved.funding_total;
    }

    /// The demo order rows and journal lines a refused perps order leaves.
    #[allow(clippy::too_many_arguments)]
    pub(super) fn refuse_perp_order(&mut self, book: &str, sid: &str, m: &Market, side: Side, qty: f64, why: &str, demo: bool) {
        let mut order = self.build_order(sid, m, side, qty, OrderStatus::Rejected, Some(why.to_string()));
        if demo {
            order.route = FillRoute::Demo;
        }
        order.book = (!book.is_empty()).then(|| book.to_string());
        self.orders.insert(0, order);
        self.log(
            JournalKind::Reject,
            format!("{} {side:?} {} refused: {why}", if demo { "DEMO" } else { "Perps" }, m.symbol),
            Some(sid.to_string()),
            Some(m.id.clone()),
        );
    }

    /// Every perps position by book and key, for tests and the status.
    #[cfg(test)]
    pub(super) fn perp_positions(&self) -> Vec<(String, String, f64)> {
        let mut v: Vec<(String, String, f64)> = self
            .positions
            .iter()
            .filter(|(_, p)| p.venue == Venue::Perps)
            .map(|(k, p)| (super::split_key(k).0.to_string(), p.market.clone(), p.qty))
            .collect();
        v.sort_by(|a, b| a.0.cmp(&b.0).then(a.1.cmp(&b.1)));
        v
    }
}
