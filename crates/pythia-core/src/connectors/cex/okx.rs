//! OKX v5 spot (`https://www.okx.com`).
//!
//! Signature is `base64(HMAC-SHA256(secret, timestamp + METHOD + requestPath + body))`
//! with an ISO-8601 millisecond timestamp — not epoch millis, which is the
//! mistake OKX's `50113 Invalid Sign` usually means. `requestPath` includes the
//! query string.
//!
//! OKX also needs the API **passphrase** you chose when creating the key, in
//! addition to key and secret.
//!
//! Like Bybit, a spot market **buy** sizes in the quote currency by default;
//! `tgtCcy=base_ccy` pins it to the coin.
//!
//! Demo trading uses the same host with `x-simulated-trading: 1` and a demo
//! key and passphrase (see [`simulated_header`]).

use super::super::{
    num_or0, sign, Balance, BrokerOrder, BrokerOrderStatus, ConnectorError, OrderRequest, OrderType,
};
use super::{is_fiat, normalize_asset, CexConnector, FeeSplit};
use serde_json::Value;

const BASE: &str = super::OKX_HOST;

/// OKX's demo world is the production host plus this header, with a key
/// created under Demo Trading
/// (<https://www.okx.com/docs-v5/en/#overview-demo-trading-services>).
/// `1` is demo, `0` production. Sent explicitly in both worlds, so a demo key
/// on a live connector (or the reverse) is refused by OKX with 50101 rather
/// than guessed at.
fn simulated_header(c: &CexConnector) -> (&'static str, &'static str) {
    ("x-simulated-trading", if c.env.is_demo() { "1" } else { "0" })
}

/// OKX wants `2020-12-08T09:08:57.715Z`, to the millisecond.
fn iso_timestamp() -> String {
    chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S%.3fZ").to_string()
}

async fn request(
    c: &CexConnector,
    method: reqwest::Method,
    request_path: &str,
    body: &str,
) -> Result<Value, ConnectorError> {
    let ts = iso_timestamp();
    let signature = sign::hmac_sha256_b64(
        c.secret.trim(),
        &format!("{ts}{}{request_path}{body}", method.as_str()),
    );

    let (sim_k, sim_v) = simulated_header(c);
    let mut rb = c
        .http
        .request(method, format!("{}{request_path}", c.base(BASE)))
        .header(sim_k, sim_v)
        .header("OK-ACCESS-KEY", c.key.trim())
        .header("OK-ACCESS-SIGN", signature)
        .header("OK-ACCESS-TIMESTAMP", ts)
        .header("OK-ACCESS-PASSPHRASE", c.passphrase.trim())
        .header("content-type", "application/json");
    if !body.is_empty() {
        rb = rb.body(body.to_string());
    }

    let v = c.send(rb, request_path).await?;
    check_error(&v, request_path)?;
    Ok(v.get("data").cloned().unwrap_or(Value::Null))
}

/// OKX answers 200 with a string `code`; "0" is success. Per-order failures also
/// appear inside `data[0].sCode`, which is what an insufficient balance looks
/// like — a top-level code of "1" with the real reason one level down.
fn check_error(v: &Value, what: &str) -> Result<(), ConnectorError> {
    let code = v.get("code").and_then(Value::as_str).unwrap_or("0");
    if code == "0" {
        return Ok(());
    }
    let inner = v
        .get("data")
        .and_then(Value::as_array)
        .and_then(|a| a.first())
        .and_then(|d| d.get("sMsg"))
        .and_then(Value::as_str);
    let msg = inner
        .or_else(|| v.get("msg").and_then(Value::as_str))
        .unwrap_or("unknown error");
    Err(match code {
        // 50111/50113 bad key or signature, 50114 bad passphrase, 50101 a
        // demo key on the live world or a live key on the demo one.
        "50101" | "50111" | "50113" | "50114" | "50100" => ConnectorError::Auth(format!("OKX: {msg}")),
        _ => ConnectorError::Rejected(format!("OKX {what}: {msg} ({code})")),
    })
}

fn map_status(s: &str) -> BrokerOrderStatus {
    match s {
        "filled" => BrokerOrderStatus::Filled,
        "partially_filled" => BrokerOrderStatus::PartiallyFilled,
        "canceled" | "mmp_canceled" => BrokerOrderStatus::Canceled,
        _ => BrokerOrderStatus::Working, // live
    }
}

