//! Kraken Futures REST v3, multi-collateral linear perps (`PF_XBTUSD`).
//!
//! Docs: <https://docs.kraken.com/api/docs/guides/futures-rest> (signing),
//! the OpenAPI file <https://docs.kraken.com/openapi/futures-rest.yaml>
//! (endpoints and fields), and
//! <https://support.kraken.com/articles/4844359082772-linear-multi-collateral-perpetual-contract-specifications>
//! (funding). Response shapes below were checked against the live public
//! endpoints on 2026-10-21; the private ones are from the OpenAPI file.
//!
//! - **Signing.** Headers `APIKey`, `Nonce`, `Authent`, with
//!   `Authent = base64(HMAC-SHA512(base64(secret), SHA256(postData + nonce + path)))`
//!   where `path` drops the leading `/derivatives` ([`sign::kraken_futures_signature`]).
//! - **Errors** come back as `{"result":"error","error":"<code>"}`, often with
//!   HTTP 200; a refused order is `"result":"success"` with
//!   `sendStatus.status` other than `placed`.
//! - **Sizes** are in contracts; one `PF_` contract is one coin. The step is
//!   `10^-contractValueTradePrecision` (BTC 0.0001, XRP 1, PEPE 1000).
//! - **Fills carry no fee.** The fee is the published base tier (0.02 % maker,
//!   0.05 % taker) on the fill's notional, by its `fillType`.
//! - **Funding** is hourly, paid pro rata for the part of the hour a position
//!   is open, positive means longs pay. `fundingRate` in the history is in
//!   dollars per contract per hour, `relativeFundingRate` the same over the
//!   price; each row's `timestamp` is the START of its hour.
//! - **The demo host is gone** (see the module docs of `perps`): every request
//!   to it answers a redirect, which `PerpConnector::send` turns into
//!   [`super::KRAKEN_DEMO_GONE`].

use super::{
    alias, FundingPoint, PerpAccount, PerpConnector, PerpExchange, PerpInstrument, PerpTicker,
};
use crate::connectors::{
    num, num_or0, sign, BrokerOrder, BrokerOrderStatus, BrokerPosition, ConnectorError, OpenOrder, OrderRequest,
    OrderType,
};
#[cfg(test)]
use crate::connectors::Side;
use serde_json::Value;
use std::sync::atomic::{AtomicU64, Ordering};

const HOUR_MS: i64 = 3_600_000;

// ── public data ──────────────────────────────────────────────────────────────

pub(super) async fn fetch_instruments(http: &reqwest::Client) -> Result<Vec<PerpInstrument>, ConnectorError> {
    let base = PerpExchange::KrakenFutures.data_base();
    let v = super::get_public(http, &format!("{base}/derivatives/api/v3/instruments"), "Kraken Futures instruments").await?;
    check(&v, "instruments")?;
    Ok(parse_instruments(&v))
}

pub(super) async fn fetch_tickers(http: &reqwest::Client) -> Result<Vec<PerpTicker>, ConnectorError> {
    let base = PerpExchange::KrakenFutures.data_base();
    let v = super::get_public(http, &format!("{base}/derivatives/api/v3/tickers"), "Kraken Futures tickers").await?;
    check(&v, "tickers")?;
    Ok(parse_tickers(&v))
}

/// The whole hourly history of one contract (the endpoint takes no start).
pub(super) async fn fetch_funding(http: &reqwest::Client, symbol: &str) -> Result<Vec<FundingPoint>, ConnectorError> {
    let base = PerpExchange::KrakenFutures.data_base();
    let url = format!("{base}/derivatives/api/v3/historical-funding-rates?symbol={}", sign::urlencode(symbol));
    let v = super::get_public(http, &url, "Kraken Futures funding").await?;
    check(&v, "historical-funding-rates")?;
    Ok(parse_funding(&v))
}

/// The coin of a Kraken Futures contract: its `base` field, else the symbol
/// (`PF_XBTUSD` -> `BTC`).
fn coin_of(i: &Value, symbol: &str) -> Option<String> {
    if let Some(b) = i.get("base").and_then(Value::as_str).filter(|b| !b.is_empty()) {
        return Some(alias(b));
    }
    let core = symbol.strip_prefix("PF_")?.strip_suffix("USD")?;
    (!core.is_empty()).then(|| alias(core))
}

