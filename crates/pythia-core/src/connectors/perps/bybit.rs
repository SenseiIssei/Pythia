//! Bybit v5, category `linear` (USDT-margined perpetuals), on the Demo
//! Trading account.
//!
//! Docs: <https://bybit-exchange.github.io/docs/v5/demo> (demo host
//! `https://api-demo.bybit.com`, keys created inside the Demo Trading
//! account, public data identical to mainnet, "basic trading rules are the
//! same as real trading"), <https://bybit-exchange.github.io/docs/v5/order/create-order>,
//! `.../order/open-order`, `.../order/order-list`, `.../position`,
//! `.../account/wallet-balance`, `.../market/instrument`, `.../market/tickers`
//! and `.../market/history-fund-rate`.
//!
//! Signing is the spot connector's: `X-BAPI-SIGN = hex(HMAC-SHA256(secret,
//! timestamp + key + recvWindow + (query | body)))`. Orders are one-way mode
//! (`positionIdx` 0), sized in contracts (`1000PEPEUSDT` is a thousand PEPE
//! per contract). Funding settles every `fundingInterval` minutes (480 for
//! most contracts) and is paid by whoever holds the position at that moment;
//! a positive rate means longs pay shorts.

use super::{coin_of_usdt_symbol, FundingPoint, PerpAccount, PerpConnector, PerpExchange, PerpInstrument, PerpTicker};
use crate::connectors::{
    num, num_or0, sign, BrokerOrder, BrokerOrderStatus, BrokerPosition, ConnectorError, OpenOrder, OrderRequest,
    OrderType, Side,
};
use serde_json::Value;

const RECV_WINDOW: &str = "10000";

// ── public data ──────────────────────────────────────────────────────────────

pub(super) async fn fetch_instruments(http: &reqwest::Client) -> Result<Vec<PerpInstrument>, ConnectorError> {
    let base = PerpExchange::Bybit.data_base();
    let mut out = Vec::new();
    let mut cursor = String::new();
    for _ in 0..10 {
        let mut url = format!("{base}/v5/market/instruments-info?category=linear&limit=1000");
        if !cursor.is_empty() {
            url.push_str(&format!("&cursor={}", sign::urlencode(&cursor)));
        }
        let v = super::get_public(http, &url, "Bybit instruments").await?;
        check(&v, "instruments-info")?;
        out.extend(parse_instruments(&v));
        cursor = v
            .get("result")
            .and_then(|r| r.get("nextPageCursor"))
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        if cursor.is_empty() {
            break;
        }
    }
    Ok(out)
}

pub(super) async fn fetch_tickers(http: &reqwest::Client) -> Result<Vec<PerpTicker>, ConnectorError> {
    let base = PerpExchange::Bybit.data_base();
    let v = super::get_public(http, &format!("{base}/v5/market/tickers?category=linear"), "Bybit tickers").await?;
    check(&v, "tickers")?;
    Ok(parse_tickers(&v))
}

/// The last 200 settlements of one contract (about 66 days at 8 h).
pub(super) async fn fetch_funding(http: &reqwest::Client, symbol: &str, _since_ms: i64) -> Result<Vec<FundingPoint>, ConnectorError> {
    let base = PerpExchange::Bybit.data_base();
    let url = format!(
        "{base}/v5/market/funding/history?category=linear&symbol={}&endTime={}&limit=200",
        sign::urlencode(symbol),
        sign::epoch_ms()
    );
    let v = super::get_public(http, &url, "Bybit funding").await?;
    check(&v, "funding/history")?;
    let period = crate::connectors::perps::instrument(symbol)
        .map(|i| i.funding_period_ms)
        .unwrap_or_else(|| PerpExchange::Bybit.default_funding_period_ms());
    Ok(parse_funding(&v, period))
}

fn list(v: &Value) -> impl Iterator<Item = &Value> {
    v.get("result").and_then(|r| r.get("list")).and_then(Value::as_array).into_iter().flatten()
}

