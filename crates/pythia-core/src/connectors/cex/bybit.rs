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
use super::{is_fiat, normalize_asset, CexConnector, FeeSplit};
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

/// The fee legs of one Bybit order, by currency.
///
/// Bybit's order list (<https://bybit-exchange.github.io/docs/v5/order/order-list>)
/// marks `cumExecFee` as deprecated for spot ("Use `cumFeeDetail` instead");
/// `cumFeeDetail` maps each fee currency to the cumulative amount, for example
/// `{"BTC": "0.0000015"}`. The currency follows Bybit's spot fee currency
/// rule (<https://bybit-exchange.github.io/docs/v5/enum#spot-fee-currency-instruction>):
/// with a positive maker fee rate a buy pays in the base coin and a sell in
/// the quote coin, and a taker always does. When an older answer has only
/// `cumExecFee`, that rule decides its currency, using `feeCurrency` if the
/// answer names one.
fn fee_legs(v: &Value, base: &str, quote: &str) -> Vec<(String, f64)> {
    if let Some(detail) = v.get("cumFeeDetail").and_then(Value::as_object).filter(|d| !d.is_empty()) {
        return detail.iter().map(|(ccy, amt)| (ccy.clone(), num_or0(Some(amt)))).collect();
    }
    let fee = num_or0(v.get("cumExecFee"));
    if fee == 0.0 {
        return Vec::new();
    }
    let named = v.get("feeCurrency").and_then(Value::as_str).filter(|s| !s.is_empty());
    let ccy = match (named, v.get("side").and_then(Value::as_str)) {
        (Some(c), _) => c.to_string(),
        (None, Some("Buy")) => base.to_string(),
        _ => quote.to_string(),
    };
    vec![(ccy, fee)]
}

fn parse_order(v: &Value, base: &str, quote: &str) -> Result<BrokerOrder, ConnectorError> {
    let id = v
        .get("orderId")
        .and_then(Value::as_str)
        .ok_or_else(|| ConnectorError::Network("Bybit order response has no orderId".into()))?
        .to_string();
    let raw = v.get("orderStatus").and_then(Value::as_str).unwrap_or("New").to_string();
    let filled = num_or0(v.get("cumExecQty"));
    let value = num_or0(v.get("cumExecValue"));
    let mut order = BrokerOrder {
        id,
        client_order_id: v.get("orderLinkId").and_then(Value::as_str).filter(|s| !s.is_empty()).map(str::to_string),
        status: map_status(&raw),
        filled_qty: filled,
        avg_price: (filled > 0.0 && value > 0.0).then(|| value / filled),
        fee: 0.0,
        fee_base: 0.0,
        fee_unpriced: Vec::new(),
        raw_status: raw,
    };
    FeeSplit::fold(fee_legs(v, base, quote), base, quote).apply(&mut order);
    Ok(order)
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
        body["orderLinkId"] = serde_json::json!(link_id(cid));
    }

    let result = post(c, "/v5/order/create", &body).await?;
    let id = result
        .get("orderId")
        .and_then(Value::as_str)
        .ok_or_else(|| ConnectorError::Rejected("Bybit accepted the order but returned no orderId".into()))?;
    Ok(BrokerOrder::acknowledged(id, req.client_order_id))
}

/// The `orderLinkId` an engine client id is sent as: capped at 36 chars.
fn link_id(cid: &str) -> String {
    cid.chars().take(36).collect()
}

