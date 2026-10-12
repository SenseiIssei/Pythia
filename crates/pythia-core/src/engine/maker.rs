//! Maker-first execution on a maker route.
//!
//! Alpaca charges crypto 0.25 % taker and 0.15 % maker per side, so on the
//! Alpaca crypto demo route every rebalance that rests instead of crossing
//! saves 10 bps of fee and the half spread. An order on a maker route is
//! worked as a short sequence of venue orders ("children"):
//!
//! 1. **Rest.** A limit at the best bid (buy) or best ask (sell) of the
//!    engine's live book for the coin, GTC.
//! 2. **Re-price.** A resting limit that has not filled after `rest_sec` is
//!    cancelled and placed again at the current touch, up to `max_tries`
//!    resting limits in all.
//! 3. **Fallback.** Then the rest goes out as a marketable limit, IOC, at
//!    most `fallback_band_bps` past the touch (or the last price), and
//!    whatever an IOC leaves goes out as a market order. A refused limit
//!    goes straight to the market order. So an order is done within about
//!    `rest_sec * max_tries` plus two order timeouts.
//!
//! Partial fills carry over: each child is for what is still open, and the
//! engine books every child's fill as part of the one order (`InFlight`'s
//! booked totals span all children). Alpaca has no post-only flag, so a fill
//! is counted as **maker** when a resting child filled at its own limit
//! price, and as **taker** when it filled better than the limit (the limit
//! was marketable when it arrived) or came from the fallback.
//!
//! Orders never outlive the process unseen: every child is saved with the
//! order, a child that was queued but not acknowledged is looked up by its
//! client id after a restart, and at startup the venue's open orders are
//! checked against the books; one Pythia sent that no order here knows of is
//! cancelled ([`Engine::apply_open_orders`]). An autopilot that stops, and an
//! exit that must not wait, make a resting maker order stand down.
//!
//! Which routes work this way is a per-route setting
//! ([`Engine::set_maker_route`]), on by default only for the Alpaca crypto
//! demo route. Every other route is unchanged.

use super::*;
use crate::connectors::alpaca::round_crypto_price;
use crate::connectors::OpenOrder;
use std::collections::BTreeMap;

/// The route key of crypto demo orders on the Alpaca paper account.
pub const ALPACA_CRYPTO_DEMO: &str = "demo:alpaca:crypto";

/// A fill within this many bps of the limit counts as at the limit: the
/// limit is rounded to six significant digits, which is never more than
/// 0.1 bps away from the number the engine compares.
const AT_LIMIT_BPS: f64 = 0.5;

/// How maker execution works on one route.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MakerSettings {
    pub enabled: bool,
    /// How long one resting limit waits for a fill before it is re-priced.
    pub rest_sec: u64,
    /// Resting limits in all, the first one included, before the fallback.
    pub max_tries: u32,
    /// How far past the touch the marketable fallback may pay.
    pub fallback_band_bps: f64,
}

impl Default for MakerSettings {
    fn default() -> Self {
        MakerSettings { enabled: false, rest_sec: 20, max_tries: 3, fallback_band_bps: 50.0 }
    }
}

impl MakerSettings {
    pub fn validate(&self) -> Result<(), String> {
        if !(5..=600).contains(&self.rest_sec) {
            return Err("restSec must be between 5 and 600 seconds".into());
        }
        if !(1..=10).contains(&self.max_tries) {
            return Err("maxTries must be between 1 and 10".into());
        }
        if !(self.fallback_band_bps.is_finite() && (1.0..=500.0).contains(&self.fallback_band_bps)) {
            return Err("fallbackBandBps must be between 1 and 500".into());
        }
        Ok(())
    }
}

/// The routes that rest by default: the Alpaca crypto demo route.
pub fn default_maker_routes() -> BTreeMap<String, MakerSettings> {
    BTreeMap::from([(ALPACA_CRYPTO_DEMO.to_string(), MakerSettings { enabled: true, ..MakerSettings::default() })])
}