/// The tradable `PF_` perpetuals of an `/instruments` answer.
pub fn parse_instruments(v: &Value) -> Vec<PerpInstrument> {
    let Some(list) = v.get("instruments").and_then(Value::as_array) else { return vec![] };
    let mut out = Vec::new();
    for i in list {
        let Some(symbol) = i.get("symbol").and_then(Value::as_str) else { continue };
        if !symbol.starts_with("PF_") {
            continue;
        }
        if i.get("type").and_then(Value::as_str).is_some_and(|t| t != "flexible_futures") {
            continue;
        }
        let tradeable = i.get("tradeable").and_then(Value::as_bool).unwrap_or(false);
        let suspended = i.get("suspended").and_then(Value::as_bool).unwrap_or(false);
        let expired = i.get("isExpired").and_then(Value::as_bool).unwrap_or(false);
        if !tradeable || suspended || expired {
            continue;
        }
        let Some(coin) = coin_of(i, symbol) else { continue };
        let precision = i.get("contractValueTradePrecision").and_then(Value::as_i64).unwrap_or(0);
        let step = 10f64.powi(-(precision as i32));
        out.push(PerpInstrument {
            coin,
            symbol: symbol.to_string(),
            qty_step: step,
            min_qty: step,
            max_qty: num(i.get("maxPositionSize")).filter(|m| *m > 0.0),
            tick: num(i.get("tickSize")).unwrap_or(0.0),
            funding_period_ms: HOUR_MS,
        });
    }
    out
}

/// Marks and funding of the perpetuals in a `/tickers` answer.
pub fn parse_tickers(v: &Value) -> Vec<PerpTicker> {
    let Some(list) = v.get("tickers").and_then(Value::as_array) else { return vec![] };
    list.iter()
        .filter(|t| t.get("tag").and_then(Value::as_str).is_none_or(|g| g == "perpetual"))
        .filter_map(|t| {
            let symbol = t.get("symbol").and_then(Value::as_str)?;
            if !symbol.starts_with("PF_") {
                return None;
            }
            let mark = num(t.get("markPrice")).or_else(|| num(t.get("last"))).filter(|p| *p > 0.0)?;
            Some(PerpTicker {
                symbol: symbol.to_string(),
                mark,
                bid: num(t.get("bid")).filter(|p| *p > 0.0),
                ask: num(t.get("ask")).filter(|p| *p > 0.0),
                funding_rate: num(t.get("relativeFundingRate")),
                suspended: t.get("suspended").and_then(Value::as_bool).unwrap_or(false),
            })
        })
        .collect()
}

/// The hourly funding history, each row settled at the end of its hour.
pub fn parse_funding(v: &Value) -> Vec<FundingPoint> {
    let Some(rates) = v.get("rates").and_then(Value::as_array) else { return vec![] };
    rates
        .iter()
        .filter_map(|r| {
            let ts = r.get("timestamp").and_then(Value::as_str)?;
            let start = chrono::DateTime::parse_from_rfc3339(ts).ok()?.timestamp_millis();
            let rate = num(r.get("relativeFundingRate"))?;
            Some(FundingPoint {
                settled_ms: start + HOUR_MS,
                period_ms: HOUR_MS,
                rate,
                per_unit_usd: num(r.get("fundingRate")),
                prorated: true,
            })
        })
        .collect()
}

// ── private requests ─────────────────────────────────────────────────────────

/// A nonce that only ever grows within this process: the time in ms with a
/// four-digit counter, like Kraken's own client.
fn nonce() -> String {
    static LAST: AtomicU64 = AtomicU64::new(0);
    let candidate = (sign::epoch_ms().max(0) as u64) * 10_000;
    let mut prev = LAST.load(Ordering::Relaxed);
    loop {
        let next = candidate.max(prev + 1);
        match LAST.compare_exchange(prev, next, Ordering::Relaxed, Ordering::Relaxed) {
            Ok(_) => return next.to_string(),
            Err(p) => prev = p,
        }
    }
}

