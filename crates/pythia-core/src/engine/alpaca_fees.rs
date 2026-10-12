//! Alpaca crypto fees, booked when Alpaca says what they were.
//!
//! Every other crypto venue reports an order's fee with the fill, and the
//! engine books it there (the coins actually received, the fee in dollars;
//! see `Engine::apply_live_update`). Alpaca does not. Its order object has no
//! fee field; the fee is "charged on the credited crypto asset/fiat (what you
//! receive)", so a buy of BTC/USD pays in BTC and a sell pays in dollars, and
//! it is "calculated and posted end of day" as an account activity of type
//! `CFEE` or `FEE`, without an order id
//! (<https://docs.alpaca.markets/docs/crypto-trading>, section "Crypto Spot
//! Trading Fees", and
//! <https://docs.alpaca.markets/reference/getaccountactivitiesbyactivitytype-1>,
//! both checked 2026-10-08). See [`CryptoFeeActivity`] for the shape.
//!
//! So an Alpaca crypto fill is booked as filled, with no fee, and watched
//! ([`AlpacaFeeWatch`]) until its fee is known. Two things can tell first:
//!
//! 1. **The venue's position.** The docs do not say whether the coins leave
//!    the position at the fill or with the end-of-day posting. When the
//!    venue shows fewer coins than the book, and the gap fits inside
//!    Alpaca's highest fee (tier 1 taker, 25 bps of the watched buys), the
//!    gap is that fee: the reconciler and a short exit book it as such
//!    instead of as an unexplained correction. Provisional (`taken`).
//! 2. **The fee activity.** The daemon reads `CFEE` and `FEE` activities
//!    (`Engine::alpaca_fee_queries`, `Engine::apply_alpaca_fees`). Each one
//!    is matched to the watched fills of its pair and side on its date and
//!    split across them by size. Coins already taken from the book are
//!    confirmed; any others leave the position now. The dollars go into the
//!    strategy's and the autopilot's fees, the tax record gets a fee line for
//!    the fill (`tax::RecordKind::Fee`), and the journal says what happened.
//!
//! Either way the end state is the one a venue that reports fees with the
//! fill produces: the book holds the coins received, the cash is what was
//! paid, and the fee is in the ledger in dollars at the fill price.
//!
//! **When no fee is ever posted.** It is not known whether the paper account
//! posts `CFEE` at all. A fill still waiting after [`WATCH_KEEP_MS`] gets its
//! fee from the published schedule instead ([`EstimatedFee`]): Alpaca's own
//! rate for the pair (`config/costs.json`, tier 1: 25 bps taker, 15 bps maker)
//! on the fill's notional, less whatever the venue's position already showed
//! taken. It is booked in dollars only, out of the cash and into the
//! strategy's and the autopilot's fees, and never moves the coins: the venue
//! did not take any, so the book keeps matching the venue's position. It is
//! marked estimated in the journal and in the Live page's list, and never
//! written to the tax record, which only holds what a venue reported.

use super::{Engine, InFlight, JournalKind, LiveUpdate, Market};
use crate::connectors::alpaca::{alpaca_crypto_pair, CryptoFeeActivity, CRYPTO_FEE_MAX_BPS};
use crate::connectors::{BrokerOrderStatus, Side, Venue};
use crate::costs::{self, CostVenue};
use crate::execution::bandit::ExecStyle;
use serde::{Deserialize, Serialize};

/// How often the daemon asks Alpaca for posted fees while any are awaited.
/// They post once a day, so twice an hour is plenty.
pub(super) const FEE_POLL_MS: i64 = 30 * 60_000;
/// How long a fill waits for its fee before Pythia stops asking.
pub(super) const WATCH_KEEP_MS: i64 = 7 * 86_400_000;
/// How long a booked activity id is remembered, against booking it twice.
const SEEN_KEEP_MS: i64 = 45 * 86_400_000;
/// Slack on top of the fee bound: the exit is sent rounded down to the
/// asset's quantity step (9 decimals at most, see `AlpacaConnector::submit_order`),
/// and that much may stay at the venue.
const GAP_SLACK: f64 = 1.5e-6;

