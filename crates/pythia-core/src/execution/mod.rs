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
//!   alpaca fees     →  engine.alpaca_fee_queries() →  CFEE/FEE activities → engine.apply_alpaca_fees()
//!   reconcile_demo  →  Alpaca paper positions + open orders → engine.apply_demo_reconcile()
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
    alpaca::{AlpacaConnector, AlpacaCryptoDemo},
    alpaca_crypto::OpenOrder,
    BrokerPosition, ConnectorError, Environment, MarketConnector, OrderRequest, OrderType, Venue,
};
use async_trait::async_trait;
use crate::costs::CostVenue;
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
    /// The exchange the DEMO route uses and its demo (key, secret,
    /// passphrase), from a slot of its own (`vault::exchange_demo_slot`).
    /// Never used for a live order, and the live keys above are never used for
    /// a demo one: see [`Credentials::connector_env`].
    pub exchange_demo: Option<(Exchange, String, String, String)>,
    /// The crypto venue's demo route goes to the Alpaca PAPER account
    /// (`PYTHIA_DEMO_EXCHANGE=alpaca`), with the paper pair in `alpaca` and
    /// nothing else. Only used while `exchange_demo` is empty: a demo
    /// exchange with its own keys keeps the route it always had.
    pub crypto_demo_alpaca: bool,
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

    /// The connector for one venue in one environment, built from that
    /// environment's own keys.
    ///
    /// * `Live` is [`Credentials::connector_with`]: the live exchange keys, or
    ///   Alpaca's live or paper pair by `paper` (the arm-time endpoint choice).
    /// * `Demo` is the venue's demo world with its demo keys only: Alpaca's
    ///   paper pair against `paper-api.alpaca.markets` whatever `paper` says,
    ///   and the demo exchange slot against that exchange's demo host. A demo
    ///   exchange key that is byte-for-byte the live key of the same exchange
    ///   is refused: it means the same key was pasted into both forms.
    ///   Without a demo exchange, `crypto_demo_alpaca` sends crypto demo
    ///   orders to the Alpaca paper account with the paper pair
    ///   ([`AlpacaCryptoDemo`]).
    pub fn connector_env(
        &self,
        venue: Venue,
        env: Environment,
        paper: bool,
        extended_hours: bool,
    ) -> Result<Box<dyn MarketConnector>, String> {
        if env == Environment::Live {
            return self.connector_with(venue, paper, extended_hours);
        }
        match venue {
            Venue::Alpaca => {
                let c = self.alpaca_connector(true, extended_hours).map_err(|_| {
                    "Alpaca demo means the paper account: its keys are not set (APCA_API_KEY_ID / \
                     APCA_API_SECRET_KEY, or Settings → Alpaca paper)"
                        .to_string()
                })?;
                // The paper pair only authenticates at paper-api.alpaca.markets,
                // which is where this connector points; a live pair in the
                // paper slot would be refused there (401), not trade for real.
                Ok(Box::new(c))
            }
            Venue::Crypto => {
                let Some((ex, k, s, p)) = self.exchange_demo.clone() else {
                    if self.crypto_demo_alpaca {
                        return Ok(Box::new(self.alpaca_crypto_demo()?));
                    }
                    return Err("No demo exchange is configured: add demo keys in Settings → Exchanges (Bybit, OKX \
                                or Binance), or set PYTHIA_DEMO_EXCHANGE=alpaca for the Alpaca paper account"
                        .into());
                };
                if ex.demo().is_none() {
                    return Err(format!("{} has no demo environment. {}", ex.label(), ex.no_demo_reason()));
                }
                if let Some((lex, lk, _, _)) = &self.exchange {
                    if *lex == ex && lk.trim() == k.trim() {
                        return Err(format!(
                            "the {} demo key is the same as the live key. Demo keys are created inside the \
                             venue's demo account; demo orders refused until a real demo key is saved",
                            ex.label()
                        ));
                    }
                }
                let c = CexConnector::with_env(ex, k, s, p, Environment::Demo);
                if !c.is_live_ready() {
                    return Err(format!("{} demo credentials are incomplete", ex.label()));
                }
                Ok(Box::new(c))
            }
            Venue::Polymarket => Err("Polymarket has no demo environment and no order path".into()),
        }
    }

    /// Venues whose demo route has usable keys, for the engine and the badges.
    pub fn demo_venues(&self) -> HashSet<Venue> {
        [Venue::Alpaca, Venue::Crypto]
            .into_iter()
            .filter(|v| self.connector_env(*v, Environment::Demo, true, false).is_ok())
            .collect()
    }

    /// The exchange the demo route trades on, if one is configured.
    pub fn demo_exchange(&self) -> Option<Exchange> {
        self.exchange_demo.as_ref().map(|e| e.0)
    }

    /// The crypto venue's demo route goes to the Alpaca paper account: opted
    /// in, and no demo exchange with keys of its own.
    pub fn crypto_demo_on_alpaca(&self) -> bool {
        self.crypto_demo_alpaca && self.exchange_demo.is_none()
    }

    /// The Alpaca paper connector for crypto demo orders. Built from the
    /// PAPER pair against the paper host only: the live pair is never read
    /// here, whatever the arm's endpoint says.
    pub fn alpaca_crypto_demo(&self) -> Result<AlpacaCryptoDemo, String> {
        let paper = self.alpaca_connector(true, false).map_err(|_| {
            "PYTHIA_DEMO_EXCHANGE=alpaca sends crypto demo orders to the Alpaca paper account, but its keys are \
             not set (APCA_API_KEY_ID / APCA_API_SECRET_KEY)"
                .to_string()
        })?;
        AlpacaCryptoDemo::new(paper)
    }

    /// Whose costs and name a crypto demo order carries: the demo exchange,
    /// or Alpaca on the Alpaca paper route. `None` without a crypto demo route.
    pub fn crypto_demo_venue(&self) -> Option<CostVenue> {
        match self.demo_exchange() {
            Some(ex) => Some(CostVenue::for_exchange(ex)),
            None if self.crypto_demo_on_alpaca() => Some(CostVenue::Alpaca),
            None => None,
        }
    }

    /// The crypto demo route trades on real market prices. Alpaca paper
    /// fills against Alpaca's own real quotes (docs/DEMO.md).
    pub fn crypto_demo_real_prices(&self) -> bool {
        match self.demo_exchange() {
            Some(ex) => ex.demo().is_some_and(|d| d.real_prices),
            None => self.crypto_demo_on_alpaca(),
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
    lookup_unacknowledged(engine, creds).await;
    poll_inflight(engine, creds).await;
    read_alpaca_fees(engine, creds).await;
}

/// Read the crypto fees Alpaca has posted for fills that are waiting on
/// theirs (`engine::alpaca_fees`). The engine asks at most every half hour
/// and only while it waits; Alpaca posts them at the end of the day.
/// Read-only. A failed read is simply asked again at the next interval.
pub async fn read_alpaca_fees(engine: &Mutex<Engine>, creds: &Credentials) {
    let queries = { engine.lock().unwrap().alpaca_fee_queries() };
    for q in queries {
        let Ok(conn) = creds.alpaca_connector(q.paper, false) else { continue };
        match conn.crypto_fee_activities(&q.after).await {
            Ok(acts) => engine.lock().unwrap().apply_alpaca_fees(q.paper, &acts),
            Err(e) => tracing::warn!("Alpaca fee activities ({}) not read: {e}", if q.paper { "paper" } else { "live" }),
        }
    }
}

/// Read which crypto pairs the Alpaca paper account lists and hand them to
/// the engine, when crypto demo orders go there. Hosts call it at startup and
/// once a day. Read-only. Returns how many dollar pairs Alpaca lists, or why
/// the list could not be read (the engine keeps the last list it had).
pub async fn refresh_crypto_demo_listing(engine: &Mutex<Engine>, creds: &Credentials) -> Result<usize, String> {
    if !creds.crypto_demo_on_alpaca() {
        engine.lock().unwrap().set_crypto_demo_listed(None);
        return Ok(0);
    }
    let conn = creds.alpaca_connector(true, false)?;
    let pairs = conn.tradable_crypto_pairs().await.map_err(|e| e.to_string())?;
    if pairs.is_empty() {
        // An empty answer would refuse every coin; more likely a bad read.
        return Err("Alpaca listed no tradable USD crypto pair".into());
    }
    let n = pairs.len();
    engine.lock().unwrap().set_crypto_demo_listed(Some(pairs.into_iter().collect()));
    Ok(n)
}

/// Ask the demo venue about demo orders that were sent before a restart and
/// never acknowledged, by the client id they were sent under. Found: booked
/// and followed. The venue says it has none: closed, nothing filled. The
/// venue cannot be asked: journaled with the client id, at once when it can
/// never answer (no keys, no such lookup), after twice the order timeout when
/// it only does not answer right now.
pub async fn lookup_unacknowledged(engine: &Mutex<Engine>, creds: &Credentials) {
    let lookups = { engine.lock().unwrap().client_lookups() };
    if lookups.is_empty() {
        return;
    }
    let timeout_ms = { engine.lock().unwrap().live_config().timeout_sec as i64 * 1000 };
    for l in lookups {
        let env = if l.demo { Environment::Demo } else { Environment::Live };
        let conn = match creds.connector_env(l.venue, env, true, false) {
            Ok(c) => c,
            Err(e) => {
                engine.lock().unwrap().apply_lookup_failed(&l.order_id, &e);
                continue;
            }
        };
        match conn.order_by_client_id(&l.client_order_id, &l.symbol).await {
            Ok(Some(bo)) => engine.lock().unwrap().apply_lookup_found(&l.order_id, bo),
            Ok(None) => engine.lock().unwrap().apply_lookup_missing(&l.order_id),
            Err(e) if e.is_transient() && l.age_ms <= timeout_ms * 2 => {} // ask again next tick
            Err(e) => engine.lock().unwrap().apply_lookup_failed(&l.order_id, &e.to_string()),
        }
    }
}

/// Read-only credential check, for the UI's "test connection" button and as the
/// gate before arming.
pub async fn verify(creds: &Credentials, venue: Venue, paper: bool) -> Result<String, String> {
    verify_env(creds, venue, Environment::Live, paper).await
}

/// [`verify`] for one environment: the demo check reads the demo account
/// with the demo keys, never the live ones. Read-only either way.
pub async fn verify_env(creds: &Credentials, venue: Venue, env: Environment, paper: bool) -> Result<String, String> {
    let conn = creds.connector_env(venue, env, paper, false)?;
    conn.verify().await.map_err(|e| e.to_string())
}

/// Submit everything the engine queued this tick.
pub async fn submit_pending(engine: &Mutex<Engine>, creds: &Credentials) {
    submit_pending_with(engine, |o| {
        // A demo order is built against the demo world with the demo keys; a
        // live one exactly as before. `env` comes from the engine's routing decision.
        let env = if o.demo { Environment::Demo } else { Environment::Live };
        creds.connector_env(o.venue, env, o.paper, o.extended_hours)
    })
    .await;
}

/// [`submit_pending`] with the connector for each order supplied by the
/// caller, so the whole path runs against a mock venue in tests.
pub async fn submit_pending_with<F>(engine: &Mutex<Engine>, connector_for: F)
where
    F: Fn(&LiveOrderOut) -> Result<Box<dyn MarketConnector>, String>,
{
    let orders = { engine.lock().unwrap().drain_live_orders() };
    for o in orders {
        if o.dry_run {
            reject(engine, &o.order_id, "dry-run: not submitted");
            continue;
        }
        // A route that answered 403 on its keys or account a moment ago is
        // not asked again for every queued order: each one is refused here,
        // without a request, until the pause ends.
        let paused = { engine.lock().unwrap().route_paused_until(o.venue, o.demo) };
        if let Some(until) = paused {
            let at = chrono::DateTime::from_timestamp_millis(until).map(|d| d.format("%H:%M UTC").to_string()).unwrap_or_default();
            reject(
                engine,
                &o.order_id,
                &format!("not sent: the route answered 403 a moment ago and waits until {at} before it is asked again"),
            );
            continue;
        }
        match connector_for(&o) {
            Ok(conn) => submit_one(engine, conn.as_ref(), o).await,
            Err(e) => reject(engine, &o.order_id, &e),
        }
    }
}

async fn submit_one(engine: &Mutex<Engine>, conn: &dyn MarketConnector, o: LiveOrderOut) {

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
                e.apply_live_update(&o.order_id, LiveUpdate::from(bo));
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
        let env = if p.demo { Environment::Demo } else { Environment::Live };
        let conn = match creds.connector_env(p.venue, env, p.paper, false) {
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
                e.apply_live_update(&p.order_id, LiveUpdate::from(bo));
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

/// What the paper-account reconciliation reads: the account's crypto
/// positions and its open crypto orders. [`AlpacaConnector`] reads Alpaca;
/// tests hand in a mock.
#[async_trait]
pub trait PaperAccount: Send + Sync {
    async fn crypto_positions(&self) -> Result<Vec<BrokerPosition>, ConnectorError>;
    async fn open_crypto_orders(&self) -> Result<Vec<OpenOrder>, ConnectorError>;
}

#[async_trait]
impl PaperAccount for AlpacaConnector {
    async fn crypto_positions(&self) -> Result<Vec<BrokerPosition>, ConnectorError> {
        AlpacaConnector::crypto_positions(self).await
    }
    async fn open_crypto_orders(&self) -> Result<Vec<OpenOrder>, ConnectorError> {
        AlpacaConnector::open_crypto_orders(self).await
    }
}

/// Reconcile the Alpaca paper account against the demo book, when demo
/// orders go there (crypto with `PYTHIA_DEMO_EXCHANGE=alpaca`, or Alpaca's
/// own demo route). Hosts call it at startup and every ten minutes
/// (`engine::demo_reconcile::DEMO_RECONCILE_EVERY_MS`). Read-only at the venue.
pub async fn reconcile_demo(engine: &Mutex<Engine>, creds: &Credentials) {
    if !creds.crypto_demo_on_alpaca() && !creds.demo_venues().contains(&Venue::Alpaca) {
        return;
    }
    match creds.alpaca_connector(true, false) {
        Ok(conn) => reconcile_demo_with(engine, &conn).await,
        Err(e) => engine.lock().unwrap().demo_reconcile_failed(&e),
    }
}

/// [`reconcile_demo`] against any [`PaperAccount`]. Both reads must succeed:
/// positions without the open orders would correct a pair whose order is
/// still filling.
pub async fn reconcile_demo_with(engine: &Mutex<Engine>, account: &dyn PaperAccount) {
    let positions = account.crypto_positions().await;
    let open = account.open_crypto_orders().await;
    match (positions, open) {
        (Ok(p), Ok(o)) => {
            let n = engine.lock().unwrap().apply_demo_reconcile(&p, &o);
            if n > 0 {
                tracing::warn!("Alpaca paper reconcile: {n} pair(s) differ from the demo book");
            }
        }
        (Err(e), _) | (_, Err(e)) => engine.lock().unwrap().demo_reconcile_failed(&e.to_string()),
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
    fn live_keys_are_never_used_for_demo_and_demo_keys_never_for_live() {
        // Only live Bybit keys: the demo route has nothing to use.
        let live_only = Credentials {
            exchange: Some((Exchange::Bybit, "LIVEKEY".into(), "LIVESECRET".into(), String::new())),
            ..Default::default()
        };
        assert!(live_only.connector_env(Venue::Crypto, Environment::Live, false, false).is_ok());
        let err = live_only.connector_env(Venue::Crypto, Environment::Demo, false, false).err().unwrap();
        assert!(err.contains("demo"), "{err}");
        assert!(live_only.demo_venues().is_empty());

        // Only demo keys: the live route has nothing to use.
        let demo_only = Credentials {
            exchange_demo: Some((Exchange::Bybit, "DEMOKEY".into(), "DEMOSECRET".into(), String::new())),
            ..Default::default()
        };
        assert!(demo_only.connector_env(Venue::Crypto, Environment::Live, false, false).is_err());
        let c = demo_only.connector_env(Venue::Crypto, Environment::Demo, false, false).unwrap();
        assert_eq!(c.label(), "Bybit (demo)");
        assert!(demo_only.connected_venues().is_empty(), "demo keys do not make a venue live-connected");
        assert!(demo_only.demo_venues().contains(&Venue::Crypto));

        // Both: each route gets its own world.
        let both = Credentials { exchange: live_only.exchange.clone(), ..demo_only.clone() };
        assert_eq!(both.connector_env(Venue::Crypto, Environment::Live, false, false).unwrap().label(), "Bybit");
        assert_eq!(both.connector_env(Venue::Crypto, Environment::Demo, false, false).unwrap().label(), "Bybit (demo)");

        // The same key pasted into both forms is refused for demo.
        let same = Credentials {
            exchange: Some((Exchange::Bybit, "K".into(), "S".into(), String::new())),
            exchange_demo: Some((Exchange::Bybit, " K ".into(), "S".into(), String::new())),
            ..Default::default()
        };
        let err = same.connector_env(Venue::Crypto, Environment::Demo, false, false).err().unwrap();
        assert!(err.contains("same as the live key"), "{err}");

        // A venue with no demo world refuses even with keys in the demo slot.
        let kraken = Credentials {
            exchange_demo: Some((Exchange::Kraken, "a".into(), "b".into(), String::new())),
            ..Default::default()
        };
        assert!(kraken.connector_env(Venue::Crypto, Environment::Demo, false, false).is_err());

        // Alpaca: demo is the paper account, whatever the arm's endpoint says,
        // and live keys alone never stand in for it.
        let alpaca_live = Credentials { alpaca_live: Some(("lk".into(), "ls".into())), ..Default::default() };
        assert!(alpaca_live.connector_env(Venue::Alpaca, Environment::Demo, false, false).is_err());
        let alpaca_paper = Credentials { alpaca: Some(("pk".into(), "ps".into())), ..Default::default() };
        let c = alpaca_paper.connector_env(Venue::Alpaca, Environment::Demo, false, false).unwrap();
        assert_eq!(c.label(), "Alpaca (paper)");
    }

    fn alpaca_route(paper: bool, live: bool) -> Credentials {
        Credentials {
            alpaca: paper.then(|| ("PAPERKEY".to_string(), "PAPERSECRET".to_string())),
            alpaca_live: live.then(|| ("LIVEKEY".to_string(), "LIVESECRET".to_string())),
            crypto_demo_alpaca: true,
            ..Default::default()
        }
    }

    #[test]
    fn crypto_demo_goes_to_alpaca_paper_only_when_opted_in_and_no_demo_exchange_is_set() {
        // Opted in with the paper pair: the crypto venue's demo route is Alpaca paper.
        let creds = alpaca_route(true, true);
        let c = creds.connector_env(Venue::Crypto, Environment::Demo, false, false).unwrap();
        assert_eq!((c.venue(), c.label().as_str()), (Venue::Crypto, "Alpaca (paper)"));
        assert!(creds.demo_venues().contains(&Venue::Crypto) && creds.demo_venues().contains(&Venue::Alpaca));
        assert!(creds.crypto_demo_on_alpaca());
        assert_eq!(creds.crypto_demo_venue(), Some(CostVenue::Alpaca));
        assert!(creds.crypto_demo_real_prices());
        assert_eq!(creds.demo_exchange(), None);

        // Not opted in: no crypto demo route, as before.
        let off = Credentials { crypto_demo_alpaca: false, ..creds.clone() };
        assert!(off.connector_env(Venue::Crypto, Environment::Demo, false, false).is_err());
        assert!(!off.demo_venues().contains(&Venue::Crypto));
        assert_eq!(off.crypto_demo_venue(), None);

        // A real demo exchange with its keys keeps its route.
        let bybit = Credentials {
            exchange_demo: Some((Exchange::Bybit, "DEMOKEY".into(), "DEMOSECRET".into(), String::new())),
            ..creds.clone()
        };
        let c = bybit.connector_env(Venue::Crypto, Environment::Demo, false, false).unwrap();
        assert_eq!(c.label(), "Bybit (demo)");
        assert!(!bybit.crypto_demo_on_alpaca());
        assert_eq!(bybit.crypto_demo_venue(), Some(CostVenue::Bybit));

        // Live crypto is untouched: still only the live exchange.
        assert!(creds.connector_env(Venue::Crypto, Environment::Live, true, false).is_err());
        assert!(!creds.connected_venues().contains(&Venue::Crypto));
    }

    #[test]
    fn the_alpaca_crypto_demo_route_never_uses_the_live_alpaca_keys() {
        // Both pairs set: the route signs with the paper pair, on the paper host.
        let both = alpaca_route(true, true);
        let c = both.alpaca_crypto_demo().unwrap();
        assert!(c.is_paper());
        assert_eq!(c.key_id(), Some("PAPERKEY"));
        // Whatever the live arm's endpoint says (`paper = false`).
        let boxed = both.connector_env(Venue::Crypto, Environment::Demo, false, false).unwrap();
        assert_eq!(boxed.label(), "Alpaca (paper)");

        // Only the live pair: refused, never borrowed.
        let live_only = alpaca_route(false, true);
        let err = live_only.connector_env(Venue::Crypto, Environment::Demo, false, false).err().unwrap();
        assert!(err.contains("PYTHIA_DEMO_EXCHANGE=alpaca") && err.contains("APCA_API_KEY_ID"), "{err}");
        assert!(!live_only.demo_venues().contains(&Venue::Crypto));
        assert!(live_only.alpaca_crypto_demo().is_err());
    }

    #[tokio::test]
    async fn a_crypto_demo_order_on_a_pair_alpaca_cannot_trade_is_rejected_before_any_request() {
        // The connector the daemon builds for a crypto demo order, and a pair
        // Alpaca has no dollar book for: refused by preflight and by submit
        // alike, with no request built (these keys would fail if one were).
        let conn = alpaca_route(true, false).connector_env(Venue::Crypto, Environment::Demo, false, false).unwrap();
        let req = OrderRequest::market("BTC/USDT", Side::Buy, 0.01);
        let err = conn.preflight(&req).await.unwrap_err();
        assert!(err.to_string().contains("BTC/USDT is not listed on Alpaca"), "{err}");
        let err = conn.submit_order(req).await.unwrap_err();
        assert!(err.to_string().contains("not listed on Alpaca"), "{err}");
    }

    #[tokio::test]
    async fn a_demo_order_without_demo_keys_is_rejected_and_never_reaches_the_live_keys() {
        let engine = Mutex::new(Engine::new());
        {
            let mut e = engine.lock().unwrap();
            // The engine believes a demo route exists (stale host state), but
            // the credentials only hold LIVE keys.
            e.set_demo_venues([Venue::Crypto].into_iter().collect(), Some(crate::costs::CostVenue::Bybit), true);
            e.place_order("ema-cross-1", "crypto:BTC/USD", Side::Buy, 1_000.0, crate::engine::RouteIntent::Demo).unwrap();
        }
        let creds = Credentials {
            exchange: Some((Exchange::Bybit, "LIVEKEY".into(), "LIVESECRET".into(), String::new())),
            ..Default::default()
        };
        submit_pending(&engine, &creds).await;
        let e = engine.lock().unwrap();
        assert_eq!(e.state().live.pending, 0);
        let row = e.state().orders.into_iter().find(|o| o.market_id == "crypto:BTC/USD").unwrap();
        assert_eq!(row.status, crate::engine::OrderStatus::Rejected);
        assert!(row.reject_reason.unwrap_or_default().contains("demo"));
        assert!(e.state().journal.iter().any(|j| j.message.starts_with("DEMO order not sent")));
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
            e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
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
            e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
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
        engine.lock().unwrap().live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0); // paper
        reconcile(&engine, &Credentials::default()).await;
        assert!(
            engine.lock().unwrap().state().positions.iter().any(|p| p.market_id == "alpaca:AAPL"),
            "a disarmed engine has nothing to reconcile and must not touch paper positions"
        );
    }

    // ── the Alpaca paper route against a mock venue ──

    use crate::connectors::alpaca_crypto::{parse_open_orders, CryptoRules, QtyFit};
    use crate::connectors::{BrokerOrder, BrokerPosition};
    use crate::costs::CostVenue as CV;
    use crate::engine::RouteIntent;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;

    /// A venue that answers every submission the same way and counts them.
    struct MockVenue {
        submits: Arc<AtomicUsize>,
        sent: Arc<Mutex<Vec<f64>>>,
        answer: fn() -> Result<BrokerOrder, ConnectorError>,
        rules: Option<CryptoRules>,
    }

    #[async_trait]
    impl MarketConnector for MockVenue {
        fn venue(&self) -> Venue {
            Venue::Crypto
        }
        fn is_live_ready(&self) -> bool {
            true
        }
        fn round_qty(&self, qty: f64, _symbol: &str) -> f64 {
            match self.rules.map(|r| r.fit_qty(qty)) {
                Some(QtyFit::Ok(q)) => q,
                Some(QtyFit::BelowMinimum { .. }) => 0.0,
                None => qty,
            }
        }
        async fn verify(&self) -> Result<String, ConnectorError> {
            Ok("mock".into())
        }
        async fn submit_order(&self, req: OrderRequest) -> Result<BrokerOrder, ConnectorError> {
            self.submits.fetch_add(1, Ordering::SeqCst);
            self.sent.lock().unwrap().push(req.qty);
            (self.answer)()
        }
        async fn order_status(&self, broker_id: &str, _symbol: &str) -> Result<BrokerOrder, ConnectorError> {
            Ok(BrokerOrder::acknowledged(broker_id, None))
        }
        async fn cancel_order(&self, _broker_id: &str, _symbol: &str) -> Result<(), ConnectorError> {
            Ok(())
        }
    }

    struct Mock {
        submits: Arc<AtomicUsize>,
        sent: Arc<Mutex<Vec<f64>>>,
        answer: fn() -> Result<BrokerOrder, ConnectorError>,
        rules: Option<CryptoRules>,
    }

    impl Mock {
        fn new(answer: fn() -> Result<BrokerOrder, ConnectorError>) -> Self {
            Mock { submits: Arc::new(AtomicUsize::new(0)), sent: Arc::new(Mutex::new(Vec::new())), answer, rules: None }
        }
        fn conn(&self) -> Result<Box<dyn MarketConnector>, String> {
            Ok(Box::new(MockVenue { submits: self.submits.clone(), sent: self.sent.clone(), answer: self.answer, rules: self.rules }))
        }
        fn submits(&self) -> usize {
            self.submits.load(Ordering::SeqCst)
        }
    }

    /// Crypto demo orders on the Alpaca paper account, one demo buy queued per market.
    fn alpaca_demo(markets: &[&str]) -> Mutex<Engine> {
        let mut e = Engine::new();
        e.fresh_crypto_prices_for_test();
        e.set_demo_venues([Venue::Crypto].into_iter().collect(), Some(CV::Alpaca), true);
        for m in markets {
            e.place_order("ema-cross-1", m, Side::Buy, 1_000.0, RouteIntent::Demo).expect("routed");
        }
        Mutex::new(e)
    }

    fn journal_count(engine: &Mutex<Engine>, needle: &str) -> usize {
        engine.lock().unwrap().state().journal.iter().filter(|j| j.message.contains(needle)).count()
    }

    const MARKETS: [&str; 3] = ["crypto:BTC/USD", "crypto:ETH/USD", "crypto:SOL/USD"];

    #[tokio::test]
    async fn a_403_on_the_keys_is_asked_once_not_once_per_queued_order() {
        let engine = alpaca_demo(&MARKETS);
        let mock = Mock::new(|| Err(ConnectorError::Auth("HTTP 403 on submit: are these paper keys?".into())));
        submit_pending_with(&engine, |_| mock.conn()).await;
        assert_eq!(mock.submits(), 1, "the first 403 pauses the route; the rest are not sent");
        let e = engine.lock().unwrap();
        assert_eq!(e.state().live.pending, 0);
        let rejected = e.state().orders.iter().filter(|o| o.status == crate::engine::OrderStatus::Rejected).count();
        assert_eq!(rejected, 3, "every queued order is closed with its reason");
        assert!(e.route_paused_until(Venue::Crypto, true).is_some());
        drop(e);
        assert_eq!(journal_count(&engine, "DEMO order not sent"), 1, "one note for the route, not three");

        // Signals keep firing: nothing reaches the venue until the pause ends.
        let err = engine.lock().unwrap().place_order("ema-cross-1", "crypto:XRP/USD", Side::Buy, 1_000.0, RouteIntent::Demo).unwrap_err();
        assert!(err.contains("backing off"), "{err}");
        submit_pending_with(&engine, |_| mock.conn()).await;
        assert_eq!(mock.submits(), 1);
    }

    #[tokio::test]
    async fn an_insufficient_balance_refusal_holds_its_market_only() {
        let engine = alpaca_demo(&MARKETS[..2]);
        let mock = Mock::new(|| {
            Err(ConnectorError::Rejected(
                r#"submit 403: {"code":40310000,"message":"insufficient balance for USD (requested: 1000, available: 12.5)"}"#.into(),
            ))
        });
        submit_pending_with(&engine, |_| mock.conn()).await;
        assert_eq!(mock.submits(), 2, "a balance refusal is not a route problem: both were asked");
        let mut e = engine.lock().unwrap();
        assert!(e.route_paused_until(Venue::Crypto, true).is_none());
        let err = e.place_order("ema-cross-1", "crypto:BTC/USD", Side::Buy, 1_000.0, RouteIntent::Demo).unwrap_err();
        assert!(err.contains("backing off"), "{err}");
        assert!(e.state().journal.iter().any(|j| j.message.contains("insufficient balance: this market waits 15 min")));
    }

    #[tokio::test]
    async fn a_wash_trade_or_a_422_is_one_request_and_a_wait() {
        let engine = alpaca_demo(&MARKETS[..1]);
        let mock = Mock::new(|| Err(ConnectorError::Rejected(r#"submit 403: {"message":"potential wash trade detected. use complex orders"}"#.into())));
        submit_pending_with(&engine, |_| mock.conn()).await;
        assert_eq!(mock.submits(), 1);
        assert!(journal_count(&engine, "[wash trade: this market waits 5 min]") == 1);

        let engine = alpaca_demo(&MARKETS[..1]);
        let mock = Mock::new(|| Err(ConnectorError::Rejected(r#"submit 422: {"message":"invalid crypto time_in_force"}"#.into())));
        submit_pending_with(&engine, |_| mock.conn()).await;
        assert_eq!(mock.submits(), 1);
        assert!(journal_count(&engine, "[422 unprocessable: this market waits 30 min]") == 1);
    }

    #[tokio::test]
    async fn quantities_go_out_on_the_step_and_below_the_minimum_nothing_is_sent() {
        let btc = CryptoRules { min_order_size: 0.0001, min_trade_increment: 1e-9, price_increment: 1.0 };
        // On the step: what is sent is the rounded-down quantity.
        let engine = alpaca_demo(&MARKETS[..1]);
        let mut mock = Mock::new(|| Ok(BrokerOrder::acknowledged("alp-1", None)));
        mock.rules = Some(btc);
        let wanted = { engine.lock().unwrap().state().orders[0].qty };
        submit_pending_with(&engine, |_| mock.conn()).await;
        let sent = mock.sent.lock().unwrap()[0];
        assert!(sent <= wanted && wanted - sent < 1e-9, "{sent} for {wanted}");
        assert_eq!(sent, btc.floor_qty(sent), "on the 1e-9 step");
        assert_eq!(engine.lock().unwrap().state().live.pending, 1, "acknowledged and followed");

        // Below the minimum: skipped without a request, with the reason.
        let engine = alpaca_demo(&MARKETS[..1]);
        let mut mock = Mock::new(|| Ok(BrokerOrder::acknowledged("never", None)));
        mock.rules = Some(CryptoRules { min_order_size: 10.0, ..btc });
        submit_pending_with(&engine, |_| mock.conn()).await;
        assert_eq!(mock.submits(), 0, "never sent to be rejected");
        let e = engine.lock().unwrap();
        let row = &e.state().orders[0];
        assert!(row.reject_reason.as_deref().unwrap_or_default().contains("below"), "{row:?}");
        assert!(e.state().journal.iter().any(|j| j.message.contains("[below the minimum order size: this market waits 30 min]")));
    }

    /// A paper account that answers with fixed positions and open orders, or fails.
    struct MockAccount {
        positions: Result<Vec<BrokerPosition>, ()>,
        open: Vec<crate::connectors::alpaca_crypto::OpenOrder>,
    }

    #[async_trait]
    impl PaperAccount for MockAccount {
        async fn crypto_positions(&self) -> Result<Vec<BrokerPosition>, ConnectorError> {
            self.positions.clone().map_err(|_| ConnectorError::Network("timed out".into()))
        }
        async fn open_crypto_orders(&self) -> Result<Vec<crate::connectors::alpaca_crypto::OpenOrder>, ConnectorError> {
            Ok(self.open.clone())
        }
    }

    #[tokio::test]
    async fn the_paper_reconcile_reads_positions_and_open_orders_and_needs_both() {
        let engine = alpaca_demo(&MARKETS[..1]);
        let mock = Mock::new(|| {
            let mut o = BrokerOrder::acknowledged("alp-1", None);
            o.status = crate::connectors::BrokerOrderStatus::Filled;
            o.filled_qty = 0.016;
            o.avg_price = Some(62_000.0);
            Ok(o)
        });
        submit_pending_with(&engine, |_| mock.conn()).await;
        let btc = BrokerPosition { symbol: "BTC/USD".into(), qty: 0.016, avg_price: 62_000.0, market_value: 992.0 };

        // A failed read changes nothing and says why.
        let down = MockAccount { positions: Err(()), open: Vec::new() };
        reconcile_demo_with(&engine, &down).await;
        let d = engine.lock().unwrap().demo_reconcile().unwrap();
        assert!(d.error.unwrap_or_default().contains("timed out"));

        // Agreement.
        let up = MockAccount { positions: Ok(vec![btc.clone()]), open: Vec::new() };
        reconcile_demo_with(&engine, &up).await;
        let d = engine.lock().unwrap().demo_reconcile().unwrap();
        assert_eq!((d.mismatches, d.error), (0, None));

        // A stray open order is reported.
        let open = parse_open_orders(&serde_json::json!([{"id":"x","symbol":"BTC/USD","asset_class":"crypto","side":"sell","qty":"0.016","filled_qty":"0","status":"new"}]));
        let stray = MockAccount { positions: Ok(vec![btc]), open };
        reconcile_demo_with(&engine, &stray).await;
        let d = engine.lock().unwrap().demo_reconcile().unwrap();
        assert_eq!(d.stray_orders.len(), 1);
    }

    #[tokio::test]
    async fn no_paper_route_means_no_paper_reconcile() {
        let engine = Mutex::new(Engine::new());
        reconcile_demo(&engine, &Credentials::default()).await;
        assert!(engine.lock().unwrap().demo_reconcile().is_none());
    }
}