/// The three auth headers for one request.
pub fn auth_headers(key: &str, secret: &str, path: &str, nonce: &str, post_data: &str) -> Result<Vec<(&'static str, String)>, ConnectorError> {
    let authent = sign::kraken_futures_signature(secret, path, nonce, post_data).map_err(ConnectorError::Auth)?;
    Ok(vec![("APIKey", key.trim().to_string()), ("Nonce", nonce.to_string()), ("Authent", authent)])
}

async fn get(c: &PerpConnector, path: &str, params: &[(&str, String)]) -> Result<Value, ConnectorError> {
    let query = sign::form_encode(params);
    let n = nonce();
    let url = if query.is_empty() { format!("{}{path}", c.base()) } else { format!("{}{path}?{query}", c.base()) };
    let mut rb = c.http.get(url);
    for (k, v) in auth_headers(&c.key, &c.secret, path, &n, &query)? {
        rb = rb.header(k, v);
    }
    let v = c.send(rb, path).await?;
    check(&v, path)?;
    Ok(v)
}

async fn post(c: &PerpConnector, path: &str, params: &[(&str, String)]) -> Result<Value, ConnectorError> {
    // Signed over exactly the bytes sent.
    let body = sign::form_encode(params);
    let n = nonce();
    let mut rb = c
        .http
        .post(format!("{}{path}", c.base()))
        .header("content-type", "application/x-www-form-urlencoded")
        .body(body.clone());
    for (k, v) in auth_headers(&c.key, &c.secret, path, &n, &body)? {
        rb = rb.header(k, v);
    }
    let v = c.send(rb, path).await?;
    check(&v, path)?;
    Ok(v)
}

/// `{"result":"error","error":"..."}` to a connector error.
pub fn check(v: &Value, what: &str) -> Result<(), ConnectorError> {
    if v.get("result").and_then(Value::as_str) != Some("error") {
        return Ok(());
    }
    let code = v.get("error").and_then(Value::as_str).unwrap_or("unknownError");
    Err(match code {
        "authenticationError" | "invalidAccount" | "accountInactive" => {
            ConnectorError::Auth(format!("Kraken Futures {what}: {code}"))
        }
        "apiLimitExceeded" | "Unavailable" | "Server Error" | "nonceBelowThreshold" | "nonceDuplicate" => {
            ConnectorError::Network(format!("Kraken Futures {what}: {code}"))
        }
        _ => ConnectorError::Rejected(format!("Kraken Futures {what}: {code}")),
    })
}

// ── orders ───────────────────────────────────────────────────────────────────

/// The form fields of one order. A market order is `mkt` (IOC with Kraken's
/// 1 % price protection); a limit with `ioc` set is `ioc`.
pub fn order_params(req: &OrderRequest) -> Vec<(&'static str, String)> {
    let kind = match (req.order_type, req.limit_price, req.ioc) {
        (OrderType::Limit, Some(_), true) => "ioc",
        (OrderType::Limit, Some(_), false) => "lmt",
        _ => "mkt",
    };
    let mut p = vec![
        ("orderType", kind.to_string()),
        ("symbol", req.symbol.clone()),
        ("side", req.side.as_str().to_string()),
        ("size", sign::trim_decimals(req.qty, 10)),
    ];
    if kind != "mkt" {
        if let Some(px) = req.limit_price {
            p.push(("limitPrice", sign::trim_decimals(px, 10)));
        }
    }
    if let Some(cid) = &req.client_order_id {
        p.push(("cliOrdId", cid.chars().take(100).collect()));
    }
    if req.reduce_only {
        p.push(("reduceOnly", "true".into()));
    }
    p
}