/// An Alpaca crypto fill whose fee has not been posted yet.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AlpacaFeeWatch {
    /// The engine order id, the same as the fill's tax record.
    pub order_id: String,
    pub market_id: String,
    /// `BTC/USD`.
    pub symbol: String,
    pub side: Side,
    pub strategy_id: String,
    /// What filled, and at what average price: the fee is valued at it.
    pub qty: f64,
    pub price: f64,
    /// When it was booked (epoch ms).
    pub ts: i64,
    /// Which Alpaca account: the paper one (paper endpoint or demo route)
    /// or the live one.
    pub paper: bool,
    pub demo: bool,
    /// A real-money fill: its fee goes into the tax record.
    pub taxed: bool,
    /// Coins taken from the book because the venue showed them gone, not yet
    /// confirmed by a posted fee.
    #[serde(default)]
    pub taken: f64,
    /// Coins and dollars Alpaca has posted for this fill.
    #[serde(default)]
    pub posted_coins: f64,
    #[serde(default)]
    pub posted_usd: f64,
    /// Sent as a resting limit (maker rate) rather than crossing (taker).
    /// Only used for an estimate; older saves read as taker, the higher one.
    #[serde(default)]
    pub maker: bool,
}

/// A fee booked from Alpaca's published schedule because Alpaca posted none
/// within [`WATCH_KEEP_MS`]. Kept for the Live page; the newest 50.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EstimatedFee {
    pub order_id: String,
    pub market_id: String,
    pub symbol: String,
    pub side: Side,
    pub strategy_id: String,
    /// The fill's notional, and the rate applied, in bps.
    pub notional: f64,
    pub rate_bps: f64,
    /// Dollars booked now; what the venue's position had already shown
    /// taken (booked earlier) is not counted twice.
    pub usd: f64,
    /// When it was booked (epoch ms).
    pub ts: i64,
    /// The paper account (demo route or paper endpoint), or the live one.
    pub paper: bool,
}

/// How many estimates the Live page keeps.
const ESTIMATES_KEPT: usize = 50;

impl AlpacaFeeWatch {
    /// The paper account answers for both the paper endpoint and the demo route.
    fn paper_account(&self) -> bool {
        self.paper || self.demo
    }

    /// Coins this buy can still have paid as a fee that the book has not taken.
    fn room(&self) -> f64 {
        if self.side != Side::Buy {
            return 0.0;
        }
        (self.qty * CRYPTO_FEE_MAX_BPS / 10_000.0 * 1.01 - self.taken - self.posted_coins).max(0.0)
    }
}

/// One request the daemon should make: the fee activities of one Alpaca
/// account since `after` (RFC 3339).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AlpacaFeeQuery {
    pub paper: bool,
    pub after: String,
}

/// The date Alpaca would file a moment under. Its account dates are New York
/// dates; a fill one day either side is still taken when nothing matches.
pub(super) fn ny_date(ms: i64) -> String {
    chrono::DateTime::from_timestamp_millis(ms)
        .map(|d| d.with_timezone(&chrono_tz::America::New_York).format("%Y-%m-%d").to_string())
        .unwrap_or_default()
}

/// An order on Alpaca's crypto book: an Alpaca crypto market, or a crypto
/// demo order the Alpaca paper route took (its cost venue says so, and it is
/// kept with the order across a restart).
pub(super) fn alpaca_crypto_order(f: &InFlight) -> bool {
    let on_alpaca = f.venue == Venue::Alpaca || (f.demo && f.venue == Venue::Crypto && f.cost_venue == CostVenue::Alpaca);
    on_alpaca && f.symbol.contains('/')
}

fn day_gap(a: &str, b: &str) -> Option<i64> {
    let p = |s: &str| chrono::NaiveDate::parse_from_str(s, "%Y-%m-%d").ok();
    Some((p(a)? - p(b)?).num_days().abs())
}

impl Engine {
    /// Start (or update) the watch on an Alpaca crypto fill that came without
    /// a fee. Called after each booked part of a fill.
    pub(super) fn watch_alpaca_fee(&mut self, order_id: &str, f: &InFlight, m: &Market, update: &LiveUpdate) {
        let crypto = alpaca_crypto_order(f);
        let price = update.avg_price.unwrap_or(0.0);
        if !crypto || update.fee != 0.0 || update.fee_base != 0.0 || update.filled_qty <= 0.0 || price <= 0.0 {
            return;
        }
        let now = self.now();
        if let Some(w) = self.alpaca_fees.iter_mut().find(|w| w.order_id == order_id) {
            w.qty = update.filled_qty;
            w.price = price;
            return;
        }
        self.alpaca_fees.push(AlpacaFeeWatch {
            order_id: order_id.to_string(),
            market_id: m.id.clone(),
            // The pair as Alpaca files its fee activities under it.
            symbol: alpaca_crypto_pair(&m.symbol).unwrap_or_else(|| m.symbol.clone()),
            side: f.side,
            strategy_id: f.strategy_id.clone(),
            qty: update.filled_qty,
            price,
            ts: now,
            paper: f.paper,
            demo: f.demo,
            taxed: f.route() == super::FillRoute::Live,
            taken: 0.0,
            posted_coins: 0.0,
            posted_usd: 0.0,
            maker: f.style != ExecStyle::Cross,
        });
    }