/// Parse one order of `GET /api/v5/trade/order`
/// (<https://www.okx.com/docs-v5/en/#order-book-trading-trade-get-order-details>).
///
/// The fee comes as `fee` plus `feeCcy`. OKX: `feeCcy` is the "currency in
/// which fees are charged" (the quote currency only for maker sells), and
/// its own example is a spot buy of BTC-USDT with `"fee": "-0.00000192834",
/// "feeCcy": "BTC"`: a buy pays in the coin bought. `fee` is negative for a
/// fee paid and positive for a net rebate, and is already net of the rebate,
/// so `rebate` is not added again.
fn parse_order(v: &Value, base: &str, quote: &str) -> Result<BrokerOrder, ConnectorError> {
    let id = v
        .get("ordId")
        .and_then(Value::as_str)
        .ok_or_else(|| ConnectorError::Network("OKX order response has no ordId".into()))?
        .to_string();
    let raw = v.get("state").and_then(Value::as_str).unwrap_or("live").to_string();
    let filled = num_or0(v.get("accFillSz"));
    let mut order = BrokerOrder {
        id,
        client_order_id: v.get("clOrdId").and_then(Value::as_str).filter(|s| !s.is_empty()).map(str::to_string),
        status: map_status(&raw),
        filled_qty: filled,
        // avgPx is blank until something fills.
        avg_price: Some(num_or0(v.get("avgPx"))).filter(|p| *p > 0.0),
        fee: 0.0,
        fee_base: 0.0,
        fee_unpriced: Vec::new(),
        raw_status: raw,
    };
    // Paid is negative at OKX; Pythia counts a fee paid as positive. A net
    // rebate is not booked as income: the engine never lets a fee go below zero.
    let paid = (-num_or0(v.get("fee"))).max(0.0);
    // No feeCcy (an older answer): the quote currency, as Pythia always assumed.
    let ccy = v.get("feeCcy").and_then(Value::as_str).filter(|s| !s.is_empty()).unwrap_or(quote);
    FeeSplit::fold([(ccy, paid)], base, quote).apply(&mut order);
    Ok(order)
}

pub(super) async fn submit(c: &CexConnector, req: OrderRequest) -> Result<BrokerOrder, ConnectorError> {
    let mut order = serde_json::json!({
        "instId": c.exchange.symbol(&req.symbol),
        "tdMode": "cash",                       // spot, no margin
        "side": req.side.as_str(),
        "ordType": if req.order_type == OrderType::Limit { "limit" } else { "market" },
        "sz": sign::trim_decimals(req.qty, 8),
        // Without this a market BUY sizes in USDT, not in the coin.
        "tgtCcy": "base_ccy",
    });
    if let (OrderType::Limit, Some(p)) = (req.order_type, req.limit_price) {
        order["px"] = serde_json::json!(sign::trim_decimals(p, 8));
    }
    if let Some(cid) = &req.client_order_id {
        // clOrdId: alphanumeric, 1–32 characters.
        let clean: String = cid.chars().filter(char::is_ascii_alphanumeric).take(32).collect();
        if !clean.is_empty() {
            order["clOrdId"] = serde_json::json!(clean);
        }
    }

    let body = serde_json::to_string(&serde_json::json!([order]))
        .map_err(|e| ConnectorError::Network(e.to_string()))?;
    let data = request(c, reqwest::Method::POST, "/api/v5/trade/order", &body).await?;
    let first = data
        .as_array()
        .and_then(|a| a.first())
        .ok_or_else(|| ConnectorError::Rejected("OKX returned no order data".into()))?;
    let id = first
        .get("ordId")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| ConnectorError::Rejected("OKX accepted the order but returned no ordId".into()))?;

    Ok(BrokerOrder::acknowledged(id, req.client_order_id))
}

pub(super) async fn status(
    c: &CexConnector,
    order_id: &str,
    symbol: &str,
    base: &str,
    quote: &str,
) -> Result<BrokerOrder, ConnectorError> {
    let path = format!("/api/v5/trade/order?instId={symbol}&ordId={order_id}");
    let data = request(c, reqwest::Method::GET, &path, "").await?;
    let o = data
        .as_array()
        .and_then(|a| a.first())
        .ok_or_else(|| ConnectorError::Rejected(format!("OKX has no order {order_id}")))?;
    parse_order(o, base, quote)
}

pub(super) async fn cancel(c: &CexConnector, order_id: &str, symbol: &str) -> Result<(), ConnectorError> {
    let body = serde_json::to_string(&serde_json::json!({ "instId": symbol, "ordId": order_id }))
        .map_err(|e| ConnectorError::Network(e.to_string()))?;
    match request(c, reqwest::Method::POST, "/api/v5/trade/cancel-order", &body).await {
        Ok(_) => Ok(()),
        // 51400/51401 — order already cancelled or does not exist.
        Err(ConnectorError::Rejected(m)) if m.contains("51400") || m.contains("51401") || m.contains("51603") => Ok(()),
        Err(e) => Err(e),
    }
}