/// The answer to `sendorder`: the order id and what executed at once.
pub fn parse_send(v: &Value, req: &OrderRequest) -> Result<BrokerOrder, ConnectorError> {
    let s = v.get("sendStatus").ok_or_else(|| ConnectorError::Network("Kraken Futures sendorder: no sendStatus".into()))?;
    let status = s.get("status").and_then(Value::as_str).unwrap_or("unknown");
    if !matches!(status, "placed" | "partiallyFilled" | "filled") {
        let why = match status {
            "insufficientAvailableFunds" => "not enough margin on the demo account".to_string(),
            "invalidSize" => "size not a multiple of the contract step or below the minimum".to_string(),
            "wouldNotReducePosition" => "a reduce-only order that would not reduce the position".to_string(),
            "marketSuspended" | "marketInactive" => "the market is suspended".to_string(),
            other => other.to_string(),
        };
        return Err(ConnectorError::Rejected(format!("Kraken Futures refused the order: {why} ({status})")));
    }
    let id = s
        .get("order_id")
        .and_then(Value::as_str)
        .ok_or_else(|| ConnectorError::Rejected("Kraken Futures accepted the order but returned no order_id".into()))?;
    let (qty, notional) = executions(s.get("orderEvents"));
    let (_, taker) = PerpExchange::KrakenFutures.fee_rates();
    let mut o = BrokerOrder::acknowledged(id, req.client_order_id.clone());
    if qty > 0.0 {
        o.filled_qty = qty;
        o.avg_price = Some(notional / qty);
        // What fills at once crossed the book: a taker fill.
        o.fee = notional * taker;
        o.status = if qty + 1e-12 >= req.qty { BrokerOrderStatus::Filled } else { BrokerOrderStatus::PartiallyFilled };
    }
    o.raw_status = status.to_string();
    Ok(o)
}

/// Quantity and notional of the `EXECUTION` events of an order event list.
fn executions(events: Option<&Value>) -> (f64, f64) {
    let mut qty = 0.0;
    let mut notional = 0.0;
    for e in events.and_then(Value::as_array).into_iter().flatten() {
        if e.get("type").and_then(Value::as_str) == Some("EXECUTION") {
            let a = num_or0(e.get("amount"));
            let p = num_or0(e.get("price"));
            if a > 0.0 && p > 0.0 {
                qty += a;
                notional += a * p;
            }
        }
    }
    (qty, notional)
}

/// The fills of one order (by its id or client id) in a `/fills` answer:
/// quantity, notional and fee at the published rate of each fill's type.
pub fn fills_of(v: &Value, order_id: Option<&str>, cli: Option<&str>) -> (f64, f64, f64, Option<String>) {
    let (maker, taker) = PerpExchange::KrakenFutures.fee_rates();
    let mut qty = 0.0;
    let mut notional = 0.0;
    let mut fee = 0.0;
    let mut id = None;
    for f in v.get("fills").and_then(Value::as_array).into_iter().flatten() {
        let oid = f.get("order_id").and_then(Value::as_str);
        let cid = f.get("cliOrdId").and_then(Value::as_str);
        let hit = (order_id.is_some() && oid == order_id) || (cli.is_some() && cid == cli);
        if !hit {
            continue;
        }
        let s = num_or0(f.get("size"));
        let p = num_or0(f.get("price"));
        if s <= 0.0 || p <= 0.0 {
            continue;
        }
        qty += s;
        notional += s * p;
        let rate = if f.get("fillType").and_then(Value::as_str) == Some("maker") { maker } else { taker };
        fee += s * p * rate;
        if id.is_none() {
            id = oid.map(str::to_string);
        }
    }
    (qty, notional, fee, id)
}

/// One order from `/orders/status` together with its fills. `None` when the
/// status answer does not list it.
pub fn parse_status(status: &Value, fills: &Value, order_id: Option<&str>, cli: Option<&str>) -> Option<BrokerOrder> {
    let entry = status.get("orders").and_then(Value::as_array).and_then(|list| {
        list.iter().find(|e| {
            let o = e.get("order");
            let oid = o.and_then(|o| o.get("orderId")).and_then(Value::as_str);
            let cid = o.and_then(|o| o.get("cliOrdId")).and_then(Value::as_str);
            (order_id.is_some() && oid == order_id) || (cli.is_some() && cid == cli)
        })
    });
    let (fq, notional, fee, fill_id) = fills_of(fills, order_id, cli);
    let entry_id = entry.and_then(|e| e.get("order")).and_then(|o| o.get("orderId")).and_then(Value::as_str);
    let id = entry_id.map(str::to_string).or(fill_id).or_else(|| order_id.map(str::to_string))?;
    let cid = entry
        .and_then(|e| e.get("order"))
        .and_then(|o| o.get("cliOrdId"))
        .and_then(Value::as_str)
        .map(str::to_string)
        .or_else(|| cli.map(str::to_string));
    let mut o = BrokerOrder::acknowledged(id, cid);
    match entry {
        Some(e) => {
            let raw = e.get("status").and_then(Value::as_str).unwrap_or("ENTERED_BOOK");
            let filled = num(e.get("order").and_then(|o| o.get("filled"))).unwrap_or(0.0).max(fq);
            o.filled_qty = filled;
            o.status = match raw {
                "FULLY_EXECUTED" => BrokerOrderStatus::Filled,
                "CANCELLED" => BrokerOrderStatus::Canceled,
                "REJECTED" => BrokerOrderStatus::Rejected,
                _ if filled > 0.0 => BrokerOrderStatus::PartiallyFilled,
                _ => BrokerOrderStatus::Working,
            };
            o.raw_status = raw.to_string();
        }
        None if fq > 0.0 => {
            // Older than the status window (5 s after it ended): its fills
            // are the record. A market order is immediate or cancel, so
            // whatever filled is all that ever will.
            o.filled_qty = fq;
            o.status = BrokerOrderStatus::Filled;
            o.raw_status = "filled (from fills)".into();
        }
        None => {
            order_id?;
            o.status = BrokerOrderStatus::Canceled;
            o.raw_status = "notFound".into();
        }
    }
    if fq > 0.0 {
        o.avg_price = Some(notional / fq);
        o.fee = fee;
    }
    Some(o)
}

