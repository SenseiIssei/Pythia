//! Coinbase Advanced Trade spot (`https://api.coinbase.com/api/v3/brokerage`).
//!
//! The one venue in the registry that does not HMAC. A CDP API key is a key
//! *pair*: a name (`organizations/{org_id}/apiKeys/{key_id}`) and an EC P-256
//! private key in PEM. Every private request carries a fresh ES256 JWT that
//! names the exact method, host and path it is valid for and expires after two
//! minutes; see [`sign::cdp_jwt`] for the format and the doc it follows.
//!
//! In [`CexConnector`] terms: `key` holds the key name, `secret` the PEM. There
//! is no passphrase.
//!
//! Endpoints used, from Coinbase's Advanced Trade REST reference
//! (<https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/rest-api>):
//!
//! | call | endpoint | key scope |
//! |---|---|---|
//! | balances | `GET /accounts` (paged by `cursor`) | view |
//! | submit | `POST /orders` | trade |
//! | status | `GET /orders/historical/{order_id}` | view |
//! | cancel | `POST /orders/batch_cancel` | trade |
//! | fee tier | `GET /transaction_summary` | view |
//! | lot rules | `GET /market/products/{product_id}` | public, no key |
//!
//! Two Coinbase habits shape the code:
//!
//! 1. A refused order is an HTTP **200** with `success: false` and the reason in
//!    `error_response`, so the body is checked even when the status is fine.
//! 2. Sizes must be exact multiples of the product's `base_increment`, prices
//!    of its `price_increment`, or the order is refused outright. The public
//!    product endpoint publishes both, plus the minimum size, so they are
//!    fetched (and cached per process) instead of guessed.
//!
//! Market orders are sized with `base_size` on both sides, so a market buy
//! spends what the strategy asked for in coins, not in dollars.

use super::super::{
    num, num_or0, sign, Balance, BrokerOrder, BrokerOrderStatus, ConnectorError, OrderRequest, OrderType, Side,
};
use super::{is_fiat, normalize_asset, CexConnector};
use serde_json::Value;
use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

const HOST: &str = "api.coinbase.com";
const PREFIX: &str = "/api/v3/brokerage";
/// Accounts per page; Coinbase's maximum.
const PAGE: usize = 250;
/// A hard stop on paging, so a misbehaving cursor cannot loop forever.
const MAX_PAGES: usize = 20;
/// Lot rules barely ever change; refetching them hourly is plenty.
const RULES_TTL: Duration = Duration::from_secs(3600);

fn url(path_and_query: &str) -> String {
    format!("https://{HOST}{path_and_query}")
}

/// `Authorization` value for one request. Building the JWT also parses the
/// key, so a malformed PEM surfaces here as an auth error that says what is
/// wrong with it (and never what is in it).
fn bearer(c: &CexConnector, method: &reqwest::Method, path: &str) -> Result<String, ConnectorError> {
    let nonce = uuid::Uuid::new_v4().simple().to_string(); // 32 random hex chars
    let now = chrono::Utc::now().timestamp();
    sign::cdp_jwt(&c.key, &c.secret, method.as_str(), HOST, path, now, &nonce)
        .map(|jwt| format!("Bearer {jwt}"))
        .map_err(|e| ConnectorError::Auth(format!("Coinbase: {e}")))
}

/// Issue one signed request. `path` is under [`PREFIX`]; `query` (without the
/// `?`) is sent but, per Coinbase's spec, not part of the signed `uri`.
async fn private(
    c: &CexConnector,
    method: reqwest::Method,
    path: &str,
    query: &str,
    body: Option<&Value>,
) -> Result<Value, ConnectorError> {
    let full = format!("{PREFIX}{path}");
    let auth = bearer(c, &method, &full)?;
    let target = if query.is_empty() { url(&full) } else { url(&format!("{full}?{query}")) };
    let mut rb = c.http.request(method, target).header("Authorization", auth);
    if let Some(b) = body {
        rb = rb.header("content-type", "application/json").body(b.to_string());
    }
    let v = c.send(rb, path).await?;
    check_error(&v, path)?;
    Ok(v)
}

/// Classify one Coinbase error code. Credential problems are `Auth` so the UI
/// says "fix your key"; rate limits are transient; everything else is the
/// venue refusing this particular request.
fn classify(code: &str, msg: String) -> ConnectorError {
    let up = code.to_ascii_uppercase();
    if up.contains("UNAUTHENTICATED")
        || up.contains("PERMISSION_DENIED")
        || up.contains("INVALID_API_KEY")
        || up.contains("UNAUTHORIZED")
    {
        ConnectorError::Auth(msg)
    } else if up.contains("RATE_LIMIT") || up == "UNAVAILABLE" || up == "INTERNAL" {
        ConnectorError::Network(msg)
    } else {
        ConnectorError::Rejected(msg)
    }
}

