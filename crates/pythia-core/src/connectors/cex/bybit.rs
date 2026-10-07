//! Bybit v5 spot (`https://api.bybit.com`).
//!
//! Demo: `https://api-demo.bybit.com`, same paths, same signing, a key created
//! inside the Demo Trading account
//! (<https://bybit-exchange.github.io/docs/v5/demo>).
//!
//! Signature covers `timestamp + api_key + recv_window + (query | rawBody)`, so
//! the body must be signed and sent byte-identically — it is serialised once and
//! passed through as a string.
//!
//! The dangerous default here is `marketUnit`: a spot **market buy** on Bybit
//! sizes in the *quote* currency unless told otherwise. Left alone, an order for
//! "0.5 BTC" would spend 0.5 USDT. Every submission pins `marketUnit=baseCoin`.

use super::super::{
    num_or0, sign, Balance, BrokerOrder, BrokerOrderStatus, ConnectorError, OrderRequest, OrderType,
};
use super::{is_fiat, normalize_asset, CexConnector};
use serde_json::Value;

const BASE: &str = "https://api.bybit.com";
const RECV_WINDOW: &str = "10000";

fn headers(c: &CexConnector, ts: &str, payload: &str) -> Vec<(&'static str, String)> {
    let signature = sign::hmac_sha256_hex(
        c.secret.trim(),
        &format!("{ts}{}{RECV_WINDOW}{payload}", c.key.trim()),
    );
    vec![
        ("X-BAPI-API-KEY", c.key.trim().to_string()),
        ("X-BAPI-TIMESTAMP", ts.to_string()),
        ("X-BAPI-RECV-WINDOW", RECV_WINDOW.to_string()),
        ("X-BAPI-SIGN", signature),
    ]
}

async fn get(c: &CexConnector, path: &str, params: &[(&str, String)]) -> Result<Value, ConnectorError> {
    let query = sign::form_encode(params);
    let ts = sign::epoch_ms().to_string();
    let mut rb = c.http.get(format!("{}{path}?{query}", c.base(BASE)));
    for (k, v) in headers(c, &ts, &query) {
        rb = rb.header(k, v);
    }
    let v = c.send(rb, path).await?;
    check_error(&v, path)?;
    Ok(v.get("result").cloned().unwrap_or(Value::Null))
}

async fn post(c: &CexConnector, path: &str, body: &Value) -> Result<Value, ConnectorError> {
    // Sign exactly the bytes we send — not a re-serialisation of them.
    let raw = serde_json::to_string(body).map_err(|e| ConnectorError::Network(e.to_string()))?;
    let ts = sign::epoch_ms().to_string();
    let mut rb = c
        .http
        .post(format!("{}{path}", c.base(BASE)))
        .header("content-type", "application/json")
        .body(raw.clone());
    for (k, v) in headers(c, &ts, &raw) {
        rb = rb.header(k, v);
    }
    let v = c.send(rb, path).await?;
    check_error(&v, path)?;
    Ok(v.get("result").cloned().unwrap_or(Value::Null))
}

/// Bybit answers 200 with `retCode != 0` on failure.
fn check_error(v: &Value, what: &str) -> Result<(), ConnectorError> {
    let code = v.get("retCode").and_then(Value::as_i64).unwrap_or(0);
    if code == 0 {
        return Ok(());
    }
    let msg = v.get("retMsg").and_then(Value::as_str).unwrap_or("unknown error");
    Err(match code {
        // 10003 invalid key, 10004 bad signature, 10005 permission denied.
        10003 | 10004 | 10005 => ConnectorError::Auth(format!("Bybit: {msg}")),
        _ => ConnectorError::Rejected(format!("Bybit {what}: {msg} ({code})")),
    })
}

fn map_status(s: &str) -> BrokerOrderStatus {
    match s {
        "Filled" => BrokerOrderStatus::Filled,
        "PartiallyFilled" => BrokerOrderStatus::PartiallyFilled,
        // Bybit closes a partially filled order it can no longer work with this.
        "PartiallyFilledCanceled" | "Cancelled" | "Deactivated" => BrokerOrderStatus::Canceled,
        "Rejected" => BrokerOrderStatus::Rejected,
        _ => BrokerOrderStatus::Working, // New, Created, Untriggered
    }
}

fn parse_order(v: &Value) -> Result<BrokerOrder, ConnectorError> {
    let id = v
        .get("orderId")
        .and_then(Value::as_str)
        .ok_or_else(|| ConnectorError::Network("Bybit order response has no orderId".into()))?
        .to_string();
    let raw = v.get("orderStatus").and_then(Value::as_str).unwrap_or("New").to_string();
    let filled = num_or0(v.get("cumExecQty"));
    let value = num_or0(v.get("cumExecValue"));
    Ok(BrokerOrder {
        id,
        client_order_id: v.get("orderLinkId").and_then(Value::as_str).map(str::to_string),
        status: map_status(&raw),
        filled_qty: filled,
        avg_price: (filled > 0.0 && value > 0.0).then(|| value / filled),
        fee: num_or0(v.get("cumExecFee")),
        raw_status: raw,
    })
}

