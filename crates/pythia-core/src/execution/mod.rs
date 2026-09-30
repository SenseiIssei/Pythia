//! The live-execution daemon: the only place in Pythia that sends an order.
//!
//! Both hosts (the Tauri desktop shell and the standalone server) run the same
//! cycle, so a bug fixed here is fixed in both. They differ only in where the
//! credentials come from — the OS keychain or the process environment — which
//! they hand over as a [`Credentials`].
//!
//! ## The cycle
//!
//! ```text
//!   submit_pending  →  engine.drain_live_orders()  →  preflight → submit → ack
//!   poll_inflight   →  engine.live_polls()         →  status (→ cancel if overdue)
//!   reconcile       →  venue positions             →  engine.reconcile_positions()
//! ```
//!
//! Two rules hold throughout:
//!
//! 1. **The engine lock is never held across an `await`.** Every network call
//!    happens between locks, so the tick loop and the UI never block on a slow
//!    broker.
//! 2. **Nothing is booked that the venue did not confirm.** A failed submission
//!    is a rejection; an unanswered poll is retried, never assumed.

pub mod bandit;

use crate::connectors::cex::{CexConnector, Exchange};
use crate::connectors::{
    alpaca::AlpacaConnector, ConnectorError, MarketConnector, OrderRequest, OrderType, Venue,
};
use crate::engine::{Engine, LiveOrderOut, LiveUpdate};
use std::collections::HashSet;
use std::sync::Mutex;

/// Credentials for the venues this host can reach. Values are moved in once and
/// never logged; `Debug` is deliberately not derived.
#[derive(Clone, Default)]
pub struct Credentials {
    /// Alpaca PAPER-account key id + secret (paper-api.alpaca.markets).
    pub alpaca: Option<(String, String)>,
    /// Alpaca LIVE-account key id + secret (api.alpaca.markets). Alpaca issues
    /// a separate pair per account and each only authenticates against its own
    /// endpoint, so the order path never borrows the other account's keys.
    pub alpaca_live: Option<(String, String)>,
    /// The selected crypto exchange and its (key, secret, passphrase).
    pub exchange: Option<(Exchange, String, String, String)>,
    /// Cap on the marketable-limit band for Alpaca market orders, in basis
    /// points. `None` keeps the connector default; 0 sends plain market orders
    /// during regular hours.
    pub alpaca_slippage_bps: Option<f64>,
    /// Allow opening short equity positions (needs a margin account).
    pub alpaca_allow_shorts: bool,
}

impl Credentials {
    /// The Alpaca key pair for one endpoint, if configured.
    pub fn alpaca_keys(&self, paper: bool) -> Option<&(String, String)> {
        if paper {
            self.alpaca.as_ref()
        } else {
            self.alpaca_live.as_ref()
        }
    }

    /// The concrete Alpaca connector for one endpoint, using that endpoint's
    /// own keys. `extended_hours` is per order: the engine only sets it when
    /// the operator opted in AND the broker reported an extended session.
    pub fn alpaca_connector(&self, paper: bool, extended_hours: bool) -> Result<AlpacaConnector, String> {
        let (k, s) = self.alpaca_keys(paper).cloned().ok_or_else(|| {
            if paper {
                "Alpaca paper keys are not set (APCA_API_KEY_ID / APCA_API_SECRET_KEY, or Settings → Alpaca paper)"
                    .to_string()
            } else {
                "Alpaca live keys are not set (APCA_LIVE_API_KEY_ID / APCA_LIVE_API_SECRET_KEY, or Settings → \
                 Alpaca live). Paper and live accounts have separate key pairs."
                    .to_string()
            }
        })?;
        let mut c = AlpacaConnector::new(Some(k), Some(s), paper)
            .with_extended_hours(extended_hours)
            .with_shorts(self.alpaca_allow_shorts);
        if let Some(bps) = self.alpaca_slippage_bps {
            c = c.with_slippage_bps(bps);
        }
        if !c.is_live_ready() {
            return Err("Alpaca keys are present but empty".into());
        }
        Ok(c)
    }

    /// Build the connector for one venue, or explain why we cannot.
    pub fn connector(&self, venue: Venue, paper: bool) -> Result<Box<dyn MarketConnector>, String> {
        self.connector_with(venue, paper, false)
    }