/// Routes the daemon can work this way: it needs IOC limits and a listing of
/// open orders at the venue, which only the Alpaca connector has so far.
pub fn route_supported(key: &str) -> bool {
    key == ALPACA_CRYPTO_DEMO
}

/// What the current venue order of a maker order is.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Child {
    /// A GTC limit resting at the touch.
    Rest,
    /// The fallback: an IOC limit a band past the touch.
    Marketable,
    /// The last resort: a market order for whatever is left.
    Market,
}

/// A maker order's progress, saved with the order.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MakerWork {
    pub settings: MakerSettings,
    pub child: Child,
    /// Resting limits placed so far, the current one included.
    pub tries: u32,
    /// Children sent after the first; the client id of the next ends in it.
    pub seq: u32,
    /// The current child's limit; 0 for a market order.
    pub limit: f64,
    /// When the current child was placed (acknowledged).
    pub child_at: i64,
    /// What the finished children filled, and their notional.
    pub prior_qty: f64,
    pub prior_notional: f64,
    /// Fees booked up to the current child.
    pub prior_fee: f64,
    pub prior_fee_base: f64,
    /// What the current child has filled so far, as last booked.
    pub child_qty: f64,
    pub child_notional: f64,
    /// Filled resting at our own limit (maker) and by crossing (taker).
    pub maker_qty: f64,
    pub maker_notional: f64,
    pub taker_qty: f64,
    pub taker_notional: f64,
    /// The route's fee rates, from `config/costs.json`, in bps.
    pub maker_bps: f64,
    pub taker_bps: f64,
    /// The order closes or reduces a position.
    pub reduce_only: bool,
    /// The client id the order started under; later children add `-m{seq}`.
    pub base_client_id: String,
    /// Set when the order has to stand down (its autopilot stopped, an exit
    /// needs the market): the current child is cancelled and nothing new is
    /// placed.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub stop: Option<String>,
}

impl MakerWork {
    /// Whether the current child should be cancelled now.
    pub(super) fn cancel_due(&self, now: i64, age_ms: i64, timeout_ms: i64) -> bool {
        if self.stop.is_some() {
            return true;
        }
        match self.child {
            Child::Rest => now - self.child_at > self.settings.rest_sec as i64 * 1000,
            Child::Marketable | Child::Market => age_ms > timeout_ms,
        }
    }

    fn describe(&self) -> String {
        match self.child {
            Child::Rest => format!("resting limit {} of {} at {}", self.tries, self.settings.max_tries, self.limit),
            Child::Marketable => format!("marketable limit IOC at {}", self.limit),
            Child::Market => "market order".into(),
        }
    }
}

/// `px` is at our limit, not better: a buy filled at or above it, a sell at
/// or below it (within [`AT_LIMIT_BPS`]).
fn at_limit(px: f64, limit: f64, side: Side) -> bool {
    if limit <= 0.0 || px <= 0.0 {
        return false;
    }
    let better_bps = match side {
        Side::Buy => (limit - px) / limit * 10_000.0,
        Side::Sell => (px - limit) / limit * 10_000.0,
    };
    better_bps <= AT_LIMIT_BPS
}

impl Engine {
    /// Maker execution per route, by route key.
    pub fn maker_routes(&self) -> &BTreeMap<String, MakerSettings> {
        &self.maker_routes
    }