/// Coinbase reports failure in two shapes: a top-level `error` + `message`
/// (validation, permissions), and on order creation `success: false` with the
/// reason one level down in `error_response`.
fn check_error(v: &Value, what: &str) -> Result<(), ConnectorError> {
    if v.get("success").and_then(Value::as_bool) == Some(false) {
        let er = v.get("error_response").cloned().unwrap_or(Value::Null);
        let code = ["new_order_failure_reason", "preview_failure_reason", "error"]
            .iter()
            .filter_map(|k| er.get(*k).and_then(Value::as_str))
            .find(|s| !s.is_empty() && !s.starts_with("UNKNOWN_"))
            .or_else(|| er.get("error").and_then(Value::as_str))
            .or_else(|| v.get("failure_reason").and_then(Value::as_str))
            .unwrap_or("UNKNOWN_FAILURE_REASON")
            .to_string();
        let detail = ["error_details", "message"]
            .iter()
            .filter_map(|k| er.get(*k).and_then(Value::as_str))
            .find(|s| !s.is_empty())
            .unwrap_or("no details");
        return Err(classify(&code, format!("Coinbase {what}: {detail} ({code})")));
    }
    if let Some(code) = v.get("error").and_then(Value::as_str).filter(|s| !s.is_empty()) {
        let msg = v.get("message").and_then(Value::as_str).unwrap_or("");
        return Err(classify(code, format!("Coinbase {what}: {msg} ({code})")));
    }
    Ok(())
}

fn map_status(s: &str) -> BrokerOrderStatus {
    match s {
        "FILLED" => BrokerOrderStatus::Filled,
        "CANCELLED" => BrokerOrderStatus::Canceled,
        "EXPIRED" => BrokerOrderStatus::Expired,
        "FAILED" => BrokerOrderStatus::Rejected,
        // PENDING, OPEN, QUEUED, CANCEL_QUEUED, EDIT_QUEUED,
        // UNKNOWN_ORDER_STATUS and anything new: not over yet.
        _ => BrokerOrderStatus::Working,
    }
}

/// Parse the `order` object of `GET /orders/historical/{id}`. Sizes are
/// cumulative, fees are in quote currency, and `average_filled_price` is "0"
/// until something fills.
fn parse_order(o: &Value) -> Result<BrokerOrder, ConnectorError> {
    let id = o
        .get("order_id")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| ConnectorError::Network("Coinbase order response has no order_id".into()))?
        .to_string();
    let raw = o.get("status").and_then(Value::as_str).unwrap_or("UNKNOWN_ORDER_STATUS").to_string();
    let filled = num_or0(o.get("filled_size"));
    let mut status = map_status(&raw);
    // Coinbase has no partial status: a resting order with fills is still OPEN.
    if status == BrokerOrderStatus::Working && filled > 0.0 {
        status = BrokerOrderStatus::PartiallyFilled;
    }
    let avg = num(o.get("average_filled_price")).filter(|p| *p > 0.0).or_else(|| {
        // Fall back to value / size when the average is blank.
        let value = num_or0(o.get("filled_value"));
        (filled > 0.0 && value > 0.0).then(|| value / filled)
    });
    Ok(BrokerOrder {
        id,
        client_order_id: o
            .get("client_order_id")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
            .map(str::to_string),
        status,
        filled_qty: filled,
        avg_price: avg,
        // Coinbase charges in the quote currency on both sides: its Get Order
        // reference defines `total_value_after_fees` as "filled_value +
        // total_fees for buy orders and filled_value - total_fees for sell
        // orders", both in quote (`filled_value` is "in quote currency").
        // <https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/get-order>
        // So the coins bought are the full `filled_size`, and nothing is
        // taken from them.
        fee: num_or0(o.get("total_fees")).abs(),
        fee_base: 0.0,
        fee_unpriced: Vec::new(),
        raw_status: raw,
    })
}

// ── lot rules from the public product endpoint ─────────────────────────────

/// What Coinbase accepts on one product. All sizes in base units, prices and
/// `quote_min` in quote units.
#[derive(Debug, Clone, PartialEq)]
pub(crate) struct ProductRules {
    pub base_increment: String,
    pub price_increment: String,
    pub base_min: f64,
    pub base_max: f64,
    pub quote_min: f64,
    /// Not accepting orders at all (delisted, halted, cancel-only).
    pub halted: bool,
    pub limit_only: bool,
    pub post_only: bool,
}