    /// Same, for submitting one order that may target the extended session.
    pub fn connector_with(
        &self,
        venue: Venue,
        paper: bool,
        extended_hours: bool,
    ) -> Result<Box<dyn MarketConnector>, String> {
        match venue {
            Venue::Alpaca => Ok(Box::new(self.alpaca_connector(paper, extended_hours)?)),
            Venue::Crypto => {
                let (ex, k, s, p) = self
                    .exchange
                    .clone()
                    .ok_or("No crypto exchange is configured — add one in Settings → Exchanges")?;
                let c = CexConnector::new(ex, k, s, p);
                if !c.is_live_ready() {
                    return Err(format!("{} credentials are incomplete", ex.label()));
                }
                Ok(Box::new(c))
            }
            Venue::Polymarket => Err(
                "Polymarket order routing is not implemented — its odds are read-only (see SAFETY.md)".into(),
            ),
        }
    }

    /// Venues with usable credentials, for the "connected" badges.
    pub fn connected_venues(&self) -> HashSet<Venue> {
        let mut set = HashSet::new();
        // Either account counts: someone who configured only live keys still
        // needs the broker-status loop and the connected badge.
        if self.connector(Venue::Alpaca, true).is_ok() || self.connector(Venue::Alpaca, false).is_ok() {
            set.insert(Venue::Alpaca);
        }
        if self.connector(Venue::Crypto, true).is_ok() {
            set.insert(Venue::Crypto);
        }
        set
    }
}

/// One full execution pass. Call it once per tick, after `engine.tick()`.
pub async fn cycle(engine: &Mutex<Engine>, creds: &Credentials) {
    submit_pending(engine, creds).await;
    poll_inflight(engine, creds).await;
}

/// Read-only credential check, for the UI's "test connection" button and as the
/// gate before arming.
pub async fn verify(creds: &Credentials, venue: Venue, paper: bool) -> Result<String, String> {
    let conn = creds.connector(venue, paper)?;
    conn.verify().await.map_err(|e| e.to_string())
}

/// Submit everything the engine queued this tick.
pub async fn submit_pending(engine: &Mutex<Engine>, creds: &Credentials) {
    let orders = { engine.lock().unwrap().drain_live_orders() };
    for o in orders {
        submit_one(engine, creds, o).await;
    }
}

async fn submit_one(engine: &Mutex<Engine>, creds: &Credentials, o: LiveOrderOut) {
    if o.dry_run {
        return reject(engine, &o.order_id, "dry-run: not submitted");
    }

    let conn = match creds.connector_with(o.venue, o.paper, o.extended_hours) {
        Ok(c) => c,
        Err(e) => return reject(engine, &o.order_id, &e),
    };

    // Round to what the venue accepts *before* preflight, so the size we check
    // is the size we send.
    let qty = conn.round_qty(o.qty, &o.symbol);
    if qty <= 0.0 {
        return reject(
            engine,
            &o.order_id,
            &format!("{:.8} {} is below {}'s minimum order size", o.qty, o.symbol, conn.label()),
        );
    }

    // The execution policy picked a style when the order was created; this is
    // where it becomes a price. `Cross` stays a market order, exactly as before.
    let limit_price = o.style.limit_price(o.side, o.ref_price, o.patience_bps);
    let req = OrderRequest {
        symbol: o.symbol.clone(),
        side: o.side,
        order_type: if limit_price.is_some() { OrderType::Limit } else { OrderType::Market },
        qty,
        limit_price,
        ref_price: Some(o.ref_price),
        client_order_id: Some(o.client_order_id.clone()),
        reduce_only: o.reduce_only,
    };

    if let Err(e) = conn.preflight(&req).await {
        return reject(engine, &o.order_id, &e.to_string());
    }

    match conn.submit_order(req).await {
        Ok(bo) => {
            {
                let mut e = engine.lock().unwrap();
                e.apply_live_ack(&o.order_id, &bo.id);
            }
            // Some venues fill on submit; book it now rather than waiting a tick.
            if bo.filled_qty > 0.0 || bo.status.is_terminal() {
                let mut e = engine.lock().unwrap();
                e.apply_live_update(
                    &o.order_id,
                    LiveUpdate {
                        status: bo.status,
                        filled_qty: bo.filled_qty,
                        avg_price: bo.avg_price,
                        fee: bo.fee,
                        raw_status: bo.raw_status,
                    },
                );
            }
        }
        Err(e) => reject(engine, &o.order_id, &e.to_string()),
    }
}

