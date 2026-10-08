//! Binance spot (`https://api.binance.com`).
//!
//! Demo: Spot Demo Mode at `https://demo-api.binance.com`, same paths and
//! signing, keys from Binance Demo Trading
//! (<https://developers.binance.com/en/docs/products/spot/demo-mode/general-info>).
//! Not the Spot Testnet (`testnet.binance.vision`), whose prices and books are
//! independent of the live exchange.
//!
//! Signed REST: every private call carries `timestamp`, and the signature is a
//! hex HMAC-SHA256 over the *exact* query string that is sent. Building the
//! string once and appending `&signature=` to it is the only way to guarantee
//! the two match — re-serialising a map here is how signature errors happen.
//!
//! Market **buy** orders take `quantity` in the base asset, which is what we
//! want; Binance's alternative `quoteOrderQty` is deliberately not used.

use super::super::{
    num, num_or0, sign, Balance, BrokerOrder, BrokerOrderStatus, ConnectorError, OrderRequest,
    OrderType,
};
use super::{is_fiat, normalize_asset, CexConnector, FeeSplit};
use serde_json::Value;

const BASE: &str = "https://api.binance.com";
/// How much clock skew Binance tolerates between our timestamp and its own.
const RECV_WINDOW_MS: i64 = 10_000;

/// Sign `params` and issue the request. Returns the parsed body.
async fn signed(
    c: &CexConnector,
    method: reqwest::Method,
    path: &str,
    params: &[(&str, String)],
) -> Result<Value, ConnectorError> {
    let mut all: Vec<(&str, String)> = params.to_vec();
    all.push(("recvWindow", RECV_WINDOW_MS.to_string()));
    all.push(("timestamp", sign::epoch_ms().to_string()));

    let query = sign::form_encode(&all);
    let signature = sign::hmac_sha256_hex(c.secret.trim(), &query);
    let url = format!("{}{path}?{query}&signature={signature}", c.base(BASE));

    let rb = c.http.request(method, url).header("X-MBX-APIKEY", c.key.trim());
    let v = c.send(rb, path).await?;
    check_error(&v, path)?;
    Ok(v)
}

/// Binance signals most failures with a non-2xx status, but `code`/`msg` can
/// also ride along in a 200 body — check both.
fn check_error(v: &Value, what: &str) -> Result<(), ConnectorError> {
    let Some(code) = v.get("code").and_then(Value::as_i64) else { return Ok(()) };
    if code >= 0 {
        return Ok(());
    }
    let msg = v.get("msg").and_then(Value::as_str).unwrap_or("unknown error");
    Err(match code {
        // -1022 bad signature, -2014/-2015 bad API key or permissions.
        -1022 | -2014 | -2015 => ConnectorError::Auth(format!("Binance: {msg}")),
        _ => ConnectorError::Rejected(format!("Binance {what}: {msg} ({code})")),
    })
}

fn map_status(s: &str) -> BrokerOrderStatus {
    match s {
        "FILLED" => BrokerOrderStatus::Filled,
        "PARTIALLY_FILLED" => BrokerOrderStatus::PartiallyFilled,
        "CANCELED" | "PENDING_CANCEL" => BrokerOrderStatus::Canceled,
        "REJECTED" => BrokerOrderStatus::Rejected,
        "EXPIRED" | "EXPIRED_IN_MATCH" => BrokerOrderStatus::Expired,
        _ => BrokerOrderStatus::Working, // NEW and anything unfamiliar
    }
}