fn parse_rules(v: &Value) -> Option<ProductRules> {
    let s = |k: &str| v.get(k).and_then(Value::as_str).filter(|s| !s.is_empty()).map(str::to_string);
    let b = |k: &str| v.get(k).and_then(Value::as_bool).unwrap_or(false);
    let base_increment = s("base_increment")?;
    let price_increment = s("price_increment").or_else(|| s("quote_increment"))?;
    let status_offline = s("status").is_some_and(|st| !st.eq_ignore_ascii_case("online"));
    Some(ProductRules {
        base_increment,
        price_increment,
        base_min: num_or0(v.get("base_min_size")),
        base_max: num(v.get("base_max_size")).filter(|m| *m > 0.0).unwrap_or(f64::INFINITY),
        quote_min: num_or0(v.get("quote_min_size")),
        halted: b("trading_disabled") || b("is_disabled") || b("cancel_only") || status_offline,
        limit_only: b("limit_only"),
        post_only: b("post_only"),
    })
}

/// Decimal places of an increment as Coinbase writes it ("0.00000001" -> 8).
fn decimals(increment: &str) -> usize {
    increment
        .split_once('.')
        .map(|(_, frac)| frac.trim_end_matches('0').len())
        .unwrap_or(0)
}

/// Round `v` onto the increment grid, down or up, as the exact decimal string
/// Coinbase wants. Works in integer steps so 0.1 + 0.2 never leaks in.
fn snap(v: f64, increment: &str, up: bool) -> String {
    let inc: f64 = increment.parse().unwrap_or(0.0);
    let dp = decimals(increment);
    if inc <= 0.0 || !v.is_finite() {
        return sign::trim_decimals(v, 8);
    }
    let steps = v / inc;
    // Tolerate float noise: 0.3 / 0.1 is 2.9999999999999996, which is 3 steps.
    let steps = if up { (steps - 1e-9).ceil() } else { (steps + 1e-9).floor() };
    sign::trim_decimals(steps.max(0.0) * inc, dp.max(1))
}

fn rules_cache() -> &'static Mutex<HashMap<String, (Instant, ProductRules)>> {
    static CACHE: OnceLock<Mutex<HashMap<String, (Instant, ProductRules)>>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Lot rules for one product, from the cache or the public endpoint. No key
/// is sent: this is public market data.
async fn rules(c: &CexConnector, product: &str) -> Result<ProductRules, ConnectorError> {
    if let Some((at, r)) = rules_cache().lock().unwrap().get(product) {
        if at.elapsed() < RULES_TTL {
            return Ok(r.clone());
        }
    }
    let path = format!("{PREFIX}/market/products/{}", sign::urlencode(product));
    let v = c.send(c.http.get(url(&path)), "/market/products").await?;
    check_error(&v, "/market/products")?;
    let r = parse_rules(&v)
        .ok_or_else(|| ConnectorError::Network(format!("Coinbase product {product} has no lot rules")))?;
    rules_cache().lock().unwrap().insert(product.to_string(), (Instant::now(), r.clone()));
    Ok(r)
}

/// Why Coinbase would refuse this order outright, judged from its lot rules.
/// `qty` is snapped down to the increment first: that is the size we send.
fn rules_block(r: &ProductRules, product: &str, req: &OrderRequest) -> Option<String> {
    if r.halted {
        return Some(format!("{product} is not accepting new orders on Coinbase right now"));
    }
    if req.order_type == OrderType::Market && (r.limit_only || r.post_only) {
        return Some(format!("{product} is limit-only on Coinbase right now; a market order would be refused"));
    }
    let qty: f64 = snap(req.qty, &r.base_increment, false).parse().unwrap_or(0.0);
    if qty <= 0.0 || qty + 1e-12 < r.base_min {
        return Some(format!(
            "{:.8} on {product} is below Coinbase's minimum size of {} (step {})",
            req.qty, r.base_min, r.base_increment
        ));
    }
    if qty > r.base_max {
        return Some(format!("{qty} on {product} is above Coinbase's maximum size of {}", r.base_max));
    }
    if let Some(price) = req.limit_price.or(req.ref_price) {
        let notional = qty * price;
        if r.quote_min > 0.0 && notional + 1e-9 < r.quote_min {
            return Some(format!(
                "${notional:.2} on {product} is below Coinbase's minimum order value of ${}",
                r.quote_min
            ));
        }
    }
    None
}

pub(super) async fn preflight(c: &CexConnector, req: &OrderRequest) -> Result<(), ConnectorError> {
    let product = c.exchange.symbol(&req.symbol);
    match rules(c, &product).await {
        Ok(r) => match rules_block(&r, &product, req) {
            Some(why) => Err(ConnectorError::Preflight(why)),
            None => Ok(()),
        },
        // Lot rules are a courtesy check. If the public endpoint is down the
        // order itself will tell us, so do not block on it.
        Err(e) if e.is_transient() => Ok(()),
        Err(e) => Err(e),
    }
}