pub(super) async fn submit(c: &PerpConnector, req: OrderRequest) -> Result<BrokerOrder, ConnectorError> {
    let v = post(c, "/derivatives/api/v3/sendorder", &order_params(&req)).await?;
    parse_send(&v, &req)
}

async fn lookup(c: &PerpConnector, order_id: Option<&str>, cli: Option<&str>) -> Result<Option<BrokerOrder>, ConnectorError> {
    let mut params = Vec::new();
    if let Some(id) = order_id {
        params.push(("orderIds", id.to_string()));
    }
    if let Some(cid) = cli {
        params.push(("cliOrdIds", cid.to_string()));
    }
    let status = post(c, "/derivatives/api/v3/orders/status", &params).await?;
    let fills = get(c, "/derivatives/api/v3/fills", &[]).await?;
    Ok(parse_status(&status, &fills, order_id, cli))
}

pub(super) async fn status(c: &PerpConnector, order_id: &str) -> Result<BrokerOrder, ConnectorError> {
    lookup(c, Some(order_id), None)
        .await?
        .ok_or_else(|| ConnectorError::Rejected(format!("Kraken Futures has no order {order_id}")))
}

pub(super) async fn by_client_id(c: &PerpConnector, cid: &str) -> Result<Option<BrokerOrder>, ConnectorError> {
    lookup(c, None, Some(cid)).await
}

pub(super) async fn cancel(c: &PerpConnector, order_id: &str) -> Result<(), ConnectorError> {
    let v = post(c, "/derivatives/api/v3/cancelorder", &[("order_id", order_id.to_string())]).await?;
    match v.get("cancelStatus").and_then(|s| s.get("status")).and_then(Value::as_str) {
        // Already gone or already filled: nothing left to cancel.
        Some("cancelled" | "filled" | "notFound") | None => Ok(()),
        Some(other) => Err(ConnectorError::Rejected(format!("Kraken Futures cancel: {other}"))),
    }
}

/// `/openorders` as the engine's open order list.
pub fn parse_open_orders(v: &Value) -> Vec<OpenOrder> {
    v.get("openOrders")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|o| {
            let id = o.get("order_id").and_then(Value::as_str)?;
            let symbol = o.get("symbol").and_then(Value::as_str)?.to_string();
            let filled = num_or0(o.get("filledSize"));
            let mut order = BrokerOrder::acknowledged(id, o.get("cliOrdId").and_then(Value::as_str).map(str::to_string));
            order.filled_qty = filled;
            order.status = if filled > 0.0 { BrokerOrderStatus::PartiallyFilled } else { BrokerOrderStatus::Working };
            order.raw_status = o.get("status").and_then(Value::as_str).unwrap_or("untouched").to_string();
            Some(OpenOrder { order, symbol })
        })
        .collect()
}

pub(super) async fn open_orders(c: &PerpConnector) -> Result<Vec<OpenOrder>, ConnectorError> {
    Ok(parse_open_orders(&get(c, "/derivatives/api/v3/openorders", &[]).await?))
}