/// One order by `orderId` or `orderLinkId`, or `None` when Bybit has no
/// such order. `realtime` only keeps open orders; once terminal the order
/// moves to history, so a miss there is a look-up in `/v5/order/history`.
async fn find(c: &CexConnector, key: (&'static str, String), symbol: &str, base: &str, quote: &str) -> Result<Option<BrokerOrder>, ConnectorError> {
    let params = [("category", "spot".to_string()), ("symbol", symbol.to_string()), key];
    let live = get(c, "/v5/order/realtime", &params).await?;
    if let Some(o) = live.get("list").and_then(Value::as_array).and_then(|a| a.first()) {
        return parse_order(o, base, quote).map(Some);
    }
    let hist = get(c, "/v5/order/history", &params).await?;
    match hist.get("list").and_then(Value::as_array).and_then(|a| a.first()) {
        Some(o) => parse_order(o, base, quote).map(Some),
        None => Ok(None),
    }
}

pub(super) async fn status(
    c: &CexConnector,
    order_id: &str,
    symbol: &str,
    base: &str,
    quote: &str,
) -> Result<BrokerOrder, ConnectorError> {
    find(c, ("orderId", order_id.to_string()), symbol, base, quote)
        .await?
        .ok_or_else(|| ConnectorError::Rejected(format!("Bybit has no order {order_id}")))
}

/// Look an order up by the client id it was sent under: `orderLinkId` is a
/// query parameter of both order lists
/// (<https://bybit-exchange.github.io/docs/v5/order/order-list>).
pub(super) async fn by_client_id(
    c: &CexConnector,
    cid: &str,
    symbol: &str,
    base: &str,
    quote: &str,
) -> Result<Option<BrokerOrder>, ConnectorError> {
    find(c, ("orderLinkId", link_id(cid)), symbol, base, quote).await
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
        let o = parse_order(&v, "BTC", "USDT").unwrap();
        assert_eq!(o.status, BrokerOrderStatus::Canceled);
        assert!(o.status.is_terminal());
        assert_eq!(o.filled_qty, 0.25, "the 0.25 that did fill is a real position");
        assert_eq!(o.avg_price, Some(32000.0));
        assert_eq!(o.fee, 8.0);
        assert_eq!(o.fee_base, 0.0);
    }

    /// A filled spot market buy as `/v5/order/history` returns it: the fee is
    /// in `cumFeeDetail`, in BTC, and `cumExecFee` is the deprecated echo.
    /// Shape from <https://bybit-exchange.github.io/docs/v5/order/order-list>.
    #[test]
    fn a_spot_buy_fee_taken_in_the_coin_is_valued_at_the_fill_and_kept_as_coins() {
        let v: Value = serde_json::json!({
            "orderId": "1854", "orderLinkId": "pythia-a-1", "symbol": "BTCUSDT", "side": "Buy",
            "orderType": "Market", "orderStatus": "Filled",
            "cumExecQty": "0.010000", "cumExecValue": "600.00", "avgPrice": "60000",
            "cumExecFee": "0.00001", "cumFeeDetail": {"BTC": "0.00001"}
        });
        let o = parse_order(&v, "BTC", "USDT").unwrap();
        assert_eq!(o.filled_qty, 0.01, "the venue filled 0.01");
        assert!((o.fee_base - 0.00001).abs() < 1e-15, "and kept 0.00001 BTC as the fee");
        assert!((o.fee - 0.6).abs() < 1e-9, "worth $0.60 at the fill price, not $0.00001: {}", o.fee);
        assert!(o.fee_unpriced.is_empty());
    }

    #[test]
    fn a_spot_sell_fee_in_usdt_is_money_and_takes_no_coins() {
        let v: Value = serde_json::json!({
            "orderId": "1855", "side": "Sell", "orderStatus": "Filled",
            "cumExecQty": "0.01", "cumExecValue": "600", "cumFeeDetail": {"USDT": "0.6"}
        });
        let o = parse_order(&v, "BTC", "USDT").unwrap();
        assert_eq!((o.fee, o.fee_base), (0.6, 0.0));
    }

    #[test]
    fn without_fee_detail_the_documented_spot_rule_decides_the_currency() {
        // An answer with only the deprecated field: a buy paid in the coin.
        let buy: Value = serde_json::json!({
            "orderId": "1", "side": "Buy", "orderStatus": "Filled",
            "cumExecQty": "2", "cumExecValue": "200", "cumExecFee": "0.002"
        });
        let o = parse_order(&buy, "SOL", "USDT").unwrap();
        assert_eq!(o.fee_base, 0.002);
        assert!((o.fee - 0.2).abs() < 1e-12);
        // A named feeCurrency wins over the rule.
        let named: Value = serde_json::json!({
            "orderId": "2", "side": "Buy", "orderStatus": "Filled",
            "cumExecQty": "2", "cumExecValue": "200", "cumExecFee": "0.2", "feeCurrency": "USDT"
        });
        let o = parse_order(&named, "SOL", "USDT").unwrap();
        assert_eq!((o.fee, o.fee_base), (0.2, 0.0));
    }

    #[test]
    fn a_client_id_is_looked_up_under_the_order_link_id_it_was_sent_as() {
        assert_eq!(link_id("pythia-a1b2-ord_17"), "pythia-a1b2-ord_17");
        let long = "x".repeat(50);
        assert_eq!(link_id(&long).len(), 36, "capped like the submission");
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