/// The `POST /orders` body. Sizes and prices are snapped onto the product's
/// grid when its rules are known: a buy limit rounds its price down and a sell
/// limit rounds up, so snapping never makes an order more aggressive.
fn order_body(req: &OrderRequest, product: &str, client_order_id: &str, rules: Option<&ProductRules>) -> Value {
    let base_size = match rules {
        Some(r) => snap(req.qty, &r.base_increment, false),
        None => sign::trim_decimals(req.qty, 8),
    };
    let config = match (req.order_type, req.limit_price) {
        (OrderType::Limit, Some(p)) => {
            let price = match rules {
                Some(r) => snap(p, &r.price_increment, req.side == Side::Sell),
                None => sign::trim_decimals(p, 8),
            };
            serde_json::json!({ "limit_limit_gtc": {
                "base_size": base_size,
                "limit_price": price,
                "post_only": false,
            }})
        }
        // A limit order without a price is not one; send it as market, which
        // is what every other adapter does with the same input.
        _ => serde_json::json!({ "market_market_ioc": { "base_size": base_size } }),
    };
    serde_json::json!({
        "client_order_id": client_order_id,
        "product_id": product,
        "side": if req.side == Side::Buy { "BUY" } else { "SELL" },
        "order_configuration": config,
    })
}

pub(super) async fn submit(c: &CexConnector, req: OrderRequest) -> Result<BrokerOrder, ConnectorError> {
    let product = c.exchange.symbol(&req.symbol);
    let rules = rules(c, &product).await.ok();
    // Coinbase requires a client id and treats a repeat as "return the order
    // that already has it", which is exactly the idempotency the engine's
    // per-process tagged id is for. Without one, make a unique one.
    let cid = req
        .client_order_id
        .clone()
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| format!("pythia-{}", uuid::Uuid::new_v4().simple()));
    let body = order_body(&req, &product, &cid, rules.as_ref());
    let v = private(c, reqwest::Method::POST, "/orders", "", Some(&body)).await?;
    parse_submit(&v, cid)
}

fn parse_submit(v: &Value, cid: String) -> Result<BrokerOrder, ConnectorError> {
    let id = v
        .get("success_response")
        .and_then(|s| s.get("order_id"))
        .or_else(|| v.get("order_id"))
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| ConnectorError::Rejected("Coinbase accepted the order but returned no order_id".into()))?;
    Ok(BrokerOrder::acknowledged(id, Some(cid)))
}

pub(super) async fn status(c: &CexConnector, order_id: &str) -> Result<BrokerOrder, ConnectorError> {
    let path = format!("/orders/historical/{}", sign::urlencode(order_id));
    let v = private(c, reqwest::Method::GET, &path, "", None).await?;
    let o = v
        .get("order")
        .ok_or_else(|| ConnectorError::Rejected(format!("Coinbase has no order {order_id}")))?;
    parse_order(o)
}

/// Read the single result of a one-order `batch_cancel`. An order that is
/// already gone (filled, cancelled, unknown) is the outcome we wanted.
fn parse_cancel(v: &Value, order_id: &str) -> Result<(), ConnectorError> {
    let r = v
        .get("results")
        .and_then(Value::as_array)
        .and_then(|a| a.iter().find(|r| r.get("order_id").and_then(Value::as_str) == Some(order_id)).or(a.first()));
    let Some(r) = r else {
        return Err(ConnectorError::Network("Coinbase cancel returned no result".into()));
    };
    if r.get("success").and_then(Value::as_bool) == Some(true) {
        return Ok(());
    }
    let reason = r.get("failure_reason").and_then(Value::as_str).unwrap_or("UNKNOWN_CANCEL_FAILURE_REASON");
    match reason {
        "UNKNOWN_CANCEL_ORDER" | "ORDER_IS_FULLY_FILLED" | "DUPLICATE_CANCEL_REQUEST" => Ok(()),
        _ => Err(classify(reason, format!("Coinbase cancel {order_id}: {reason}"))),
    }
}

pub(super) async fn cancel(c: &CexConnector, order_id: &str) -> Result<(), ConnectorError> {
    let body = serde_json::json!({ "order_ids": [order_id] });
    let v = private(c, reqwest::Method::POST, "/orders/batch_cancel", "", Some(&body)).await?;
    parse_cancel(&v, order_id)
}

/// Fold one page of `GET /accounts` into per-asset totals. Coinbase reports
/// the spendable amount and the amount held for open orders separately.
fn fold_accounts(v: &Value, into: &mut HashMap<String, (f64, f64)>) {
    let Some(arr) = v.get("accounts").and_then(Value::as_array) else { return };
    for a in arr {
        let Some(cur) = a.get("currency").and_then(Value::as_str) else { continue };
        let free = num_or0(a.get("available_balance").and_then(|b| b.get("value")));
        let hold = num_or0(a.get("hold").and_then(|b| b.get("value")));
        let e = into.entry(normalize_asset(cur)).or_insert((0.0, 0.0));
        e.0 += free;
        e.1 += hold;
    }
}