/// `/openpositions`, signed: a short is negative.
pub fn parse_positions(v: &Value) -> Vec<BrokerPosition> {
    v.get("openPositions")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|p| {
            let symbol = p.get("symbol").and_then(Value::as_str)?.to_string();
            let size = num(p.get("size"))?;
            let sign = match p.get("side").and_then(Value::as_str) {
                Some("short") => -1.0,
                _ => 1.0,
            };
            let price = num_or0(p.get("price"));
            let qty = sign * size.abs();
            Some(BrokerPosition { symbol, qty, avg_price: price, market_value: qty * price })
        })
        .collect()
}

pub(super) async fn positions(c: &PerpConnector) -> Result<Vec<BrokerPosition>, ConnectorError> {
    Ok(parse_positions(&get(c, "/derivatives/api/v3/openpositions", &[]).await?))
}

/// The multi-collateral (`flex`) wallet of `/accounts`.
pub fn parse_account(v: &Value) -> Result<PerpAccount, ConnectorError> {
    let flex = v
        .get("accounts")
        .and_then(|a| a.get("flex"))
        .ok_or_else(|| ConnectorError::Rejected("Kraken Futures account has no multi-collateral (flex) wallet".into()))?;
    Ok(PerpAccount {
        equity: num(flex.get("portfolioValue")).or_else(|| num(flex.get("balanceValue"))).unwrap_or(0.0),
        available_margin: num_or0(flex.get("availableMargin")),
        initial_margin: num_or0(flex.get("initialMargin")),
        unrealized_funding: num_or0(flex.get("unrealizedFunding")),
    })
}