/// Ask every venue about every order we have out, and cancel the overdue ones.
pub async fn poll_inflight(engine: &Mutex<Engine>, creds: &Credentials) {
    let polls = { engine.lock().unwrap().live_polls() };
    if polls.is_empty() {
        return;
    }
    let timeout_ms = { engine.lock().unwrap().live_config().timeout_sec as i64 * 1000 };

    for p in polls {
        let conn = match creds.connector(p.venue, p.paper) {
            Ok(c) => c,
            // Keys disappeared mid-flight. We cannot see the order any more, so
            // say so rather than leaving it silently stuck.
            Err(e) => {
                if p.age_ms > timeout_ms * 2 {
                    reject(engine, &p.order_id, &format!("lost contact with the venue: {e}"));
                }
                continue;
            }
        };

        // Overdue: stop it at the venue first, then report whatever filled.
        // Cancelling before reading means the number we book is final.
        if p.cancel {
            match conn.cancel_order(&p.broker_id, &p.symbol).await {
                Ok(()) => engine.lock().unwrap().mark_cancel_sent(&p.order_id),
                Err(e) if !e.is_transient() => {
                    // The venue refuses to cancel it (usually: already filled).
                    // Fall through to the status read, which will tell us.
                    engine.lock().unwrap().mark_cancel_sent(&p.order_id);
                    tracing::debug!("cancel {} refused: {e}", p.broker_id);
                }
                Err(_) => continue, // transient — try again next tick
            }
        }

        match conn.order_status(&p.broker_id, &p.symbol).await {
            Ok(bo) => {
                let mut e = engine.lock().unwrap();
                e.apply_live_update(
                    &p.order_id,
                    LiveUpdate {
                        status: bo.status,
                        filled_qty: bo.filled_qty,
                        avg_price: bo.avg_price,
                        fee: bo.fee,
                        raw_status: bo.raw_status,
                    },
                );
            }
            Err(e) if e.is_transient() => {} // retry next tick
            Err(e) => {
                // A hard error (auth, unknown order) that keeps repeating means
                // we will never learn this order's fate. Give up loudly, but
                // only well past the timeout so a blip cannot orphan a live order.
                if p.age_ms > timeout_ms * 2 {
                    reject(
                        engine,
                        &p.order_id,
                        &format!("could not read order {} from the venue: {e}", p.broker_id),
                    );
                }
            }
        }
    }
}

/// Pull each armed venue's real positions and let the engine correct its book.
/// Run this on startup and every few minutes — not every tick.
pub async fn reconcile(engine: &Mutex<Engine>, creds: &Credentials) {
    let cfg = { engine.lock().unwrap().live_config() };
    if !cfg.armed {
        return; // nothing of ours is live; there is nothing to reconcile against
    }
    for venue in cfg.venues.iter().copied() {
        // Spot exchanges report every coin the account holds, most of which
        // Pythia never bought. Reconciling those would claim someone's savings.
        if venue != Venue::Alpaca {
            continue;
        }
        let Ok(conn) = creds.connector(venue, cfg.paper) else { continue };
        match conn.positions().await {
            Ok(positions) => {
                engine.lock().unwrap().reconcile_positions(venue, &positions, false);
            }
            Err(e) => tracing::warn!("reconcile {venue:?} failed: {e}"),
        }
    }
}

fn reject(engine: &Mutex<Engine>, order_id: &str, reason: &str) {
    engine.lock().unwrap().apply_live_reject(order_id, reason);
}