/// The trading USDT perpetuals of an `instruments-info` page.
pub fn parse_instruments(v: &Value) -> Vec<PerpInstrument> {
    list(v)
        .filter(|i| i.get("contractType").and_then(Value::as_str) == Some("LinearPerpetual"))
        .filter(|i| i.get("status").and_then(Value::as_str) == Some("Trading"))
        .filter(|i| i.get("quoteCoin").and_then(Value::as_str).is_none_or(|q| q == "USDT"))
        .filter_map(|i| {
            let symbol = i.get("symbol").and_then(Value::as_str)?;
            let coin = coin_of_usdt_symbol(symbol)?;
            let lot = i.get("lotSizeFilter");
            let step = num(lot.and_then(|l| l.get("qtyStep"))).filter(|s| *s > 0.0)?;
            let minutes = num(i.get("fundingInterval")).filter(|m| *m > 0.0).unwrap_or(480.0);
            Some(PerpInstrument {
                coin,
                symbol: symbol.to_string(),
                qty_step: step,
                min_qty: num(lot.and_then(|l| l.get("minOrderQty"))).unwrap_or(step),
                // A market order is capped by the market-order maximum.
                max_qty: num(lot.and_then(|l| l.get("maxMktOrderQty")))
                    .or_else(|| num(lot.and_then(|l| l.get("maxOrderQty"))))
                    .filter(|m| *m > 0.0),
                tick: num(i.get("priceFilter").and_then(|p| p.get("tickSize"))).unwrap_or(0.0),
                funding_period_ms: (minutes * 60_000.0) as i64,
            })
        })
        .collect()
}

pub fn parse_tickers(v: &Value) -> Vec<PerpTicker> {
    list(v)
        .filter_map(|t| {
            let symbol = t.get("symbol").and_then(Value::as_str)?;
            if !symbol.ends_with("USDT") {
                return None;
            }
            let mark = num(t.get("markPrice")).or_else(|| num(t.get("lastPrice"))).filter(|p| *p > 0.0)?;
            Some(PerpTicker {
                symbol: symbol.to_string(),
                mark,
                bid: num(t.get("bid1Price")).filter(|p| *p > 0.0),
                ask: num(t.get("ask1Price")).filter(|p| *p > 0.0),
                funding_rate: num(t.get("fundingRate")),
                suspended: false,
            })
        })
        .collect()
}

pub fn parse_funding(v: &Value, period_ms: i64) -> Vec<FundingPoint> {
    list(v)
        .filter_map(|r| {
            Some(FundingPoint {
                settled_ms: num(r.get("fundingRateTimestamp"))? as i64,
                period_ms,
                rate: num(r.get("fundingRate"))?,
                per_unit_usd: None,
                prorated: false,
            })
        })
        .collect()
}

// ── private requests ─────────────────────────────────────────────────────────

fn headers(c: &PerpConnector, ts: &str, payload: &str) -> Vec<(&'static str, String)> {
    let signature = sign::hmac_sha256_hex(c.secret.trim(), &format!("{ts}{}{RECV_WINDOW}{payload}", c.key.trim()));
    vec![
        ("X-BAPI-API-KEY", c.key.trim().to_string()),
        ("X-BAPI-TIMESTAMP", ts.to_string()),
        ("X-BAPI-RECV-WINDOW", RECV_WINDOW.to_string()),
        ("X-BAPI-SIGN", signature),
    ]
}

async fn get(c: &PerpConnector, path: &str, params: &[(&str, String)]) -> Result<Value, ConnectorError> {
    let query = sign::form_encode(params);
    let ts = sign::epoch_ms().to_string();
    let mut rb = c.http.get(format!("{}{path}?{query}", c.base()));
    for (k, v) in headers(c, &ts, &query) {
        rb = rb.header(k, v);
    }
    let v = c.send(rb, path).await?;
    check(&v, path)?;
    Ok(v)
}

async fn post(c: &PerpConnector, path: &str, body: &Value) -> Result<Value, ConnectorError> {
    let raw = serde_json::to_string(body).map_err(|e| ConnectorError::Network(e.to_string()))?;
    let ts = sign::epoch_ms().to_string();
    let mut rb = c.http.post(format!("{}{path}", c.base())).header("content-type", "application/json").body(raw.clone());
    for (k, v) in headers(c, &ts, &raw) {
        rb = rb.header(k, v);
    }
    let v = c.send(rb, path).await?;
    check(&v, path)?;
    Ok(v)
}