pub(super) async fn account(c: &PerpConnector) -> Result<PerpAccount, ConnectorError> {
    parse_account(&get(c, "/derivatives/api/v3/accounts", &[]).await?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn req(qty: f64) -> OrderRequest {
        let mut r = OrderRequest::market("PF_XBTUSD", Side::Sell, qty);
        r.client_order_id = Some("pythia-abc-o1".into());
        r
    }

    #[test]
    fn a_market_order_is_sent_as_mkt_with_its_client_id_and_reduce_only_flag() {
        let mut r = req(0.0123);
        r.reduce_only = true;
        let p = order_params(&r);
        assert_eq!(
            sign::form_encode(&p),
            "orderType=mkt&symbol=PF_XBTUSD&side=sell&size=0.0123&cliOrdId=pythia-abc-o1&reduceOnly=true"
        );
        let mut l = req(1.0);
        l.order_type = OrderType::Limit;
        l.limit_price = Some(64_000.5);
        l.ioc = true;
        let p = order_params(&l);
        assert_eq!(p[0].1, "ioc");
        assert!(p.iter().any(|(k, v)| *k == "limitPrice" && v == "64000.5"));
    }

    #[test]
    fn a_placed_market_order_books_its_executions_and_a_refusal_says_why() {
        let v = json!({"result":"success","serverTime":"2026-10-21T10:00:00.000Z","sendStatus":{
            "order_id":"61ca5732-3478-42fe-8362-abbfd9465294","status":"placed","receivedTime":"2026-10-21T10:00:00.000Z",
            "cliOrdId":"pythia-abc-o1","orderEvents":[
              {"type":"EXECUTION","executionId":"e1","price":64000.0,"amount":0.01},
              {"type":"EXECUTION","executionId":"e2","price":64010.0,"amount":0.0023},
              {"type":"PLACE","order":{"orderId":"61ca5732"}}]}});
        let o = parse_send(&v, &req(0.0123)).unwrap();
        assert_eq!(o.id, "61ca5732-3478-42fe-8362-abbfd9465294");
        assert_eq!(o.status, BrokerOrderStatus::Filled);
        assert!((o.filled_qty - 0.0123).abs() < 1e-12);
        let avg = (0.01 * 64000.0 + 0.0023 * 64010.0) / 0.0123;
        assert!((o.avg_price.unwrap() - avg).abs() < 1e-6);
        assert!((o.fee - 0.0123 * avg * 0.0005).abs() < 1e-9, "taker fee at the published rate");
        assert_eq!(o.client_order_id.as_deref(), Some("pythia-abc-o1"));

        let resting = json!({"result":"success","sendStatus":{"order_id":"x","status":"placed","orderEvents":[]}});
        let o = parse_send(&resting, &req(1.0)).unwrap();
        assert_eq!(o.status, BrokerOrderStatus::Working);

        let refused = json!({"result":"success","sendStatus":{"status":"insufficientAvailableFunds"}});
        let e = parse_send(&refused, &req(1.0)).unwrap_err().to_string();
        assert!(e.contains("not enough margin"), "{e}");
        let auth = json!({"result":"error","error":"authenticationError","serverTime":"x"});
        assert!(matches!(check(&auth, "sendorder"), Err(ConnectorError::Auth(_))));
        let busy = json!({"result":"error","error":"apiLimitExceeded"});
        assert!(check(&busy, "x").unwrap_err().is_transient());
    }

    #[test]
    fn the_status_of_an_order_comes_from_the_status_list_and_its_fills() {
        let status = json!({"result":"success","orders":[{"order":{"type":"ORDER","orderId":"o-1","cliOrdId":"c-1",
            "symbol":"PF_ETHUSD","side":"buy","quantity":2.0,"filled":1.5,"limitPrice":null,"reduceOnly":false},
            "status":"ENTERED_BOOK","updateReason":null,"error":null}]});
        let fills = json!({"result":"success","fills":[
            {"fill_id":"f1","symbol":"PF_ETHUSD","side":"buy","order_id":"o-1","cliOrdId":"c-1","size":1.0,"price":3000.0,"fillTime":"x","fillType":"maker"},
            {"fill_id":"f2","symbol":"PF_ETHUSD","side":"buy","order_id":"o-1","size":0.5,"price":3006.0,"fillTime":"x","fillType":"taker"},
            {"fill_id":"f3","symbol":"PF_ETHUSD","side":"buy","order_id":"other","size":9.0,"price":1.0,"fillTime":"x","fillType":"taker"}]});
        let o = parse_status(&status, &fills, Some("o-1"), None).unwrap();
        assert_eq!(o.status, BrokerOrderStatus::PartiallyFilled);
        assert!((o.filled_qty - 1.5).abs() < 1e-12);
        assert!((o.avg_price.unwrap() - 3002.0).abs() < 1e-9);
        assert!((o.fee - (3000.0 * 0.0002 + 0.5 * 3006.0 * 0.0005)).abs() < 1e-9, "maker and taker at their own rates");

        // Past the status window: the fills are the record.
        let empty = json!({"result":"success","orders":[]});
        let o = parse_status(&empty, &fills, Some("o-1"), None).unwrap();
        assert_eq!(o.status, BrokerOrderStatus::Filled);
        let o = parse_status(&empty, &json!({"fills":[]}), Some("o-9"), None).unwrap();
        assert_eq!(o.status, BrokerOrderStatus::Canceled, "an immediate-or-cancel order that left nothing");
        // Looked up by client id: found through its fills, or not at all.
        let o = parse_status(&empty, &fills, None, Some("c-1")).unwrap();
        assert_eq!(o.id, "o-1");
        assert!(parse_status(&empty, &fills, None, Some("c-404")).is_none());
    }

    #[test]
    fn positions_are_signed_and_the_flex_wallet_gives_the_margin() {
        let v = json!({"result":"success","openPositions":[
            {"side":"long","symbol":"PF_XBTUSD","price":64000.0,"size":0.05,"unrealizedFunding":-0.12},
            {"side":"short","symbol":"PF_DOGEUSD","price":0.2,"size":1500}]});
        let p = parse_positions(&v);
        assert_eq!(p.len(), 2);
        assert_eq!(p[0].qty, 0.05);
        assert_eq!(p[1].qty, -1500.0);
        assert!((p[1].market_value + 300.0).abs() < 1e-9);

        let a = json!({"result":"success","accounts":{"flex":{"type":"multiCollateralMarginAccount",
            "balanceValue":10000.0,"portfolioValue":10012.5,"availableMargin":9100.0,"initialMargin":900.0,
            "unrealizedFunding":-1.5}}});
        let acc = parse_account(&a).unwrap();
        assert_eq!(acc.equity, 10012.5);
        assert_eq!(acc.available_margin, 9100.0);
        assert!(parse_account(&json!({"accounts":{}})).is_err());

        let oo = json!({"openOrders":[{"order_id":"o-2","cliOrdId":"pythia-x","status":"untouched","side":"buy",
            "orderType":"lmt","symbol":"PF_SOLUSD","limitPrice":150.0,"filledSize":0,"unfilledSize":2}]});
        let oo = parse_open_orders(&oo);
        assert_eq!(oo[0].symbol, "PF_SOLUSD");
        assert_eq!(oo[0].order.client_order_id.as_deref(), Some("pythia-x"));
    }

    #[test]
    fn instruments_tickers_and_funding_parse_from_the_public_answers() {
        let v = json!({"result":"success","instruments":[
            {"symbol":"PF_XBTUSD","type":"flexible_futures","tickSize":1,"contractSize":1,"tradeable":true,
             "maxPositionSize":1200.0,"contractValueTradePrecision":4,"suspended":false,"base":"BTC","quote":"USD"},
            {"symbol":"PF_PEPEUSD","type":"flexible_futures","tickSize":1e-10,"tradeable":true,
             "contractValueTradePrecision":-3,"base":"PEPE"},
            {"symbol":"PF_OLDUSD","type":"flexible_futures","tradeable":false,"contractValueTradePrecision":0},
            {"symbol":"PF_SUSUSD","type":"flexible_futures","tradeable":true,"suspended":true,"contractValueTradePrecision":0},
            {"symbol":"FF_XBTUSD_261225","type":"flexible_futures","tradeable":true,"contractValueTradePrecision":4},
            {"symbol":"PI_XBTUSD","type":"futures_inverse","tradeable":true}]});
        let list = parse_instruments(&v);
        assert_eq!(list.len(), 2);
        assert_eq!(list[0].coin, "BTC");
        assert_eq!(list[0].qty_step, 0.0001);
        assert_eq!(list[0].max_qty, Some(1200.0));
        assert_eq!(list[1].coin, "PEPE");
        assert_eq!(list[1].qty_step, 1000.0, "precision -3: multiples of a thousand");
        assert_eq!(list[1].round_qty(12_345.0), 12_000.0);

        let t = json!({"result":"success","tickers":[
            {"symbol":"PF_XBTUSD","tag":"perpetual","markPrice":83465.72,"bid":83456,"ask":83457,
             "fundingRate":1.33,"relativeFundingRate":1.5956975e-05,"suspended":false},
            {"symbol":"FF_XBTUSD_261225","tag":"quarter","markPrice":84000},
            {"symbol":"PF_ZEROUSD","tag":"perpetual","markPrice":0}]});
        let t = parse_tickers(&t);
        assert_eq!(t.len(), 1);
        assert_eq!(t[0].mark, 83465.72);
        assert_eq!(t[0].funding_rate, Some(1.5956975e-05));

        let f = json!({"result":"success","rates":[
            {"timestamp":"2026-10-21T08:00:00.000Z","fundingRate":1.2,"relativeFundingRate":1.5e-05},
            {"timestamp":"2026-10-21T09:00:00Z","fundingRate":-0.4,"relativeFundingRate":-5e-06}]});
        let f = parse_funding(&f);
        assert_eq!(f.len(), 2);
        let start = chrono::DateTime::parse_from_rfc3339("2026-10-21T08:00:00Z").unwrap().timestamp_millis();
        assert_eq!(f[0].settled_ms, start + HOUR_MS, "a row is paid at the end of its hour");
        assert_eq!(f[0].per_unit_usd, Some(1.2));
        assert!(f[1].prorated && f[1].rate < 0.0);
    }

    #[test]
    fn nonces_only_grow() {
        let a: u64 = nonce().parse().unwrap();
        let b: u64 = nonce().parse().unwrap();
        assert!(b > a);
        let h = auth_headers("key", "rttp4AzwRfYEdQ7R7X8Z/04Y4TZPa97pqCypi3xXxAqftygftnI6H9yGV+OcUOOJeFtZkr8mVwbAndU3Kz4Q+eG", "/derivatives/api/v3/openpositions", "1415957147987", "").unwrap();
        assert_eq!(h[0], ("APIKey", "key".to_string()));
        assert_eq!(h[2].1, "Te83uR/IcaVaB7NTDlwkcvPV1ZyKFGjnDZ2+63Rs5B0sELkWbXOPdoDKLsVzD+v/AgnmPpAJmtF8Le7ElEVMrw==");
    }
}