    /// Change how one route works orders. Orders already working keep the
    /// settings they started with.
    pub fn set_maker_route(&mut self, key: &str, settings: MakerSettings) -> Result<(), String> {
        if !route_supported(key) {
            return Err(format!(
                "maker execution is only built for the Alpaca crypto demo route ({ALPACA_CRYPTO_DEMO}); \
                 \"{key}\" keeps its market orders"
            ));
        }
        settings.validate()?;
        if self.maker_routes.get(key) == Some(&settings) {
            return Ok(());
        }
        self.maker_routes.insert(key.to_string(), settings);
        let msg = if settings.enabled {
            format!(
                "Maker execution on {key}: rest at the touch {}s per try, {} tries, then a marketable limit up to {} bps past the touch",
                settings.rest_sec, settings.max_tries, settings.fallback_band_bps
            )
        } else {
            format!("Maker execution on {key} is off: its orders go out as market orders")
        };
        self.log(JournalKind::System, msg, None, None);
        Ok(())
    }

    /// The route key of a demo order on `m`: `demo:{cost venue}:{kind}`.
    pub fn maker_route_key(&self, m: &Market) -> String {
        let kind = match m.venue {
            Venue::Crypto => "crypto",
            Venue::Alpaca if m.symbol.contains('/') => "crypto",
            Venue::Alpaca => "equity",
            Venue::Polymarket => "prediction",
        };
        format!("demo:{}:{kind}", self.demo_cost_venue(m).id())
    }

    /// The best price on `side`'s own side of a fresh book: the best bid for
    /// a buy, the best ask for a sell. `None` without a fresh book.
    fn maker_touch(&self, m: &Market, side: Side) -> Option<f64> {
        let b = self.books.get(&m.id).filter(|b| b.is_fresh(self.now()))?;
        let level = match side {
            Side::Buy => b.bids.levels().first(),
            Side::Sell => b.asks.levels().first(),
        };
        let half = b.mid * b.half_spread_bps / 10_000.0;
        let px = level.map(|l| l.0).unwrap_or(match side {
            Side::Buy => b.mid - half,
            Side::Sell => b.mid + half,
        });
        (px.is_finite() && px > 0.0).then_some(px)
    }

    /// A new demo order on `m` as a maker order, or `None` to send it as
    /// before: not a crypto order, an exit that must not wait, the route is
    /// off, or there is no fresh book to price the limit from.
    pub(super) fn maker_plan(&self, m: &Market, side: Side) -> Option<MakerWork> {
        if self.urgent_exit || m.venue != Venue::Crypto {
            return None;
        }
        let key = self.maker_route_key(m);
        if !route_supported(&key) {
            return None;
        }
        let settings = *self.maker_routes.get(&key).filter(|s| s.enabled)?;
        let limit = round_crypto_price(self.maker_touch(m, side)?, side == Side::Sell);
        if limit <= 0.0 {
            return None;
        }
        let cost = costs::model_for(self.demo_cost_venue(m), &m.symbol);
        Some(MakerWork {
            settings,
            child: Child::Rest,
            tries: 1,
            seq: 0,
            limit,
            child_at: self.now(),
            prior_qty: 0.0,
            prior_notional: 0.0,
            prior_fee: 0.0,
            prior_fee_base: 0.0,
            child_qty: 0.0,
            child_notional: 0.0,
            maker_qty: 0.0,
            maker_notional: 0.0,
            taker_qty: 0.0,
            taker_notional: 0.0,
            maker_bps: cost.maker_bps,
            taker_bps: cost.taker_bps,
            reduce_only: false,
            base_client_id: String::new(),
            stop: None,
        })
    }