/// Binance reports cumulative filled base qty and cumulative quote spend; the
/// average price is the ratio (it never sends an average directly).
///
/// The order itself carries no fee. Commission is per trade, as `commission`
/// plus `commissionAsset`: in the `fills` of a FULL new-order response
/// (market and limit orders default to FULL,
/// <https://developers.binance.com/docs/binance-spot-api-docs/rest-api/trading-endpoints>)
/// and in `GET /api/v3/myTrades`
/// (<https://developers.binance.com/docs/binance-spot-api-docs/rest-api/account-endpoints>).
/// Binance charges it in the asset received (the coin on a buy) unless the
/// account pays with BNB, so `commissionAsset` decides what it is.
fn parse_order(v: &Value, trades: Option<&Value>, base: &str, quote_asset: &str) -> Result<BrokerOrder, ConnectorError> {
    let id = num(v.get("orderId"))
        .map(|n| format!("{n:.0}"))
        .ok_or_else(|| ConnectorError::Network("Binance order response has no orderId".into()))?;
    let raw = v.get("status").and_then(Value::as_str).unwrap_or("NEW").to_string();
    let filled = num_or0(v.get("executedQty"));
    let quote = num_or0(v.get("cummulativeQuoteQty"));
    let mut order = BrokerOrder {
        id,
        client_order_id: v.get("clientOrderId").and_then(Value::as_str).map(str::to_string),
        status: map_status(&raw),
        filled_qty: filled,
        avg_price: (filled > 0.0 && quote > 0.0).then(|| quote / filled),
        fee: 0.0,
        fee_base: 0.0,
        fee_unpriced: Vec::new(),
        raw_status: raw,
    };
    let legs: Vec<(String, f64)> = trades
        .or_else(|| v.get("fills"))
        .and_then(Value::as_array)
        .map(|a| {
            a.iter()
                .filter_map(|t| {
                    let asset = t.get("commissionAsset").and_then(Value::as_str)?;
                    Some((asset.to_string(), num_or0(t.get("commission"))))
                })
                .collect()
        })
        .unwrap_or_default();
    FeeSplit::fold(legs, base, quote_asset).apply(&mut order);
    Ok(order)
}

pub(super) async fn submit(c: &CexConnector, req: OrderRequest) -> Result<BrokerOrder, ConnectorError> {
    let symbol = c.exchange.symbol(&req.symbol);
    let mut params: Vec<(&str, String)> = vec![
        ("symbol", symbol),
        ("side", req.side.as_str().to_uppercase()),
        ("type", if req.order_type == OrderType::Limit { "LIMIT".into() } else { "MARKET".into() }),
        ("quantity", sign::trim_decimals(req.qty, 8)),
    ];
    if let (OrderType::Limit, Some(p)) = (req.order_type, req.limit_price) {
        params.push(("timeInForce", "GTC".into()));
        params.push(("price", sign::trim_decimals(p, 8)));
    }
    if let Some(cid) = &req.client_order_id {
        params.push(("newClientOrderId", cid.clone()));
    }
    let v = signed(c, reqwest::Method::POST, "/api/v3/order", &params).await?;
    let (base, quote) = c.exchange.assets(&req.symbol);
    parse_order(&v, None, &base, &quote)
}

pub(super) async fn status(
    c: &CexConnector,
    order_id: &str,
    symbol: &str,
    base: &str,
    quote: &str,
) -> Result<BrokerOrder, ConnectorError> {
    let v = signed(
        c,
        reqwest::Method::GET,
        "/api/v3/order",
        &[("symbol", symbol.to_string()), ("orderId", order_id.to_string())],
    )
    .await?;
    // The order has no fee field; its trades do. Without them a buy would
    // book coins Binance kept as commission, so a failed read is retried
    // (the error goes back to the poll) rather than booked without fees.
    let trades = if num_or0(v.get("executedQty")) > 0.0 {
        Some(
            signed(
                c,
                reqwest::Method::GET,
                "/api/v3/myTrades",
                &[("symbol", symbol.to_string()), ("orderId", order_id.to_string())],
            )
            .await?,
        )
    } else {
        None
    };
    parse_order(&v, trades.as_ref(), base, quote)
}

pub(super) async fn cancel(c: &CexConnector, order_id: &str, symbol: &str) -> Result<(), ConnectorError> {
    match signed(
        c,
        reqwest::Method::DELETE,
        "/api/v3/order",
        &[("symbol", symbol.to_string()), ("orderId", order_id.to_string())],
    )
    .await
    {
        Ok(_) => Ok(()),
        // -2011 "Unknown order sent" — it is already gone, which is the goal.
        Err(ConnectorError::Rejected(m)) if m.contains("-2011") || m.contains("Unknown order") => Ok(()),
        Err(e) => Err(e),
    }
}