fn balances_from(totals: HashMap<String, (f64, f64)>) -> Vec<Balance> {
    let mut out: Vec<Balance> = totals
        .into_iter()
        .filter(|(_, (free, hold))| free + hold > 0.0)
        .map(|(asset, (free, hold))| {
            let total = free + hold;
            let usd = is_fiat(&asset).then_some(total);
            Balance { asset, free, total, usd_value: usd }
        })
        .collect();
    out.sort_by(|a, b| a.asset.cmp(&b.asset));
    out
}

pub(super) async fn balances(c: &CexConnector) -> Result<Vec<Balance>, ConnectorError> {
    let mut totals: HashMap<String, (f64, f64)> = HashMap::new();
    let mut cursor = String::new();
    for _ in 0..MAX_PAGES {
        let mut query = format!("limit={PAGE}");
        if !cursor.is_empty() {
            query.push_str(&format!("&cursor={}", sign::urlencode(&cursor)));
        }
        let v = private(c, reqwest::Method::GET, "/accounts", &query, None).await?;
        fold_accounts(&v, &mut totals);
        let next = v.get("cursor").and_then(Value::as_str).unwrap_or("");
        if v.get("has_next").and_then(Value::as_bool) != Some(true) || next.is_empty() || next == cursor {
            break;
        }
        cursor = next.to_string();
    }
    Ok(balances_from(totals))
}

/// Maker / taker rates of the account's current fee tier, as fractions.
fn parse_fee_tier(v: &Value) -> Option<(String, f64, f64)> {
    let t = v.get("fee_tier")?;
    let tier = t.get("pricing_tier").and_then(Value::as_str).unwrap_or("").to_string();
    Some((tier, num(t.get("maker_fee_rate"))?, num(t.get("taker_fee_rate"))?))
}

