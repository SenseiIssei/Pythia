//! The perps route's reads, for the hosts' loops (see `engine::perps`).
//!
//! ```text
//!   market      every minute: contracts (daily) and marks + funding now, public, no keys
//!   funding     every few minutes: settled funding of what is held, public  -> engine.apply_perp_funding()
//!   account     every minute: the demo account's margin, demo keys          -> engine.set_perp_account()
//!   reconcile   at startup and every 10 minutes: positions + open orders    -> engine.apply_perp_reconcile()
//! ```
//!
//! Orders themselves go through the ordinary execution cycle: the engine
//! queues them like any demo order and `Credentials::connector_env` builds
//! the perps demo connector for them. The engine lock is never held across a
//! request.

use std::sync::Mutex;

use super::Credentials;
use crate::connectors::perps::{self, PerpExchange};
use crate::connectors::MarketConnector;
use crate::engine::Engine;

/// Read the venue's contract list (when the engine says it is due) and every
/// mark. Public data; works without keys (paper perps).
pub async fn refresh_perps_market(engine: &Mutex<Engine>, http: &reqwest::Client, marks: bool) -> Result<usize, String> {
    let (ex, due) = {
        let e = engine.lock().unwrap();
        (e.perps_exchange(), e.perp_instruments_due())
    };
    let Some(ex) = ex else { return Ok(0) };
    if due {
        let list = perps::fetch_instruments(http, ex).await.map_err(|e| format!("{} contracts: {e}", ex.label()))?;
        engine.lock().unwrap().set_perp_instruments(list);
    }
    if !marks {
        return Ok(0);
    }
    let tickers = perps::fetch_tickers(http, ex).await.map_err(|e| format!("{} marks: {e}", ex.label()))?;
    let n = tickers.len();
    engine.lock().unwrap().apply_perp_tickers(&tickers);
    Ok(n)
}

/// Book the settled funding of every perps symbol held, where due.
pub async fn book_perps_funding(engine: &Mutex<Engine>, http: &reqwest::Client) {
    let (ex, due) = {
        let e = engine.lock().unwrap();
        (e.perps_exchange(), e.perp_funding_due())
    };
    let Some(ex) = ex else { return };
    for (symbol, since) in due {
        match perps::fetch_funding(http, ex, &symbol, since).await {
            Ok(points) => {
                engine.lock().unwrap().apply_perp_funding(&symbol, &points);
            }
            Err(e) => tracing::warn!("{} funding for {symbol} not read: {e}", ex.label()),
        }
    }
}

/// Read the demo account's margin (demo keys only).
pub async fn read_perps_account(engine: &Mutex<Engine>, creds: &Credentials) {
    let conn = match creds.perps_connector() {
        Ok(c) => c,
        Err(_) => return,
    };
    let read = conn.account().await.map_err(|e| e.to_string());
    engine.lock().unwrap().set_perp_account(read);
}

/// Compare the demo account with the books. Both reads must succeed:
/// positions without the open orders would correct a symbol whose order is
/// still filling.
pub async fn reconcile_perps(engine: &Mutex<Engine>, creds: &Credentials) {
    if !engine.lock().unwrap().perp_reconcile_wanted() {
        return;
    }
    let conn = match creds.perps_connector() {
        Ok(c) => c,
        Err(e) => return engine.lock().unwrap().perp_reconcile_failed(&e),
    };
    let positions = conn.positions().await;
    let open = conn.open_orders().await;
    match (positions, open) {
        (Ok(p), Ok(o)) => {
            let n = engine.lock().unwrap().apply_perp_reconcile(&p, &o);
            if n > 0 {
                tracing::warn!("perps demo reconcile: {n} symbol(s) differ from the books");
            }
        }
        (Err(e), _) | (_, Err(e)) => engine.lock().unwrap().perp_reconcile_failed(&e.to_string()),
    }
}

/// Which perps venue a host follows: `PYTHIA_PERPS_DEMO` when set
/// (`kraken_futures` or `bybit`), else the venue whose demo keys are set,
/// else Kraken Futures (marks and funding for paper perps). `None` only when
/// the setting names no known venue or is `off`.
pub fn perps_exchange_from(setting: Option<&str>, creds: &Credentials) -> Option<PerpExchange> {
    match setting.map(str::trim).filter(|s| !s.is_empty()) {
        Some(s) if s.eq_ignore_ascii_case("off") || s.eq_ignore_ascii_case("none") => None,
        Some(s) => PerpExchange::parse(s),
        None => Some(creds.perps_exchange().unwrap_or(PerpExchange::KrakenFutures)),
    }
}