    /// The venue's report on a maker order's current child. Books what is
    /// new, counts it as maker or taker, and either finishes the order or
    /// places the next child.
    pub(super) fn apply_maker_update(&mut self, order_id: &str, update: LiveUpdate) {
        let Some(f) = self.inflight.get(order_id).cloned() else { return };
        let Some(mut w) = f.maker.clone() else { return };
        let mut status = update.status;
        // Alpaca reports a cancel it is still working through as
        // `pending_cancel`; the child can still fill until it is final.
        if update.raw_status == "pending_cancel" {
            status = if update.filled_qty > 0.0 { BrokerOrderStatus::PartiallyFilled } else { BrokerOrderStatus::Working };
        }

        let child_px = update.avg_price.filter(|p| *p > 0.0);
        let dq = update.filled_qty - w.child_qty;
        let mut fill_note = None;
        if dq > 1e-12 {
            if let Some(avg) = child_px {
                let notional = avg * update.filled_qty;
                let dn = (notional - w.child_notional).max(0.0);
                let px = dn / dq;
                let maker = w.child == Child::Rest && at_limit(px, w.limit, f.side);
                if maker {
                    w.maker_qty += dq;
                    w.maker_notional += dn;
                } else {
                    w.taker_qty += dq;
                    w.taker_notional += dn;
                }
                w.child_qty = update.filled_qty;
                w.child_notional = notional;
                fill_note = Some((maker, dq, px));
            }
        }

        let total = w.prior_qty + w.child_qty;
        let notional = w.prior_notional + w.child_notional;
        let child_done = status.is_terminal();
        let all_filled = status == BrokerOrderStatus::Filled || f.qty - total <= f.qty * 1e-6;
        let next = child_done && !all_filled && w.stop.is_none() && w.child != Child::Market;
        let parent_status = if child_done && !next {
            match status {
                _ if all_filled => BrokerOrderStatus::Filled,
                // A refusal after earlier children filled is a partial fill.
                BrokerOrderStatus::Rejected if total > 0.0 => BrokerOrderStatus::Canceled,
                s => s,
            }
        } else if total > 0.0 {
            BrokerOrderStatus::PartiallyFilled
        } else {
            BrokerOrderStatus::Working
        };
        let view = LiveUpdate {
            status: parent_status,
            filled_qty: total,
            avg_price: (total > 0.0).then(|| notional / total),
            fee: w.prior_fee + update.fee,
            fee_base: w.prior_fee_base + update.fee_base,
            fee_unpriced: update.fee_unpriced.clone(),
            raw_status: update.raw_status.clone(),
        };
        if let Some(g) = self.inflight.get_mut(order_id) {
            g.maker = Some(w.clone());
        }
        if let Some((maker, q, px)) = fill_note {
            let how = if maker {
                format!("as maker, resting at our limit {}", w.limit)
            } else if w.child == Child::Rest {
                format!("as taker at {px:.6}: the limit {} was marketable when it arrived", w.limit)
            } else {
                format!("as taker at {px:.6} ({})", w.describe())
            };
            self.log(
                JournalKind::Fill,
                format!("{} {:?} {q:.6} {} filled {how}", Self::route_word(&f), f.side, f.symbol),
                Some(f.strategy_id.clone()),
                Some(f.market_id.clone()),
            );
        }
        self.apply_order_update(order_id, view.clone());
        if parent_status.is_terminal() {
            self.maker_record_costs(order_id, &f, &w, &view);
        } else if next {
            let why = match status {
                BrokerOrderStatus::Canceled if w.child == Child::Rest => {
                    format!("the limit at {} did not fill in {}s", w.limit, w.settings.rest_sec)
                }
                _ => format!("the {} ended {}", w.describe(), update.raw_status),
            };
            self.maker_next_child(order_id, &why, false);
        }
    }