/// The account's spot fee tier, for the connection check. `None` when the key
/// cannot see it; a missing fee tier never fails a connection test.
pub(super) async fn fee_tier(c: &CexConnector) -> Option<(String, f64, f64)> {
    let v = private(c, reqwest::Method::GET, "/transaction_summary", "product_type=SPOT", None)
        .await
        .ok()?;
    parse_fee_tier(&v)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::connectors::cex::Exchange;

    // Response fixtures follow the shapes in Coinbase's Advanced Trade API
    // reference. Nothing here talks to Coinbase.

    fn req(side: Side, qty: f64, limit: Option<f64>) -> OrderRequest {
        OrderRequest {
            symbol: "BTC/USD".into(),
            side,
            order_type: if limit.is_some() { OrderType::Limit } else { OrderType::Market },
            qty,
            limit_price: limit,
            ref_price: Some(60_000.0),
            client_order_id: Some("pythia-ab12-7".into()),
            reduce_only: false,
        }
    }

    fn btc_rules() -> ProductRules {
        parse_rules(&serde_json::json!({
            "product_id": "BTC-USD", "price": "60000.00",
            "base_increment": "0.00000001", "quote_increment": "0.01", "price_increment": "0.01",
            "base_min_size": "0.00000001", "base_max_size": "3400",
            "quote_min_size": "1", "quote_max_size": "150000000",
            "status": "online", "trading_disabled": false, "is_disabled": false,
            "cancel_only": false, "limit_only": false, "post_only": false, "auction_mode": false
        }))
        .unwrap()
    }

    #[test]
    fn the_product_symbol_is_dash_separated_usd() {
        assert_eq!(Exchange::Coinbase.symbol("BTC/USD"), "BTC-USD");
        assert_eq!(Exchange::Coinbase.symbol("eth"), "ETH-USD");
        assert_eq!(Exchange::Coinbase.symbol("SOL/USDC"), "SOL-USDC");
    }

    #[test]
    fn a_market_order_is_sized_in_base_units_with_the_engine_client_id() {
        let r = btc_rules();
        let b = order_body(&req(Side::Buy, 0.000_123_456_789, None), "BTC-USD", "pythia-ab12-7", Some(&r));
        assert_eq!(b["client_order_id"], "pythia-ab12-7");
        assert_eq!(b["product_id"], "BTC-USD");
        assert_eq!(b["side"], "BUY");
        let m = &b["order_configuration"]["market_market_ioc"];
        assert_eq!(m["base_size"], "0.00012345", "snapped down to the 1e-8 step");
        assert!(m.get("quote_size").is_none(), "never size a market buy in dollars");
    }

    #[test]
    fn limit_prices_snap_away_from_the_market() {
        let r = btc_rules();
        let buy = order_body(&req(Side::Buy, 0.01, Some(60_000.019)), "BTC-USD", "c", Some(&r));
        let l = &buy["order_configuration"]["limit_limit_gtc"];
        assert_eq!(l["limit_price"], "60000.01", "a buy never pays more than asked");
        assert_eq!(l["base_size"], "0.01");
        assert_eq!(l["post_only"], false);
        let sell = order_body(&req(Side::Sell, 0.01, Some(60_000.011)), "BTC-USD", "c", Some(&r));
        assert_eq!(sell["side"], "SELL");
        assert_eq!(
            sell["order_configuration"]["limit_limit_gtc"]["limit_price"], "60000.02",
            "a sell never asks for less"
        );
    }

    #[test]
    fn without_rules_sizes_fall_back_to_eight_decimals() {
        let b = order_body(&req(Side::Sell, 1.5, None), "BTC-USD", "c", None);
        assert_eq!(b["order_configuration"]["market_market_ioc"]["base_size"], "1.5");
    }

    #[test]
    fn snapping_is_exact_on_coarse_and_fine_grids() {
        assert_eq!(snap(0.3, "0.1", false), "0.3", "0.3/0.1 is 2.999.. in floats, still 3 steps");
        assert_eq!(snap(123.456, "1", false), "123");
        assert_eq!(snap(0.123_456, "0.001", true), "0.124");
        assert_eq!(snap(1.0, "0.00000001", false), "1");
        assert_eq!(decimals("0.00000001"), 8);
        assert_eq!(decimals("0.010"), 2);
        assert_eq!(decimals("1"), 0);
    }

    #[test]
    fn rules_refuse_what_coinbase_would_refuse() {
        let mut r = btc_rules();
        // $1 minimum order value: 0.00001 BTC at 60k is $0.60.
        let why = rules_block(&r, "BTC-USD", &req(Side::Buy, 0.000_01, None)).unwrap();
        assert!(why.contains("minimum order value"), "{why}");
        assert!(rules_block(&r, "BTC-USD", &req(Side::Buy, 0.001, None)).is_none());

        r.base_min = 0.001;
        let why = rules_block(&r, "BTC-USD", &req(Side::Buy, 0.000_5, None)).unwrap();
        assert!(why.contains("minimum size"), "{why}");

        r = btc_rules();
        r.limit_only = true;
        assert!(rules_block(&r, "BTC-USD", &req(Side::Buy, 0.01, None)).unwrap().contains("limit-only"));
        assert!(rules_block(&r, "BTC-USD", &req(Side::Buy, 0.01, Some(60_000.0))).is_none());

        r = btc_rules();
        r.halted = true;
        assert!(rules_block(&r, "BTC-USD", &req(Side::Buy, 0.01, None)).is_some());
    }

    #[test]
    fn product_flags_and_status_mark_a_halted_book() {
        let r = parse_rules(&serde_json::json!({
            "base_increment": "0.1", "quote_increment": "0.0001",
            "base_min_size": "1", "quote_min_size": "1", "status": "delisted"
        }))
        .unwrap();
        assert!(r.halted);
        assert_eq!(r.price_increment, "0.0001", "quote_increment stands in for a missing price_increment");
        assert_eq!(r.base_max, f64::INFINITY);
        assert!(parse_rules(&serde_json::json!({"product_id": "X-USD"})).is_none());
    }

    #[test]
    fn a_submit_reads_the_order_id_from_success_response() {
        let v = serde_json::json!({
            "success": true,
            "success_response": {
                "order_id": "11111-00000-000000", "product_id": "BTC-USD",
                "side": "BUY", "client_order_id": "pythia-ab12-7"
            }
        });
        assert!(check_error(&v, "/orders").is_ok());
        let o = parse_submit(&v, "pythia-ab12-7".into()).unwrap();
        assert_eq!(o.id, "11111-00000-000000");
        assert_eq!(o.client_order_id.as_deref(), Some("pythia-ab12-7"));
        assert_eq!(o.status, BrokerOrderStatus::Working);
    }

    #[test]
    fn a_200_with_success_false_is_a_rejection_with_the_real_reason() {
        let v = serde_json::json!({
            "success": false,
            "failure_reason": "UNKNOWN_FAILURE_REASON",
            "order_id": "",
            "error_response": {
                "error": "INSUFFICIENT_FUND",
                "message": "Insufficient balance in source account",
                "error_details": "",
                "preview_failure_reason": "PREVIEW_INSUFFICIENT_FUND",
                "new_order_failure_reason": "INSUFFICIENT_FUND"
            }
        });
        let e = check_error(&v, "/orders").unwrap_err();
        assert!(matches!(e, ConnectorError::Rejected(_)), "{e:?}");
        let s = e.to_string();
        assert!(s.contains("INSUFFICIENT_FUND") && s.contains("Insufficient balance"), "{s}");
    }

    #[test]
    fn errors_are_classified_auth_rejected_or_transient() {
        let perm = serde_json::json!({"error": "PERMISSION_DENIED", "message": "Missing required scopes"});
        assert!(matches!(check_error(&perm, "/orders"), Err(ConnectorError::Auth(_))));
        let unauth = serde_json::json!({"error": "UNAUTHENTICATED", "message": "invalid JWT"});
        assert!(matches!(check_error(&unauth, "/accounts"), Err(ConnectorError::Auth(_))));
        let bad = serde_json::json!({"error": "INVALID_ARGUMENT", "message": "invalid product_id"});
        assert!(matches!(check_error(&bad, "/orders"), Err(ConnectorError::Rejected(_))));
        let rate = serde_json::json!({"error": "RATE_LIMIT_EXCEEDED", "message": "slow down"});
        let e = check_error(&rate, "/orders").unwrap_err();
        assert!(e.is_transient(), "{e:?}");
        // A normal body has neither `error` nor `success: false`.
        assert!(check_error(&serde_json::json!({"accounts": [], "has_next": false}), "/accounts").is_ok());
        assert!(check_error(&serde_json::json!({"error": ""}), "/accounts").is_ok());
    }

    #[test]
    fn an_open_order_with_fills_is_a_partial_fill() {
        let o = parse_order(&serde_json::json!({
            "order_id": "0000-000000-000000", "client_order_id": "pythia-ab12-7",
            "product_id": "BTC-USD", "side": "BUY", "status": "OPEN",
            "filled_size": "0.004", "average_filled_price": "60010.5",
            "filled_value": "240.042", "total_fees": "1.44", "completion_percentage": "40"
        }))
        .unwrap();
        assert_eq!(o.status, BrokerOrderStatus::PartiallyFilled);
        assert_eq!(o.filled_qty, 0.004);
        assert_eq!(o.avg_price, Some(60010.5));
        assert_eq!(o.fee, 1.44);
        assert_eq!(o.raw_status, "OPEN");
    }

    /// A filled market buy: Coinbase adds the fee to the dollars spent
    /// (`total_value_after_fees` = `filled_value` + `total_fees`), so every
    /// coin of `filled_size` arrives and none is kept as the fee.
    #[test]
    fn a_buy_pays_its_fee_in_dollars_and_keeps_the_full_size() {
        let o = parse_order(&serde_json::json!({
            "order_id": "cb-1", "side": "BUY", "status": "FILLED",
            "filled_size": "0.01", "average_filled_price": "60000", "filled_value": "600",
            "total_fees": "3.6", "total_value_after_fees": "603.6", "size_inclusive_of_fees": false
        }))
        .unwrap();
        assert_eq!((o.filled_qty, o.fee, o.fee_base), (0.01, 3.6, 0.0));
        assert!(o.fee_unpriced.is_empty());
    }

    #[test]
    fn a_filled_order_without_an_average_derives_it_from_value() {
        let o = parse_order(&serde_json::json!({
            "order_id": "x", "status": "FILLED",
            "filled_size": "0.5", "average_filled_price": "0", "filled_value": "30000", "total_fees": "180"
        }))
        .unwrap();
        assert_eq!(o.status, BrokerOrderStatus::Filled);
        assert_eq!(o.avg_price, Some(60000.0));
    }

    #[test]
    fn an_unfilled_order_has_no_average_and_statuses_map() {
        let o = parse_order(&serde_json::json!({
            "order_id": "x", "status": "PENDING", "filled_size": "0", "average_filled_price": "0"
        }))
        .unwrap();
        assert_eq!(o.avg_price, None);
        assert!(!o.status.is_terminal());
        assert_eq!(map_status("CANCELLED"), BrokerOrderStatus::Canceled);
        assert_eq!(map_status("EXPIRED"), BrokerOrderStatus::Expired);
        assert_eq!(map_status("FAILED"), BrokerOrderStatus::Rejected);
        assert!(!map_status("CANCEL_QUEUED").is_terminal());
        assert!(!map_status("SOMETHING_NEW").is_terminal());
        assert!(parse_order(&serde_json::json!({"status": "OPEN"})).is_err());
    }

    #[test]
    fn cancelling_something_already_gone_is_success() {
        let ok = serde_json::json!({"results": [{"success": true, "failure_reason": "UNKNOWN_CANCEL_FAILURE_REASON", "order_id": "a"}]});
        assert!(parse_cancel(&ok, "a").is_ok());
        for gone in ["UNKNOWN_CANCEL_ORDER", "ORDER_IS_FULLY_FILLED", "DUPLICATE_CANCEL_REQUEST"] {
            let v = serde_json::json!({"results": [{"success": false, "failure_reason": gone, "order_id": "a"}]});
            assert!(parse_cancel(&v, "a").is_ok(), "{gone}");
        }
        let refused = serde_json::json!({"results": [{"success": false, "failure_reason": "NOT_ALLOWED_TO_CANCEL", "order_id": "a"}]});
        assert!(matches!(parse_cancel(&refused, "a"), Err(ConnectorError::Rejected(_))));
        assert!(parse_cancel(&serde_json::json!({"results": []}), "a").is_err());
    }

    #[test]
    fn accounts_fold_into_free_plus_held_balances() {
        let page1 = serde_json::json!({
            "accounts": [
                {"uuid": "1", "name": "BTC Wallet", "currency": "BTC",
                 "available_balance": {"value": "0.4", "currency": "BTC"},
                 "hold": {"value": "0.1", "currency": "BTC"}, "active": true, "type": "ACCOUNT_TYPE_CRYPTO", "ready": true},
                {"uuid": "2", "name": "Cash (USD)", "currency": "USD",
                 "available_balance": {"value": "1000.00", "currency": "USD"},
                 "hold": {"value": "0", "currency": "USD"}, "active": true, "type": "ACCOUNT_TYPE_FIAT", "ready": true}
            ],
            "has_next": true, "cursor": "next-page", "size": 2
        });
        let page2 = serde_json::json!({
            "accounts": [
                {"uuid": "3", "name": "ETH Wallet", "currency": "ETH",
                 "available_balance": {"value": "0", "currency": "ETH"},
                 "hold": {"value": "0", "currency": "ETH"}}
            ],
            "has_next": false, "cursor": "", "size": 1
        });
        let mut totals = HashMap::new();
        fold_accounts(&page1, &mut totals);
        fold_accounts(&page2, &mut totals);
        let out = balances_from(totals);
        assert_eq!(out.len(), 2, "empty wallets are dropped");
        assert_eq!(out[0].asset, "BTC");
        assert_eq!(out[0].free, 0.4);
        assert!((out[0].total - 0.5).abs() < 1e-12);
        assert_eq!(out[0].usd_value, None, "BTC is priced by the wallet layer, not here");
        assert_eq!(out[1].asset, "USD");
        assert_eq!(out[1].usd_value, Some(1000.0));
    }

    #[test]
    fn the_fee_tier_is_read_as_fractions() {
        let v = serde_json::json!({
            "total_volume": 1000, "total_fees": 6,
            "fee_tier": {"pricing_tier": "Advanced 1", "usd_from": "0", "usd_to": "10000",
                          "taker_fee_rate": "0.006", "maker_fee_rate": "0.004"}
        });
        assert_eq!(parse_fee_tier(&v), Some(("Advanced 1".into(), 0.004, 0.006)));
        assert_eq!(parse_fee_tier(&serde_json::json!({})), None);
    }

    #[test]
    fn a_bad_key_is_an_auth_error_before_any_request() {
        let c = CexConnector::new(Exchange::Coinbase, "organizations/o/apiKeys/k".into(), "not a pem".into(), String::new());
        let e = bearer(&c, &reqwest::Method::GET, "/api/v3/brokerage/accounts").unwrap_err();
        assert!(matches!(e, ConnectorError::Auth(_)), "{e:?}");
        assert!(!e.to_string().contains("not a pem"), "never echo the secret: {e}");
    }

    #[test]
    fn a_good_key_yields_a_bearer_jwt_for_the_exact_path() {
        let sk = p256::SecretKey::from_slice(&[0x42u8; 32]).unwrap();
        let pem = sk.to_sec1_pem(Default::default()).unwrap().to_string();
        let c = CexConnector::new(Exchange::Coinbase, "organizations/o/apiKeys/k".into(), pem, String::new());
        let h = bearer(&c, &reqwest::Method::POST, "/api/v3/brokerage/orders").unwrap();
        let jwt = h.strip_prefix("Bearer ").unwrap();
        use base64::Engine as _;
        let claims = base64::engine::general_purpose::URL_SAFE_NO_PAD.decode(jwt.split('.').nth(1).unwrap()).unwrap();
        let claims: Value = serde_json::from_slice(&claims).unwrap();
        assert_eq!(claims["uri"], "POST api.coinbase.com/api/v3/brokerage/orders");
        let header = base64::engine::general_purpose::URL_SAFE_NO_PAD.decode(jwt.split('.').next().unwrap()).unwrap();
        let header: Value = serde_json::from_slice(&header).unwrap();
        assert_eq!(header["nonce"].as_str().map(str::len), Some(32), "a fresh 128-bit hex nonce");
    }
}