pub(super) async fn submit(c: &CexConnector, req: OrderRequest) -> Result<BrokerOrder, ConnectorError> {
    let mut body = serde_json::json!({
        "category": "spot",
        "symbol": c.exchange.symbol(&req.symbol),
        "side": if req.side == super::super::Side::Buy { "Buy" } else { "Sell" },
        "orderType": if req.order_type == OrderType::Limit { "Limit" } else { "Market" },
        "qty": sign::trim_decimals(req.qty, 8),
        // Without this a market BUY sizes in USDT, not in the coin.
        "marketUnit": "baseCoin",
    });
    if let (OrderType::Limit, Some(p)) = (req.order_type, req.limit_price) {
        body["price"] = serde_json::json!(sign::trim_decimals(p, 8));
        body["timeInForce"] = serde_json::json!("GTC");
    }
    if let Some(cid) = &req.client_order_id {
        // orderLinkId is capped at 36 chars.
        body["orderLinkId"] = serde_json::json!(cid.chars().take(36).collect::<String>());
    }

    let result = post(c, "/v5/order/create", &body).await?;
    let id = result
        .get("orderId")
        .and_then(Value::as_str)
        .ok_or_else(|| ConnectorError::Rejected("Bybit accepted the order but returned no orderId".into()))?;
    Ok(BrokerOrder {
        id: id.to_string(),
        client_order_id: req.client_order_id,
        status: BrokerOrderStatus::Working,
        filled_qty: 0.0,
        avg_price: None,
        fee: 0.0,
        raw_status: "submitted".into(),
    })
}

pub(super) async fn status(c: &CexConnector, order_id: &str, symbol: &str) -> Result<BrokerOrder, ConnectorError> {
    let params = [
        ("category", "spot".to_string()),
        ("symbol", symbol.to_string()),
        ("orderId", order_id.to_string()),
    ];
    // `realtime` only keeps open orders; once terminal the order moves to
    // history, so a miss there is a look-up in `/v5/order/history`.
    let live = get(c, "/v5/order/realtime", &params).await?;
    if let Some(o) = live.get("list").and_then(Value::as_array).and_then(|a| a.first()) {
        return parse_order(o);
    }
    let hist = get(c, "/v5/order/history", &params).await?;
    let o = hist
        .get("list")
        .and_then(Value::as_array)
        .and_then(|a| a.first())
        .ok_or_else(|| ConnectorError::Rejected(format!("Bybit has no order {order_id}")))?;
    parse_order(o)
}

pub(super) async fn cancel(c: &CexConnector, order_id: &str, symbol: &str) -> Result<(), ConnectorError> {
    let body = serde_json::json!({ "category": "spot", "symbol": symbol, "orderId": order_id });
    match post(c, "/v5/order/cancel", &body).await {
        Ok(_) => Ok(()),
        // 110001 "order does not exist" — already terminal.
        Err(ConnectorError::Rejected(m)) if m.contains("110001") => Ok(()),
        Err(e) => Err(e),
    }
}

pub(super) async fn balances(c: &CexConnector) -> Result<Vec<Balance>, ConnectorError> {
    let result = get(c, "/v5/account/wallet-balance", &[("accountType", "UNIFIED".to_string())]).await?;
    let Some(accounts) = result.get("list").and_then(Value::as_array) else { return Ok(vec![]) };

    let mut out = Vec::new();
    for acct in accounts {
        let Some(coins) = acct.get("coin").and_then(Value::as_array) else { continue };
        for co in coins {
            let total = num_or0(co.get("walletBalance"));
            if total <= 0.0 {
                continue;
            }
            let Some(asset) = co.get("coin").and_then(Value::as_str).map(normalize_asset) else { continue };
            // availableToWithdraw is blank on some unified accounts; fall back
            // to the full balance rather than reporting nothing tradable.
            let free = match num_or0(co.get("availableToWithdraw")) {
                f if f > 0.0 => f,
                _ => total,
            };
            let usd = match num_or0(co.get("usdValue")) {
                u if u > 0.0 => Some(u),
                _ => is_fiat(&asset).then_some(total),
            };
            out.push(Balance { asset, free, total, usd_value: usd });
        }
    }
    out.sort_by(|a, b| a.asset.cmp(&b.asset));
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ret_code_zero_is_success_everything_else_is_not() {
        assert!(check_error(&serde_json::json!({"retCode": 0, "retMsg": "OK"}), "/create").is_ok());
        assert!(check_error(&serde_json::json!({"retCode": 10004, "retMsg": "error sign"}), "/create")
            .is_err_and(|e| matches!(e, ConnectorError::Auth(_))));
        assert!(check_error(&serde_json::json!({"retCode": 170131, "retMsg": "Balance insufficient"}), "/create")
            .is_err_and(|e| matches!(e, ConnectorError::Rejected(_))));
    }

    #[test]
    fn a_partially_filled_cancel_keeps_the_filled_quantity() {
        let v: Value = serde_json::json!({
            "orderId": "abc", "orderStatus": "PartiallyFilledCanceled",
            "cumExecQty": "0.25", "cumExecValue": "8000", "cumExecFee": "8"
        });
        let o = parse_order(&v).unwrap();
        assert_eq!(o.status, BrokerOrderStatus::Canceled);
        assert!(o.status.is_terminal());
        assert_eq!(o.filled_qty, 0.25, "the 0.25 that did fill is a real position");
        assert_eq!(o.avg_price, Some(32000.0));
        assert_eq!(o.fee, 8.0);
    }

    #[test]
    fn statuses_map_and_unknown_stays_working() {
        assert_eq!(map_status("Filled"), BrokerOrderStatus::Filled);
        assert_eq!(map_status("New"), BrokerOrderStatus::Working);
        assert!(!map_status("SomethingBybitAdded").is_terminal());
    }

    #[test]
    fn the_signature_covers_timestamp_key_window_and_body() {
        let c = CexConnector::new(super::super::Exchange::Bybit, "KEY".into(), "SECRET".into(), String::new());
        let hs = headers(&c, "1700000000000", r#"{"a":1}"#);
        let sig = hs.iter().find(|(k, _)| *k == "X-BAPI-SIGN").unwrap().1.clone();
        let expected = sign::hmac_sha256_hex("SECRET", &format!("1700000000000KEY{RECV_WINDOW}{{\"a\":1}}"));
        assert_eq!(sig, expected);
    }
}