pub(super) async fn balances(c: &CexConnector) -> Result<Vec<Balance>, ConnectorError> {
    let v = signed(c, reqwest::Method::GET, "/api/v3/account", &[]).await?;
    let Some(arr) = v.get("balances").and_then(Value::as_array) else { return Ok(vec![]) };
    let mut out = Vec::new();
    for b in arr {
        let free = num_or0(b.get("free"));
        let locked = num_or0(b.get("locked"));
        let total = free + locked;
        if total <= 0.0 {
            continue;
        }
        let Some(asset) = b.get("asset").and_then(Value::as_str).map(normalize_asset) else { continue };
        let usd = is_fiat(&asset).then_some(total);
        out.push(Balance { asset, free, total, usd_value: usd });
    }
    out.sort_by(|a, b| a.asset.cmp(&b.asset));
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn negative_codes_are_errors_and_signature_problems_are_auth() {
        assert!(check_error(&serde_json::json!({"code": -1022, "msg": "Signature invalid"}), "/order")
            .is_err_and(|e| matches!(e, ConnectorError::Auth(_))));
        assert!(check_error(&serde_json::json!({"code": -2010, "msg": "insufficient balance"}), "/order")
            .is_err_and(|e| matches!(e, ConnectorError::Rejected(_))));
        // A successful order body has no `code` at all.
        assert!(check_error(&serde_json::json!({"orderId": 1, "status": "FILLED"}), "/order").is_ok());
        // Some endpoints legitimately return code: 200.
        assert!(check_error(&serde_json::json!({"code": 200}), "/order").is_ok());
    }

    #[test]
    fn average_price_comes_from_the_quote_over_base_ratio() {
        let v: Value = serde_json::json!({
            "orderId": 28457, "clientOrderId": "pythia-3", "status": "FILLED",
            "executedQty": "0.50000000", "cummulativeQuoteQty": "16000.00000000"
        });
        let o = parse_order(&v, None, "BTC", "USDT").unwrap();
        assert_eq!(o.id, "28457", "the numeric id must not become 28457.0 or 2.8e4");
        assert_eq!(o.status, BrokerOrderStatus::Filled);
        assert_eq!(o.filled_qty, 0.5);
        assert_eq!(o.avg_price, Some(32000.0));
    }

    /// A FULL new-order response for a market buy: two fills, commission in
    /// the coin bought.
    #[test]
    fn a_market_buy_pays_commission_in_the_coin_it_bought() {
        let v: Value = serde_json::json!({
            "symbol": "BTCUSDT", "orderId": 28, "clientOrderId": "pythia-x-1", "status": "FILLED",
            "executedQty": "0.02000000", "cummulativeQuoteQty": "1200.00000000", "side": "BUY", "type": "MARKET",
            "fills": [
                {"price": "60000.00", "qty": "0.01500000", "commission": "0.00001500", "commissionAsset": "BTC"},
                {"price": "60000.00", "qty": "0.00500000", "commission": "0.00000500", "commissionAsset": "BTC"}
            ]
        });
        let o = parse_order(&v, None, "BTC", "USDT").unwrap();
        assert!((o.fee_base - 0.00002).abs() < 1e-15, "{}", o.fee_base);
        assert!((o.fee - 1.2).abs() < 1e-9, "0.00002 BTC at $60,000: {}", o.fee);
    }

    /// `GET /api/v3/myTrades` for a status poll: a sell paid in USDT and a
    /// trade paid in BNB, which this connector cannot price.
    #[test]
    fn trades_fold_quote_and_bnb_commission_apart() {
        let order: Value = serde_json::json!({
            "orderId": 7, "status": "FILLED", "executedQty": "2", "cummulativeQuoteQty": "300"
        });
        let trades: Value = serde_json::json!([
            {"orderId": 7, "price": "150", "qty": "1", "commission": "0.15", "commissionAsset": "USDT", "isBuyer": false},
            {"orderId": 7, "price": "150", "qty": "1", "commission": "0.0002", "commissionAsset": "BNB", "isBuyer": false}
        ]);
        let o = parse_order(&order, Some(&trades), "SOL", "USDT").unwrap();
        assert_eq!((o.fee, o.fee_base), (0.15, 0.0));
        assert_eq!(o.fee_unpriced, vec![("BNB".to_string(), 0.0002)]);
    }

    #[test]
    fn an_unfilled_order_has_no_average_price() {
        let v: Value = serde_json::json!({
            "orderId": 1, "status": "NEW", "executedQty": "0", "cummulativeQuoteQty": "0"
        });
        let o = parse_order(&v, None, "BTC", "USDT").unwrap();
        assert_eq!(o.avg_price, None, "0/0 must not become NaN");
        assert!(!o.status.is_terminal());
    }

    #[test]
    fn statuses_map_and_unknown_stays_working() {
        assert_eq!(map_status("PARTIALLY_FILLED"), BrokerOrderStatus::PartiallyFilled);
        assert_eq!(map_status("EXPIRED_IN_MATCH"), BrokerOrderStatus::Expired);
        assert!(!map_status("SOMETHING_NEW").is_terminal());
    }
}