    /// Coins the watched buys in this market, on this account and route, can
    /// still have paid as a fee.
    fn alpaca_fee_room(&self, market_id: &str, paper: bool, demo: bool) -> f64 {
        self.alpaca_fees
            .iter()
            .filter(|w| w.market_id == market_id && w.paper == paper && w.demo == demo)
            .map(AlpacaFeeWatch::room)
            .sum()
    }

    /// The venue shows `gap` fewer coins than the book in an Alpaca crypto
    /// market. When the watched buys' unposted fees can explain it, book it
    /// as those fees (provisionally, until Alpaca posts them) and return
    /// true. Otherwise leave it to the caller's ordinary correction.
    pub(super) fn take_alpaca_fee_gap(&mut self, market_id: &str, gap: f64, paper: bool, demo: bool, seen_by: &str) -> bool {
        let room = self.alpaca_fee_room(market_id, paper, demo);
        if gap.is_nan() || gap <= 0.0 || room <= 0.0 || gap > room + GAP_SLACK {
            return false;
        }
        let shares: Vec<(usize, f64)> = self
            .alpaca_fees
            .iter()
            .enumerate()
            .filter(|(_, w)| w.market_id == market_id && w.paper == paper && w.demo == demo && w.room() > 0.0)
            .map(|(i, w)| (i, gap * w.room() / room))
            .collect();
        let mut value = 0.0;
        let mut who = Vec::new();
        for (i, coins) in shares {
            self.alpaca_fees[i].taken += coins;
            let w = self.alpaca_fees[i].clone();
            value += coins * w.price;
            if let Some(ap) = self.charge_late_fee(&w, coins, coins * w.price, 0.0) {
                who.push(ap);
            }
        }
        let base = self.alpaca_fees.iter().find(|w| w.market_id == market_id).map(|w| w.symbol.clone()).unwrap_or_default();
        let base = base.split('/').next().unwrap_or("coin").to_string();
        let ap = if who.is_empty() { String::new() } else { format!(" ({})", who.join(", ")) };
        self.log(
            JournalKind::Fill,
            format!(
                "Alpaca kept {gap:.8} {base} of the {market_id} buy as its crypto fee ({seen_by}); booked as a fee of ${value:.4}{ap}. \
                 Confirmed when Alpaca posts the fee at the end of the day."
            ),
            None,
            Some(market_id.to_string()),
        );
        true
    }

    /// Book a fee against one watched fill: `coins` leave the position (or,
    /// if the book no longer holds them, their price leaves the cash),
    /// `usd` leaves the cash, and `value` (the whole fee in dollars) goes to
    /// the strategy's and the autopilot's fees. The cash is otherwise
    /// untouched: the fill already paid for the coins the fee took. Returns
    /// the autopilot's label when one paid it.
    fn charge_late_fee(&mut self, w: &AlpacaFeeWatch, coins: f64, value: f64, usd: f64) -> Option<String> {
        let idx = self
            .strategies
            .iter()
            .position(|s| s.id == w.strategy_id)
            .unwrap_or_else(|| self.ensure_manual_strategy());
        {
            let s = &mut self.strategies[idx];
            s.ledger.fees += value;
            s.ledger.pnl = s.ledger.breakdown(s.pnl);
        }
        let mut left = coins.max(0.0);
        if left > 0.0 {
            if let Some(p) = self.positions.get_mut(&w.market_id).filter(|p| p.qty > 0.0) {
                let take = left.min(p.qty);
                p.qty -= take;
                left -= take;
                if p.qty < 1e-9 {
                    self.positions.remove(&w.market_id);
                    self.ref_prices.remove(&w.market_id);
                }
            }
        }
        // Coins the book had already sold: the sale was booked for more than
        // the account had to sell, so the difference comes out of the cash.
        self.cash -= usd + left * w.price;
        let open_after = self.positions.contains_key(&w.market_id);
        self.autopilot_on_late_fee(&w.strategy_id, &w.market_id, value, open_after)
    }

    /// An Alpaca crypto exit that filled less than it was sent for, because
    /// the venue held less than the book (see `AlpacaConnector::submit_order`):
    /// the coins left over in the book are the buy's fee.
    pub(super) fn alpaca_exit_gap(&mut self, f: &InFlight, update: &LiveUpdate) {
        if !alpaca_crypto_order(f) || f.side != Side::Sell || update.status != BrokerOrderStatus::Filled {
            return;
        }
        let Some(left) = self.positions.get(&f.market_id).map(|p| p.qty).filter(|q| *q > 0.0) else { return };
        // The exit was meant to close the position: what it did not sell is
        // what is left.
        if f.qty - update.filled_qty + GAP_SLACK < left {
            return;
        }
        self.take_alpaca_fee_gap(&f.market_id, left, f.paper, f.demo, "the exit sold what the venue held");
    }