    fn route_word(f: &InFlight) -> &'static str {
        if f.demo {
            "DEMO"
        } else {
            "LIVE"
        }
    }

    /// Place the next child of a maker order for what is still open: another
    /// resting limit at the current touch while tries are left, then the
    /// marketable IOC limit, then a market order. `market` skips straight to
    /// the market order (a limit the venue refused).
    fn maker_next_child(&mut self, order_id: &str, why: &str, market: bool) {
        let Some(f) = self.inflight.get(order_id).cloned() else { return };
        let Some(mut w) = f.maker.clone() else { return };
        let Some(m) = self.markets.iter().find(|m| m.id == f.market_id).cloned() else { return };
        w.prior_qty += w.child_qty;
        w.prior_notional += w.child_notional;
        w.prior_fee = f.booked_fee;
        w.prior_fee_base = f.booked_fee_base;
        w.child_qty = 0.0;
        w.child_notional = 0.0;
        let remaining = f.qty - w.prior_qty;
        let touch = self.maker_touch(&m, f.side);
        let (child, limit) = match (w.child, touch) {
            _ if market => (Child::Market, 0.0),
            (Child::Rest, Some(t)) if w.tries < w.settings.max_tries => {
                (Child::Rest, round_crypto_price(t, f.side == Side::Sell))
            }
            (Child::Rest, _) => {
                // The far side of the book, never better than the last price.
                let far = self.maker_touch(&m, opposite(f.side));
                let band = w.settings.fallback_band_bps / 10_000.0;
                let px = match f.side {
                    Side::Buy => far.unwrap_or(m.price).max(m.price) * (1.0 + band),
                    Side::Sell => far.unwrap_or(m.price).min(m.price) * (1.0 - band),
                };
                (Child::Marketable, round_crypto_price(px, f.side == Side::Buy))
            }
            _ => (Child::Market, 0.0),
        };
        if child == Child::Rest {
            w.tries += 1;
        }
        w.seq += 1;
        w.child = child;
        w.limit = limit;
        let now = self.now();
        w.child_at = now;
        let cid = format!("{}-m{}", w.base_client_id, w.seq);
        let what = w.describe();
        if let Some(ord) = self.orders.iter_mut().find(|o| o.id == order_id) {
            ord.order_type = if child == Child::Market { OrderType::Market } else { OrderType::Limit };
            ord.limit_price = (child != Child::Market).then_some(limit);
        }
        if let Some(g) = self.inflight.get_mut(order_id) {
            g.broker_id = None;
            g.client_order_id = cid.clone();
            g.cancel_sent = false;
            g.lookup = false;
            g.submitted_at = now;
            g.maker = Some(w.clone());
        }
        self.pending_live.push(LiveOrderOut {
            order_id: order_id.to_string(),
            client_order_id: cid,
            venue: f.venue,
            market_id: f.market_id.clone(),
            symbol: f.symbol.clone(),
            side: f.side,
            qty: remaining,
            ref_price: m.price,
            strategy_id: f.strategy_id.clone(),
            reduce_only: w.reduce_only,
            style: if child == Child::Market { bandit::ExecStyle::Cross } else { bandit::ExecStyle::Join },
            patience_bps: 0.0,
            paper: f.paper,
            dry_run: false,
            extended_hours: false,
            demo: f.demo,
            limit_price: (child != Child::Market).then_some(limit),
            ioc: child == Child::Marketable,
        });
        self.log(
            JournalKind::Order,
            format!("{} {:?} {} {why}: {remaining:.6} more as a {what}", Self::route_word(&f), f.side, f.symbol),
            Some(f.strategy_id.clone()),
            Some(f.market_id.clone()),
        );
    }

    /// Finish a maker order with what its finished children filled, the
    /// current child having filled nothing.
    fn maker_finish_with_prior(&mut self, order_id: &str, reason: &str) {
        let Some(f) = self.inflight.get(order_id).cloned() else { return };
        let Some(mut w) = f.maker.clone() else { return };
        w.prior_qty += w.child_qty;
        w.prior_notional += w.child_notional;
        w.child_qty = 0.0;
        w.child_notional = 0.0;
        if let Some(g) = self.inflight.get_mut(order_id) {
            g.maker = Some(w.clone());
        }
        let view = LiveUpdate {
            status: BrokerOrderStatus::Canceled,
            filled_qty: w.prior_qty,
            avg_price: (w.prior_qty > 0.0).then(|| w.prior_notional / w.prior_qty),
            fee: f.booked_fee,
            fee_base: f.booked_fee_base,
            fee_unpriced: Vec::new(),
            raw_status: reason.to_string(),
        };
        self.log(
            JournalKind::Order,
            format!(
                "{} {:?} {}: maker order ends with {:.6} of {:.6} filled ({reason})",
                Self::route_word(&f),
                f.side,
                f.symbol,
                w.prior_qty,
                f.qty
            ),
            Some(f.strategy_id.clone()),
            Some(f.market_id.clone()),
        );
        self.apply_order_update(order_id, view.clone());
        self.maker_record_costs(order_id, &f, &w, &view);
    }

    /// The daemon could not send a maker order's child. A refused limit is
    /// followed by a market order for the rest; a refused market order, or
    /// one after a stand-down, ends the order with what filled. Returns
    /// false when the caller should treat it as an ordinary refusal (nothing
    /// filled and nothing left to try).
    pub(super) fn maker_child_refused(&mut self, order_id: &str, reason: &str) -> bool {
        let Some(w) = self.inflight.get(order_id).and_then(|f| f.maker.clone()) else { return false };
        if w.child != Child::Market && w.stop.is_none() {
            self.maker_next_child(order_id, &format!("the {} was refused ({reason})", w.describe()), true);
            return true;
        }
        if w.prior_qty + w.child_qty > 0.0 {
            self.maker_finish_with_prior(order_id, &format!("the rest was refused: {reason}"));
            return true;
        }
        false
    }

    /// After a restart the venue has no order under the current child's
    /// client id: it was queued but never sent. The order carries on with
    /// the next child.
    pub(super) fn maker_child_missing(&mut self, order_id: &str) -> bool {
        let Some(w) = self.inflight.get(order_id).and_then(|f| f.maker.clone()) else { return false };
        if w.stop.is_some() {
            self.maker_finish_with_prior(order_id, "stood down before its next order was sent");
            return true;
        }
        self.maker_next_child(order_id, "the order queued before the restart never reached the venue", false);
        true
    }

    /// After a restart the current child could not be looked up. With
    /// earlier fills, the order ends with those (the open-order check at
    /// startup cancels the child if it is resting unseen); without, the
    /// caller closes it as unknown.
    pub(super) fn maker_child_lost(&mut self, order_id: &str, why: &str) -> bool {
        let Some(f) = self.inflight.get(order_id).cloned() else { return false };
        let Some(w) = f.maker.as_ref() else { return false };
        if w.prior_qty + w.child_qty <= 0.0 {
            return false;
        }
        let reason = format!("its order with client id {} could not be looked up after the restart ({why})", f.client_order_id);
        self.maker_finish_with_prior(order_id, &reason);
        true
    }

    /// Make the maker order working in `market_id`, if any, stand down.
    pub(super) fn maker_stand_down(&mut self, market_id: &str, why: &str) {
        let ids: Vec<String> = self
            .inflight
            .iter()
            .filter(|(_, f)| f.market_id == market_id && f.maker.as_ref().is_some_and(|w| w.stop.is_none()))
            .map(|(id, _)| id.clone())
            .collect();
        for id in ids {
            self.maker_stand_down_order(&id, why);
        }
    }

    /// Make every maker order of these strategies stand down.
    pub(super) fn maker_stand_down_for(&mut self, strategies: &HashSet<String>, why: &str) {
        let ids: Vec<String> = self
            .inflight
            .iter()
            .filter(|(_, f)| strategies.contains(&f.strategy_id) && f.maker.as_ref().is_some_and(|w| w.stop.is_none()))
            .map(|(id, _)| id.clone())
            .collect();
        for id in ids {
            self.maker_stand_down_order(&id, why);
        }
    }

    /// Cancel at the venue (the next poll does it) and place nothing new. A
    /// child still queued here, never handed to the daemon, is dropped and
    /// the order ends now. One the daemon has taken but the venue has not
    /// acknowledged yet is cancelled once its acknowledgement arrives.
    fn maker_stand_down_order(&mut self, order_id: &str, why: &str) {
        let Some(f) = self.inflight.get_mut(order_id) else { return };
        let Some(w) = f.maker.as_mut() else { return };
        w.stop = Some(why.to_string());
        let (sid, market, symbol, demo) = (f.strategy_id.clone(), f.market_id.clone(), f.symbol.clone(), f.demo);
        let queued = f.broker_id.is_none() && !f.lookup && self.pending_live.iter().any(|o| o.order_id == order_id);
        self.log(
            JournalKind::Order,
            format!("{} {symbol}: the maker order stands down ({why}); its resting order is cancelled", if demo { "DEMO" } else { "LIVE" }),
            Some(sid),
            Some(market),
        );
        if queued {
            self.pending_live.retain(|o| o.order_id != order_id);
            self.maker_finish_with_prior(order_id, &format!("stood down: {why}"));
        }
    }

    /// Put the maker and taker split and the realised cost against the model
    /// on the order row, and journal it.
    fn maker_record_costs(&mut self, order_id: &str, f: &InFlight, w: &MakerWork, view: &LiveUpdate) {
        let filled = view.filled_qty;
        let notional = w.maker_notional + w.taker_notional;
        let fee_bps = if notional > 0.0 {
            (w.maker_notional * w.maker_bps + w.taker_notional * w.taker_bps) / notional
        } else {
            w.taker_bps
        };
        let slip = view.avg_price.and_then(|p| bandit::realised_cost_bps(f.side, f.arrival, p)).filter(|_| filled > 0.0);
        let realised = slip.map(|s| s + fee_bps);
        let modelled = f.modelled_bps + w.taker_bps;
        if let Some(ord) = self.orders.iter_mut().find(|o| o.id == order_id) {
            ord.maker_qty = Some(w.maker_qty);
            ord.taker_qty = Some(w.taker_qty);
            ord.realised_cost_bps = realised;
            ord.modelled_cost_bps = Some(modelled);
        }
        if filled <= 0.0 {
            return;
        }
        let maker_pct = if filled > 0.0 { w.maker_qty / filled * 100.0 } else { 0.0 };
        let cost = match realised {
            Some(r) => format!("cost {r:.1} bps (fee {fee_bps:.1}) against {modelled:.1} modelled for a market order"),
            None => format!("fee {fee_bps:.1} bps against {:.1} for a market order", w.taker_bps),
        };
        self.log(
            JournalKind::Fill,
            format!(
                "{} {:?} {} done: {maker_pct:.0}% maker ({:.6}), {:.6} taker; {cost}",
                Self::route_word(f),
                f.side,
                f.symbol,
                w.maker_qty,
                w.taker_qty
            ),
            Some(f.strategy_id.clone()),
            Some(f.market_id.clone()),
        );
    }

    // ── open orders left from an earlier run ───────────────────────────────

    /// The daemon should list the maker venue's open orders: not yet done
    /// since this process started, and not tried in the last minute.
    pub fn open_orders_check_due(&self) -> bool {
        !self.open_orders_checked && self.now() - self.open_orders_tried_at >= 60_000
    }

    /// No venue to check (no maker route has keys): nothing can be resting.
    pub fn open_orders_check_skipped(&mut self) {
        self.open_orders_checked = true;
    }

    /// The listing failed; it is tried again in a minute.
    pub fn open_orders_check_failed(&mut self, why: &str) {
        let first = self.open_orders_tried_at == 0;
        self.open_orders_tried_at = self.now();
        if first {
            self.log(
                JournalKind::Risk,
                format!("Open orders at the demo venue could not be listed ({why}); trying again every minute"),
                None,
                None,
            );
        }
    }

    /// Check the venue's open orders against the books. An order Pythia sent
    /// (its client id starts with `pythia-`) that an order here is waiting
    /// for is adopted; one nothing here knows of is an orphan from an
    /// earlier run, returned for the daemon to cancel. Orders not sent by
    /// Pythia are never touched.
    pub fn apply_open_orders(&mut self, open: &[OpenOrder]) -> Vec<OpenOrder> {
        self.open_orders_tried_at = self.now();
        let mut orphans = Vec::new();
        for o in open {
            let Some(cid) = o.order.client_order_id.as_deref().filter(|c| c.starts_with("pythia-")) else { continue };
            if self.inflight.values().any(|f| f.broker_id.as_deref() == Some(o.order.id.as_str())) {
                continue;
            }
            let waiting = self
                .inflight
                .iter()
                .find(|(_, f)| f.broker_id.is_none() && f.client_order_id == cid)
                .map(|(id, _)| id.clone());
            match waiting {
                Some(id) => self.apply_lookup_found(&id, o.order.clone()),
                None => orphans.push(o.clone()),
            }
        }
        if orphans.is_empty() {
            self.open_orders_checked = true;
        }
        orphans
    }

    /// The orphans' cancels: journaled one by one. The check is done when
    /// every one was cancelled; otherwise it runs again in a minute.
    pub fn apply_orphans_cancelled(&mut self, cancelled: &[OpenOrder], failed: &[(OpenOrder, String)]) {
        for o in cancelled {
            self.log(
                JournalKind::Risk,
                format!(
                    "Cancelled an open {} order left from an earlier run (client id {}, {} filled): no order here was \
                     following it. A fill of it is not in Pythia's books",
                    o.symbol,
                    o.order.client_order_id.as_deref().unwrap_or("?"),
                    o.order.filled_qty
                ),
                None,
                None,
            );
        }
        for (o, why) in failed {
            self.log(
                JournalKind::Risk,
                format!(
                    "An open {} order left from an earlier run (client id {}) could not be cancelled ({why}); trying again in a minute",
                    o.symbol,
                    o.order.client_order_id.as_deref().unwrap_or("?")
                ),
                None,
                None,
            );
        }
        if failed.is_empty() {
            self.open_orders_checked = true;
        }
    }

    /// Move an in-flight order's clocks back, as if `ms` had passed.
    #[cfg(test)]
    pub(crate) fn age_inflight_for_test(&mut self, order_id: &str, ms: i64) {
        if let Some(f) = self.inflight.get_mut(order_id) {
            f.submitted_at -= ms;
            if let Some(w) = f.maker.as_mut() {
                w.child_at -= ms;
            }
        }
    }

    /// The maker state of an in-flight order, for tests.
    #[cfg(test)]
    pub(crate) fn maker_work_for_test(&self, order_id: &str) -> Option<MakerWork> {
        self.inflight.get(order_id).and_then(|f| f.maker.clone())
    }
}

fn opposite(side: Side) -> Side {
    match side {
        Side::Buy => Side::Sell,
        Side::Sell => Side::Buy,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_fill_counts_as_maker_only_at_our_limit() {
        assert!(at_limit(60_000.0, 60_000.0, Side::Buy));
        assert!(at_limit(60_001.0, 60_000.0, Side::Buy), "a buy cannot fill above its limit; rounding only");
        assert!(!at_limit(59_990.0, 60_000.0, Side::Buy), "better than the limit: it crossed");
        assert!(at_limit(60_000.0, 60_000.0, Side::Sell));
        assert!(!at_limit(60_010.0, 60_000.0, Side::Sell));
        assert!(!at_limit(0.0, 60_000.0, Side::Sell));
    }

    #[test]
    fn only_the_alpaca_crypto_demo_route_rests_by_default() {
        let routes = default_maker_routes();
        assert_eq!(routes.len(), 1);
        assert!(routes[ALPACA_CRYPTO_DEMO].enabled);
        assert!(routes[ALPACA_CRYPTO_DEMO].validate().is_ok());
        assert!(!route_supported("demo:bybit:crypto"));
        let bad = MakerSettings { rest_sec: 1, ..MakerSettings::default() };
        assert!(bad.validate().is_err());
    }
}