/// Bybit answers 200 with `retCode != 0` on failure.
pub fn check(v: &Value, what: &str) -> Result<(), ConnectorError> {
    let code = v.get("retCode").and_then(Value::as_i64).unwrap_or(0);
    if code == 0 {
        return Ok(());
    }
    let msg = v.get("retMsg").and_then(Value::as_str).unwrap_or("unknown error");
    Err(match code {
        10003..=10005 => ConnectorError::Auth(format!("Bybit demo: {msg}")),
        10006 | 10016 => ConnectorError::Network(format!("Bybit {what}: {msg} ({code})")),
        110007 => ConnectorError::Rejected(format!("Bybit refused the order: not enough margin on the demo account ({code})")),
        _ => ConnectorError::Rejected(format!("Bybit {what}: {msg} ({code})")),
    })
}

/// The JSON body of one order.
pub fn order_body(req: &OrderRequest) -> Value {
    let limit = req.order_type == OrderType::Limit && req.limit_price.is_some();
    let mut body = serde_json::json!({
        "category": "linear",
        "symbol": req.symbol,
        "side": if req.side == Side::Buy { "Buy" } else { "Sell" },
        "orderType": if limit { "Limit" } else { "Market" },
        "qty": sign::trim_decimals(req.qty, 10),
        "positionIdx": 0,
    });
    if limit {
        body["price"] = serde_json::json!(sign::trim_decimals(req.limit_price.unwrap_or_default(), 10));
        body["timeInForce"] = serde_json::json!(if req.ioc { "IOC" } else { "GTC" });
    }
    if let Some(cid) = &req.client_order_id {
        body["orderLinkId"] = serde_json::json!(link_id(cid));
    }
    if req.reduce_only {
        body["reduceOnly"] = serde_json::json!(true);
    }
    body
}

/// Client ids are capped at 36 characters.
fn link_id(cid: &str) -> String {
    cid.chars().take(36).collect()
}

fn map_status(s: &str) -> BrokerOrderStatus {
    match s {
        "Filled" => BrokerOrderStatus::Filled,
        "PartiallyFilled" => BrokerOrderStatus::PartiallyFilled,
        "PartiallyFilledCanceled" | "Cancelled" | "Deactivated" => BrokerOrderStatus::Canceled,
        "Rejected" => BrokerOrderStatus::Rejected,
        _ => BrokerOrderStatus::Working,
    }
}

/// One order of an order list. Fees are in USDT, taken as dollars.
pub fn parse_order(v: &Value) -> Option<BrokerOrder> {
    let id = v.get("orderId").and_then(Value::as_str)?;
    let raw = v.get("orderStatus").and_then(Value::as_str).unwrap_or("New").to_string();
    let filled = num_or0(v.get("cumExecQty"));
    let value = num_or0(v.get("cumExecValue"));
    let mut o = BrokerOrder::acknowledged(
        id,
        v.get("orderLinkId").and_then(Value::as_str).filter(|s| !s.is_empty()).map(str::to_string),
    );
    o.status = map_status(&raw);
    o.filled_qty = filled;
    o.avg_price = num(v.get("avgPrice"))
        .filter(|p| *p > 0.0)
        .or_else(|| (filled > 0.0 && value > 0.0).then(|| value / filled));
    o.fee = num_or0(v.get("cumExecFee"));
    o.raw_status = raw;
    Some(o)
}

pub(super) async fn submit(c: &PerpConnector, req: OrderRequest) -> Result<BrokerOrder, ConnectorError> {
    let v = post(c, "/v5/order/create", &order_body(&req)).await?;
    let id = v
        .get("result")
        .and_then(|r| r.get("orderId"))
        .and_then(Value::as_str)
        .ok_or_else(|| ConnectorError::Rejected("Bybit accepted the order but returned no orderId".into()))?;
    Ok(BrokerOrder::acknowledged(id, req.client_order_id))
}