    /// The fee requests the daemon should make now: one per Alpaca account
    /// with fills waiting for their fee, at most every [`FEE_POLL_MS`].
    /// Fills that waited longer than [`WATCH_KEEP_MS`] stop being watched.
    pub fn alpaca_fee_queries(&mut self) -> Vec<AlpacaFeeQuery> {
        let now = self.now();
        let expired: Vec<AlpacaFeeWatch> = self.alpaca_fees.iter().filter(|w| now - w.ts > WATCH_KEEP_MS).cloned().collect();
        if !expired.is_empty() {
            self.alpaca_fees.retain(|w| now - w.ts <= WATCH_KEEP_MS);
            for w in expired.iter().filter(|w| w.posted_coins == 0.0 && w.posted_usd == 0.0) {
                self.estimate_alpaca_fee(w);
            }
        }
        self.alpaca_fee_seen.retain(|_, at| now - *at <= SEEN_KEEP_MS);
        if self.alpaca_fees.is_empty() || now - self.alpaca_fee_polled < FEE_POLL_MS {
            return Vec::new();
        }
        self.alpaca_fee_polled = now;
        let mut out: Vec<AlpacaFeeQuery> = Vec::new();
        for paper in [true, false] {
            let Some(first) = self.alpaca_fees.iter().filter(|w| w.paper_account() == paper).map(|w| w.ts).min() else { continue };
            // A day early: Alpaca dates by New York time and posts after the fill.
            let after = chrono::DateTime::from_timestamp_millis(first - 86_400_000)
                .map(|d| d.format("%Y-%m-%dT%H:%M:%SZ").to_string())
                .unwrap_or_default();
            out.push(AlpacaFeeQuery { paper, after });
        }
        out
    }

    /// Book the fee of a fill Alpaca never posted one for, from the published
    /// schedule, in dollars only (see the module docs). Journaled as estimated.
    fn estimate_alpaca_fee(&mut self, w: &AlpacaFeeWatch) {
        let model = costs::model_for(CostVenue::Alpaca, &w.symbol);
        let rate_bps = if w.maker { model.maker_bps } else { model.taker_bps };
        let notional = w.qty * w.price;
        let full = notional * rate_bps / 10_000.0;
        // Coins the venue's position already showed gone are in the ledger.
        let usd = (full - w.taken * w.price).max(0.0);
        let account = if w.paper_account() { "paper" } else { "live" };
        let ap = if usd > 0.0 { self.charge_late_fee(w, 0.0, usd, usd) } else { None };
        let who = ap.map(|a| format!(" ({a})")).unwrap_or_default();
        let tax = if w.taxed { " Not in the tax record, which holds only fees a venue reported." } else { "" };
        self.log(
            JournalKind::Fill,
            format!(
                "Alpaca posted no fee within 7 days for {} {:?} {} on the {account} account: booked an ESTIMATED fee of ${usd:.4} \
                 ({rate_bps:.0} bps {} on ${notional:.2}, Alpaca's published tier 1 rate) to {}{who}, in dollars only; the coins \
                 stay as the venue holds them.{tax}",
                w.symbol,
                w.side,
                w.order_id,
                if w.maker { "maker" } else { "taker" },
                w.strategy_id
            ),
            Some(w.strategy_id.clone()),
            Some(w.market_id.clone()),
        );
        self.alpaca_fee_estimates.push(EstimatedFee {
            order_id: w.order_id.clone(),
            market_id: w.market_id.clone(),
            symbol: w.symbol.clone(),
            side: w.side,
            strategy_id: w.strategy_id.clone(),
            notional,
            rate_bps,
            usd,
            ts: self.now(),
            paper: w.paper_account(),
        });
        let extra = self.alpaca_fee_estimates.len().saturating_sub(ESTIMATES_KEPT);
        self.alpaca_fee_estimates.drain(..extra);
    }

    /// The fees booked as estimates, newest last.
    pub fn alpaca_fee_estimates(&self) -> &[EstimatedFee] {
        &self.alpaca_fee_estimates
    }