pub(super) async fn balances(c: &CexConnector) -> Result<Vec<Balance>, ConnectorError> {
    let data = request(c, reqwest::Method::GET, "/api/v5/account/balance", "").await?;
    let Some(details) = data
        .as_array()
        .and_then(|a| a.first())
        .and_then(|d| d.get("details"))
        .and_then(Value::as_array)
    else {
        return Ok(vec![]);
    };

    let mut out = Vec::new();
    for d in details {
        let total = num_or0(d.get("eq")).max(num_or0(d.get("cashBal")));
        if total <= 0.0 {
            continue;
        }
        let Some(asset) = d.get("ccy").and_then(Value::as_str).map(normalize_asset) else { continue };
        let free = match num_or0(d.get("availBal")) {
            f if f > 0.0 => f,
            _ => total,
        };
        let usd = match num_or0(d.get("eqUsd")) {
            u if u > 0.0 => Some(u),
            _ => is_fiat(&asset).then_some(total),
        };
        out.push(Balance { asset, free, total, usd_value: usd });
    }
    out.sort_by(|a, b| a.asset.cmp(&b.asset));
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_real_reason_is_pulled_out_of_the_nested_scode() {
        // OKX's top-level msg is empty here; the useful text is in data[0].sMsg.
        let v: Value = serde_json::json!({
            "code": "1", "msg": "",
            "data": [{"sCode": "51008", "sMsg": "Order placement failed due to insufficient balance"}]
        });
        let e = check_error(&v, "/trade/order").unwrap_err();
        assert!(e.to_string().contains("insufficient balance"), "{e}");
    }

    #[test]
    fn code_zero_is_success_and_auth_codes_map_to_auth() {
        assert!(check_error(&serde_json::json!({"code": "0"}), "/x").is_ok());
        assert!(check_error(&serde_json::json!({"code": "50114", "msg": "Invalid passphrase"}), "/x")
            .is_err_and(|e| matches!(e, ConnectorError::Auth(_))));
    }

    #[test]
    fn fees_are_reported_positive_even_though_okx_sends_them_negative() {
        let v: Value = serde_json::json!({
            "ordId": "312269865356374016", "state": "filled",
            "accFillSz": "2", "avgPx": "31500", "fee": "-0.01", "feeCcy": "USDT"
        });
        let o = parse_order(&v, "BTC", "USDT").unwrap();
        assert_eq!(o.fee, 0.01);
        assert_eq!(o.fee_base, 0.0);
        assert_eq!(o.avg_price, Some(31500.0));
        assert_eq!(o.status, BrokerOrderStatus::Filled);
    }

    /// OKX's own example for Get order details: a spot market buy on
    /// BTC-USDT whose fee is charged in BTC.
    #[test]
    fn the_documented_spot_buy_pays_its_fee_in_btc() {
        let v: Value = serde_json::json!({
            "accFillSz": "0.00192834", "avgPx": "51858", "fee": "-0.00000192834", "feeCcy": "BTC",
            "instId": "BTC-USDT", "instType": "SPOT", "ordId": "680800019749904384", "ordType": "market",
            "rebate": "0", "rebateCcy": "USDT", "side": "buy", "state": "filled", "clOrdId": ""
        });
        let o = parse_order(&v, "BTC", "USDT").unwrap();
        assert_eq!(o.filled_qty, 0.00192834);
        assert!((o.fee_base - 0.00000192834).abs() < 1e-18, "the coins OKX kept: {}", o.fee_base);
        assert!((o.fee - 0.00000192834 * 51858.0).abs() < 1e-9, "valued at the fill: {}", o.fee);
        assert!(o.fee > 0.09, "about ten cents, not a millionth of a dollar");
    }

    #[test]
    fn a_net_rebate_is_not_booked_as_income() {
        let v: Value = serde_json::json!({
            "ordId": "9", "state": "filled", "accFillSz": "1", "avgPx": "100", "fee": "0.02", "feeCcy": "USDT"
        });
        let o = parse_order(&v, "SOL", "USDT").unwrap();
        assert_eq!((o.fee, o.fee_base), (0.0, 0.0));
    }

    #[test]
    fn a_live_order_has_no_average_price() {
        let v: Value = serde_json::json!({"ordId": "1", "state": "live", "accFillSz": "0", "avgPx": ""});
        let o = parse_order(&v, "BTC", "USDT").unwrap();
        assert_eq!(o.avg_price, None);
        assert!(!o.status.is_terminal());
    }

    #[test]
    fn demo_sends_the_simulated_trading_header_and_live_says_it_is_not() {
        use super::super::{Environment, Exchange};
        let live = CexConnector::new(Exchange::Okx, "k".into(), "s".into(), "p".into());
        let demo = CexConnector::with_env(Exchange::Okx, "k".into(), "s".into(), "p".into(), Environment::Demo);
        assert_eq!(simulated_header(&live), ("x-simulated-trading", "0"));
        assert_eq!(simulated_header(&demo), ("x-simulated-trading", "1"));
        // Same host for both worlds: the header and the key pick the world.
        assert_eq!(live.base(BASE), demo.base(BASE));
        // A key from the other world is an auth problem, not a rejected order.
        let v = serde_json::json!({"code": "50101", "msg": "APIKey does not match current environment."});
        assert!(check_error(&v, "/x").is_err_and(|e| matches!(e, ConnectorError::Auth(_))));
    }

    #[test]
    fn the_timestamp_is_iso8601_with_milliseconds() {
        let ts = iso_timestamp();
        assert!(ts.ends_with('Z') && ts.contains('T') && ts.contains('.'), "{ts}");
        assert_eq!(ts.len(), 24, "yyyy-MM-ddTHH:mm:ss.sssZ — {ts}");
    }
}