async fn find(c: &PerpConnector, key: (&'static str, String), symbol: &str) -> Result<Option<BrokerOrder>, ConnectorError> {
    let params = [("category", "linear".to_string()), ("symbol", symbol.to_string()), key];
    let live = get(c, "/v5/order/realtime", &params).await?;
    if let Some(o) = list(&live).next().and_then(parse_order) {
        return Ok(Some(o));
    }
    let hist = get(c, "/v5/order/history", &params).await?;
    let found = list(&hist).next().and_then(parse_order);
    Ok(found)
}

pub(super) async fn status(c: &PerpConnector, order_id: &str, symbol: &str) -> Result<BrokerOrder, ConnectorError> {
    find(c, ("orderId", order_id.to_string()), symbol)
        .await?
        .ok_or_else(|| ConnectorError::Rejected(format!("Bybit has no order {order_id}")))
}

pub(super) async fn by_client_id(c: &PerpConnector, cid: &str, symbol: &str) -> Result<Option<BrokerOrder>, ConnectorError> {
    find(c, ("orderLinkId", link_id(cid)), symbol).await
}

pub(super) async fn cancel(c: &PerpConnector, order_id: &str, symbol: &str) -> Result<(), ConnectorError> {
    let body = serde_json::json!({ "category": "linear", "symbol": symbol, "orderId": order_id });
    match post(c, "/v5/order/cancel", &body).await {
        Ok(_) => Ok(()),
        // 110001: the order no longer exists (already filled or cancelled).
        Err(ConnectorError::Rejected(m)) if m.contains("110001") => Ok(()),
        Err(e) => Err(e),
    }
}

pub fn parse_open_orders(v: &Value) -> Vec<OpenOrder> {
    list(v)
        .filter_map(|o| {
            let symbol = o.get("symbol").and_then(Value::as_str)?.to_string();
            Some(OpenOrder { order: parse_order(o)?, symbol })
        })
        .collect()
}

pub(super) async fn open_orders(c: &PerpConnector) -> Result<Vec<OpenOrder>, ConnectorError> {
    let v = get(c, "/v5/order/realtime", &[("category", "linear".into()), ("settleCoin", "USDT".into())]).await?;
    Ok(parse_open_orders(&v))
}

/// `/v5/position/list`, signed: a short (`side` Sell) is negative.
pub fn parse_positions(v: &Value) -> Vec<BrokerPosition> {
    list(v)
        .filter_map(|p| {
            let symbol = p.get("symbol").and_then(Value::as_str)?.to_string();
            let size = num(p.get("size")).filter(|s| *s > 0.0)?;
            let sign = match p.get("side").and_then(Value::as_str) {
                Some("Sell") => -1.0,
                Some("Buy") => 1.0,
                _ => return None,
            };
            let avg = num_or0(p.get("avgPrice"));
            let qty = sign * size;
            Some(BrokerPosition { symbol, qty, avg_price: avg, market_value: qty * avg })
        })
        .collect()
}

pub(super) async fn positions(c: &PerpConnector) -> Result<Vec<BrokerPosition>, ConnectorError> {
    let mut out = Vec::new();
    let mut cursor = String::new();
    for _ in 0..10 {
        let mut params = vec![("category", "linear".to_string()), ("settleCoin", "USDT".to_string()), ("limit", "200".to_string())];
        if !cursor.is_empty() {
            params.push(("cursor", cursor.clone()));
        }
        let v = get(c, "/v5/position/list", &params).await?;
        out.extend(parse_positions(&v));
        cursor = v.get("result").and_then(|r| r.get("nextPageCursor")).and_then(Value::as_str).unwrap_or("").to_string();
        if cursor.is_empty() {
            break;
        }
    }
    Ok(out)
}

/// The unified account's totals.
pub fn parse_account(v: &Value) -> Result<PerpAccount, ConnectorError> {
    let a = list(v).next().ok_or_else(|| ConnectorError::Rejected("Bybit demo: no unified account in the answer".into()))?;
    Ok(PerpAccount {
        equity: num_or0(a.get("totalEquity")),
        available_margin: num_or0(a.get("totalAvailableBalance")),
        initial_margin: num_or0(a.get("totalInitialMargin")),
        unrealized_funding: 0.0,
    })
}

pub(super) async fn account(c: &PerpConnector) -> Result<PerpAccount, ConnectorError> {
    parse_account(&get(c, "/v5/account/wallet-balance", &[("accountType", "UNIFIED".to_string())]).await?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn an_order_body_is_linear_one_way_and_reduce_only_when_asked() {
        let mut r = OrderRequest::market("1000PEPEUSDT", Side::Sell, 1200.0);
        r.client_order_id = Some("pythia-0123456789abcdef-o12345678901234567".into());
        let b = order_body(&r);
        assert_eq!(b["category"], "linear");
        assert_eq!(b["orderType"], "Market");
        assert_eq!(b["side"], "Sell");
        assert_eq!(b["qty"], "1200");
        assert_eq!(b["positionIdx"], 0);
        assert_eq!(b["orderLinkId"].as_str().unwrap().len(), 36);
        assert!(b.get("reduceOnly").is_none());
        r.reduce_only = true;
        r.order_type = OrderType::Limit;
        r.limit_price = Some(0.0123);
        r.ioc = true;
        let b = order_body(&r);
        assert_eq!(b["reduceOnly"], true);
        assert_eq!(b["timeInForce"], "IOC");
        assert_eq!(b["price"], "0.0123");
    }

    #[test]
    fn orders_positions_and_the_account_parse() {
        let o = json!({"orderId":"b-1","orderLinkId":"pythia-x","orderStatus":"Filled","cumExecQty":"0.05",
            "cumExecValue":"3200","cumExecFee":"1.76","avgPrice":"64000"});
        let o = parse_order(&o).unwrap();
        assert_eq!(o.status, BrokerOrderStatus::Filled);
        assert_eq!(o.avg_price, Some(64000.0));
        assert_eq!(o.fee, 1.76);
        let p = json!({"retCode":0,"result":{"list":[
            {"symbol":"BTCUSDT","side":"Buy","size":"0.05","avgPrice":"64000"},
            {"symbol":"DOGEUSDT","side":"Sell","size":"1500","avgPrice":"0.2"},
            {"symbol":"ETHUSDT","side":"","size":"0","avgPrice":"0"}]}});
        let p = parse_positions(&p);
        assert_eq!(p.len(), 2);
        assert_eq!(p[1].qty, -1500.0);
        let a = json!({"retCode":0,"result":{"list":[{"accountType":"UNIFIED","totalEquity":"50000.5",
            "totalAvailableBalance":"48000","totalInitialMargin":"2000.5"}]}});
        let a = parse_account(&a).unwrap();
        assert_eq!(a.equity, 50000.5);
        assert_eq!(a.available_margin, 48000.0);
        let refused = json!({"retCode":110007,"retMsg":"ab not enough for new order"});
        assert!(check(&refused, "x").unwrap_err().to_string().contains("not enough margin"));
        assert!(matches!(check(&json!({"retCode":10003,"retMsg":"API key is invalid."}), "x"), Err(ConnectorError::Auth(_))));
    }

    #[test]
    fn instruments_tickers_and_funding_parse() {
        let v = json!({"retCode":0,"result":{"list":[
            {"symbol":"BTCUSDT","contractType":"LinearPerpetual","status":"Trading","baseCoin":"BTC","quoteCoin":"USDT",
             "fundingInterval":480,"lotSizeFilter":{"maxOrderQty":"1190","minOrderQty":"0.001","qtyStep":"0.001","maxMktOrderQty":"119"},
             "priceFilter":{"tickSize":"0.10"}},
            {"symbol":"1000PEPEUSDT","contractType":"LinearPerpetual","status":"Trading","baseCoin":"1000PEPE","quoteCoin":"USDT",
             "fundingInterval":240,"lotSizeFilter":{"minOrderQty":"100","qtyStep":"100"},"priceFilter":{"tickSize":"0.0000001"}},
            {"symbol":"BTC-26DEC26","contractType":"LinearFutures","status":"Trading","quoteCoin":"USDC","lotSizeFilter":{"qtyStep":"0.001"}},
            {"symbol":"OLDUSDT","contractType":"LinearPerpetual","status":"Closed","quoteCoin":"USDT","lotSizeFilter":{"qtyStep":"1"}}]}});
        let l = parse_instruments(&v);
        assert_eq!(l.len(), 2);
        assert_eq!(l[0].max_qty, Some(119.0), "a market order is capped by the market-order maximum");
        assert_eq!(l[1].coin, "PEPE");
        assert_eq!(l[1].funding_period_ms, 4 * 3_600_000);
        let t = json!({"retCode":0,"result":{"list":[{"symbol":"BTCUSDT","markPrice":"64000.5","bid1Price":"64000","ask1Price":"64001",
            "fundingRate":"0.0001"}]}});
        assert_eq!(parse_tickers(&t)[0].funding_rate, Some(0.0001));
        let f = json!({"retCode":0,"result":{"list":[{"symbol":"BTCUSDT","fundingRate":"0.0001","fundingRateTimestamp":"1791504000000"}]}});
        let f = parse_funding(&f, 8 * 3_600_000);
        assert_eq!(f[0].settled_ms, 1791504000000);
        assert!(!f[0].prorated);
    }
}