    /// Book the crypto fees one Alpaca account posted (`paper`: the paper
    /// account). Each activity is booked once, however often it is read.
    pub fn apply_alpaca_fees(&mut self, paper: bool, activities: &[CryptoFeeActivity]) {
        let now = self.now();
        for a in activities {
            let key = if a.id.is_empty() { format!("{}|{}|{}|{}", a.date, a.symbol, a.coins, a.usd) } else { a.id.clone() };
            let key = format!("{}:{key}", if paper { "paper" } else { "live" });
            if self.alpaca_fee_seen.contains_key(&key) {
                continue;
            }
            self.alpaca_fee_seen.insert(key, now);
            self.book_alpaca_fee(paper, a);
        }
    }

    fn book_alpaca_fee(&mut self, paper: bool, a: &CryptoFeeActivity) {
        let base = a.symbol.split('/').next().unwrap_or("coin").to_string();
        let what = if a.coins != 0.0 { format!("{:.8} {base}", a.coins) } else { format!("${:.4}", a.usd) };
        if a.coins < 0.0 || a.usd < 0.0 {
            self.log(
                JournalKind::Risk,
                format!("Alpaca posted a negative crypto fee ({what} on {} {}, {}); not booked, check the account", a.symbol, a.date, a.id),
                None,
                None,
            );
            return;
        }
        // A fee in the coin is a buy's; one in dollars a sell's.
        let side = if a.coins > 0.0 { Side::Buy } else { Side::Sell };
        let pick = |within: i64| -> Vec<usize> {
            self.alpaca_fees
                .iter()
                .enumerate()
                .filter(|(_, w)| w.paper_account() == paper && w.symbol == a.symbol && w.side == side)
                .filter(|(_, w)| day_gap(&ny_date(w.ts), &a.date).is_some_and(|d| d <= within))
                .map(|(i, _)| i)
                .collect()
        };
        let mut idx = pick(0);
        if idx.is_empty() {
            idx = pick(1);
        }
        if idx.is_empty() {
            self.log(
                JournalKind::Risk,
                format!(
                    "Alpaca posted a crypto fee of {what} on {} {} that matches no fill Pythia is waiting on (a trade made outside Pythia, or one older than a week); not booked",
                    a.symbol, a.date
                ),
                None,
                None,
            );
            return;
        }
        // Split by size: coins by quantity, dollars by notional.
        let weight = |w: &AlpacaFeeWatch| if side == Side::Buy { w.qty } else { w.qty * w.price };
        let total: f64 = idx.iter().map(|&i| weight(&self.alpaca_fees[i])).sum();
        let mut value = 0.0;
        let mut from_book = 0.0;
        let mut who: Vec<String> = Vec::new();
        for &i in &idx {
            let part = if total > 0.0 { weight(&self.alpaca_fees[i]) / total } else { 1.0 / idx.len() as f64 };
            let (coins, usd) = (a.coins * part, a.usd * part);
            let w = {
                let w = &mut self.alpaca_fees[i];
                let confirmed = w.taken.min(coins);
                w.taken -= confirmed;
                w.posted_coins += coins;
                w.posted_usd += usd;
                (w.clone(), coins - confirmed)
            };
            let (w, extra) = w;
            let fee_value = coins * w.price + usd;
            value += fee_value;
            from_book += extra;
            // What was taken from the book earlier is in the ledger already.
            if let Some(ap) = self.charge_late_fee(&w, extra, extra * w.price + usd, usd) {
                if !who.contains(&ap) {
                    who.push(ap);
                }
            }
            if !who.contains(&w.strategy_id) {
                who.push(w.strategy_id.clone());
            }
            if w.taxed {
                self.fill_records.push(crate::tax::FillRecord {
                    ts: self.now(),
                    venue: Venue::Alpaca,
                    market_id: w.market_id.clone(),
                    symbol: w.symbol.clone(),
                    side: w.side,
                    qty: coins,
                    price: w.price,
                    fee: fee_value,
                    strategy_id: w.strategy_id.clone(),
                    order_id: w.order_id.clone(),
                    kind: crate::tax::RecordKind::Fee,
                });
            }
        }
        let market_id = self.alpaca_fees[idx[0]].market_id.clone();
        let book = if from_book > 0.0 {
            format!(", {from_book:.8} {base} taken from the position now")
        } else if a.coins > 0.0 {
            ", the position already showed it".to_string()
        } else {
            String::new()
        };
        self.log(
            JournalKind::Fill,
            format!(
                "Alpaca {} {}: crypto fee of {what} on {} {:?} fill(s), ${value:.4} at the fill price, booked to {}{book}",
                a.activity_type,
                a.date,
                a.symbol,
                side,
                who.join(", ")
            ),
            self.alpaca_fees.get(idx[0]).map(|w| w.strategy_id.clone()),
            Some(market_id),
        );
    }
}