/// Trait-object-friendly error check used by [`poll_inflight`].
trait TransientExt {
    fn is_transient(&self) -> bool;
}
impl TransientExt for ConnectorError {
    fn is_transient(&self) -> bool {
        ConnectorError::is_transient(self)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::connectors::Side;
    use crate::engine::{BrokerStatus, LiveConfig};

    fn armed(venues: Vec<Venue>) -> LiveConfig {
        LiveConfig { armed: true, paper: true, dry_run: false, venues, timeout_sec: 60, extended_hours: false }
    }

    /// A fresh "market open, account healthy" snapshot. Live Alpaca entries
    /// are refused by the engine until one arrives.
    fn open_market() -> BrokerStatus {
        BrokerStatus {
            market_open: true,
            extended_open: true,
            session_end: None,
            next_open: None,
            day_trade_limit_reached: false,
            restricted: None,
            equity: 100_000.0,
            buying_power: 200_000.0,
            checked_at: chrono::Utc::now().timestamp_millis(),
        }
    }

    #[test]
    fn paper_and_live_alpaca_keys_never_stand_in_for_each_other() {
        // Only paper keys: the live endpoint must fail as "not configured"
        // rather than quietly sending the paper pair to api.alpaca.markets.
        let paper_only = Credentials { alpaca: Some(("pk".into(), "ps".into())), ..Default::default() };
        assert!(paper_only.connector(Venue::Alpaca, true).is_ok());
        let err = paper_only.connector(Venue::Alpaca, false).err().expect("no live keys → no live connector");
        assert!(err.contains("APCA_LIVE_API_KEY_ID"), "{err}");

        // Only live keys: still counts as connected, and paper is refused.
        let live_only = Credentials { alpaca_live: Some(("lk".into(), "ls".into())), ..Default::default() };
        assert!(live_only.connector(Venue::Alpaca, false).is_ok());
        assert!(live_only.connector(Venue::Alpaca, true).is_err());
        assert!(live_only.connected_venues().contains(&Venue::Alpaca));
    }

    #[test]
    fn a_venue_with_no_credentials_reports_what_to_set() {
        let creds = Credentials::default();
        let err = creds.connector(Venue::Alpaca, true).err().expect("no keys → no connector");
        assert!(err.contains("APCA_API_KEY_ID"), "{err}");
        let err = creds.connector(Venue::Crypto, true).err().expect("no exchange → no connector");
        assert!(err.contains("exchange"), "{err}");
        assert!(creds.connected_venues().is_empty());
    }

    #[test]
    fn polymarket_never_produces_a_connector() {
        let creds = Credentials::default();
        assert!(creds.connector(Venue::Polymarket, true).is_err());
    }

    #[test]
    fn configured_venues_show_up_as_connected() {
        let creds = Credentials {
            alpaca: Some(("k".into(), "s".into())),
            exchange: Some((Exchange::Kraken, "k".into(), "s".into(), String::new())),
            ..Default::default()
        };
        let set = creds.connected_venues();
        assert!(set.contains(&Venue::Alpaca));
        assert!(set.contains(&Venue::Crypto));
        assert!(!set.contains(&Venue::Polymarket));
    }

    #[tokio::test]
    async fn a_dry_run_order_is_rejected_without_touching_the_network() {
        let engine = Mutex::new(Engine::new());
        {
            let mut e = engine.lock().unwrap();
            e.set_live(LiveConfig { dry_run: true, ..armed(vec![Venue::Alpaca]) });
            e.manual_order("alpaca:AAPL", Side::Buy, 1_000.0);
        }
        // No credentials at all — a dry run must still resolve cleanly.
        submit_pending(&engine, &Credentials::default()).await;

        let e = engine.lock().unwrap();
        assert!(e.live_polls().is_empty(), "nothing should be in flight");
        let st = e.state();
        assert_eq!(st.live.pending, 0);
        assert!(st.orders.iter().any(|o| o.reject_reason.as_deref() == Some("dry-run: not submitted")));
    }

    #[tokio::test]
    async fn a_missing_key_rejects_the_order_instead_of_stranding_it() {
        let engine = Mutex::new(Engine::new());
        {
            let mut e = engine.lock().unwrap();
            e.set_live(armed(vec![Venue::Alpaca]));
            e.set_broker_status(open_market());
            e.manual_order("alpaca:AAPL", Side::Buy, 1_000.0);
        }
        submit_pending(&engine, &Credentials::default()).await;

        let e = engine.lock().unwrap();
        assert_eq!(e.state().live.pending, 0, "the market must be freed for the next signal");
        assert!(!e.state().positions.iter().any(|p| p.market_id == "alpaca:AAPL"));
        assert!(e
            .state()
            .orders
            .iter()
            .any(|o| o.reject_reason.as_deref().unwrap_or_default().contains("APCA_API_KEY_ID")));
    }

    #[tokio::test]
    async fn reconcile_is_a_no_op_while_disarmed() {
        let engine = Mutex::new(Engine::new());
        engine.lock().unwrap().manual_order("alpaca:AAPL", Side::Buy, 1_000.0); // paper
        reconcile(&engine, &Credentials::default()).await;
        assert!(
            engine.lock().unwrap().state().positions.iter().any(|p| p.market_id == "alpaca:AAPL"),
            "a disarmed engine has nothing to reconcile and must not touch paper positions"
        );
    }
}
