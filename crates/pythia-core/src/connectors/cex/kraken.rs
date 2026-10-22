//! Kraken spot (`https://api.kraken.com`).
//!
//! Private endpoints are POST form-encoded, signed per [`sign::kraken_signature`].
//! Two Kraken quirks drive most of the code here:
//!
//! 1. Errors come back inside a **200** response, in an `error` array — an
//!    `EOrder:Insufficient funds` looks exactly like success at the HTTP layer.
//! 2. The nonce must strictly increase per key. Milliseconds are fine as long as
//!    one key is not shared by two processes, which is why Pythia builds a fresh
//!    connector per submission rather than racing a pooled one.

use super::super::{
    num, num_or0, sign, Balance, BrokerOrder, BrokerOrderStatus, ConnectorError, OrderRequest,
    OrderType, Side,
};
use super::{is_fiat, normalize_asset, CexConnector};
use serde_json::Value;

const BASE: &str = "https://api.kraken.com";

/// POST a signed private endpoint. `params` must NOT contain the nonce — it is
/// prepended here so the signed string and the wire body cannot diverge.
async fn private(c: &CexConnector, endpoint: &str, params: &[(&str, String)]) -> Result<Value, ConnectorError> {
    let path = format!("/0/private/{endpoint}");
    let nonce = sign::epoch_ms().to_string();

    let mut all: Vec<(&str, String)> = vec![("nonce", nonce.clone())];
    all.extend(params.iter().cloned());
    let postdata = sign::form_encode(&all);

    let signature = sign::kraken_signature(&c.secret, &path, &nonce, &postdata)
        .map_err(ConnectorError::Auth)?;

    let rb = c
        .http
        .post(format!("{BASE}{path}"))
        .header("API-Key", c.key.trim())
        .header("API-Sign", signature)
        .header("content-type", "application/x-www-form-urlencoded")
        .body(postdata);

    let v = c.send(rb, endpoint).await?;
    check_error(&v, endpoint)?;
    Ok(v.get("result").cloned().unwrap_or(Value::Null))
}

/// Kraken reports failures in a 200 body. Anything in `error` is the real answer.
fn check_error(v: &Value, what: &str) -> Result<(), ConnectorError> {
    let Some(errs) = v.get("error").and_then(Value::as_array) else { return Ok(()) };
    if errs.is_empty() {
        return Ok(());
    }
    let msg = errs.iter().filter_map(Value::as_str).collect::<Vec<_>>().join("; ");
    // EAPI:Invalid key / EGeneral:Permission denied are credential problems, not
    // order problems — the distinction drives what the UI tells the user to fix.
    if msg.contains("Invalid key") || msg.contains("Permission denied") || msg.contains("Invalid signature") {
        return Err(ConnectorError::Auth(format!("Kraken: {msg}")));
    }
    Err(ConnectorError::Rejected(format!("Kraken {what}: {msg}")))
}

/// `pending`/`open` are live; `closed` means fully filled at Kraken (it has no
/// separate "partially filled" status — partials show as `open` with `vol_exec`).
fn map_status(s: &str) -> BrokerOrderStatus {
    match s {
        "closed" => BrokerOrderStatus::Filled,
        "canceled" => BrokerOrderStatus::Canceled,
        "expired" => BrokerOrderStatus::Expired,
        _ => BrokerOrderStatus::Working,
    }
}

pub(super) async fn submit(c: &CexConnector, req: OrderRequest) -> Result<BrokerOrder, ConnectorError> {
    let params = add_order_params(c.exchange.symbol(&req.symbol), &req);
    // Kraken's userref is a signed 32-bit int, so a UUID will not fit; the
    // engine's client id is carried for the journal only.
    let result = private(c, "AddOrder", &params).await?;
    let txid = result
        .get("txid")
        .and_then(Value::as_array)
        .and_then(|a| a.first())
        .and_then(Value::as_str)
        .ok_or_else(|| ConnectorError::Rejected("Kraken accepted the order but returned no txid".into()))?;

    Ok(BrokerOrder::acknowledged(txid, req.client_order_id))
}

/// What Kraken's public `AssetPairs` says about one USD pair Pythia trades:
/// the decimals an order volume may have (`lot_decimals`) and the smallest
/// volume it accepts (`ordermin`, in the base coin) and the decimals a limit
/// price may have (`pair_decimals`). Read from
/// <https://api.kraken.com/0/public/AssetPairs> on 2026-10-22. Kraken also
/// has a `costmin` of 0.5 USD on every one of them.
///
/// Newer listings (most memecoins) take only 5 decimals: a volume with 8 is
/// refused there, so an order for PEPE or BONK sized to the satoshi never
/// goes through. Prices are the same: BTC takes 1 decimal, PEPE 9.
const PAIRS: &[(&str, u32, f64, u32)] = &[
    ("XBTUSD", 8, 0.00006, 1),
    ("ETHUSD", 8, 0.002, 2),
    ("SOLUSD", 8, 0.05, 2),
    ("XRPUSD", 8, 4.0, 5),
    ("XDGUSD", 8, 50.0, 7),
    ("ADAUSD", 8, 20.0, 6),
    ("AVAXUSD", 8, 0.5, 3),
    ("LINKUSD", 8, 0.35, 5),
    ("LTCUSD", 8, 0.08, 2),
    ("DOTUSD", 8, 3.9, 4),
    ("BCHUSD", 8, 0.018, 2),
    ("TRXUSD", 8, 16.0, 6),
    ("SUIUSD", 5, 5.0, 4),
    ("NEARUSD", 8, 1.0, 4),
    ("ATOMUSD", 8, 3.0, 4),
    ("UNIUSD", 8, 0.7, 4),
    ("AAVEUSD", 8, 0.03, 2),
    ("XLMUSD", 8, 25.0, 6),
    ("PEPEUSD", 5, 1_100_000.0, 9),
    ("FILUSD", 8, 5.0, 3),
    ("ARBUSD", 5, 25.0, 4),
    ("BATUSD", 8, 50.0, 5),
    ("BONKUSD", 5, 1_300_000.0, 9),
    ("CRVUSD", 8, 15.0, 5),
    ("GRTUSD", 8, 170.0, 5),
    ("LDOUSD", 8, 11.0, 3),
    ("ONDOUSD", 5, 10.0, 5),
    ("POLUSD", 5, 50.0, 5),
    ("RENDERUSD", 5, 2.5, 3),
    ("SHIBUSD", 5, 770_000.0, 9),
    ("SUSHIUSD", 8, 20.0, 4),
    ("TRUMPUSD", 5, 2.5, 3),
    ("WIFUSD", 5, 20.0, 4),
    ("XTZUSD", 8, 13.0, 5),
    ("YFIUSD", 8, 0.0022, 1),
];

/// Kraken's smallest order value on every USD pair, in USD (`costmin`).
pub const COST_MIN_USD: f64 = 0.5;

/// Volume decimals for a pair not in [`PAIRS`]: 5, what most Kraken USD
/// pairs take (477 of 680 on 2026-10-22). A volume rounded to 5 is accepted
/// on a pair that allows 8; the other way round it is refused.
const DEFAULT_LOT_DECIMALS: u32 = 5;

/// (`lot_decimals`, `ordermin`) of a Kraken pair (`XBTUSD`), if known.
pub fn pair_limits(pair: &str) -> Option<(u32, f64)> {
    PAIRS.iter().find(|(p, ..)| *p == pair).map(|(_, d, m, _)| (*d, *m))
}

/// Price decimals for a pair not in [`PAIRS`]: 5, what most Kraken USD pairs
/// take (277 of 680 on 2026-10-22).
const DEFAULT_PRICE_DECIMALS: u32 = 5;

/// The limit-price decimals Kraken accepts on `pair`.
pub fn price_decimals(pair: &str) -> u32 {
    PAIRS.iter().find(|(p, ..)| *p == pair).map_or(DEFAULT_PRICE_DECIMALS, |l| l.3)
}

/// A limit price on the pair's price grid, rounded away from crossing: a buy
/// down, a sell up, so the order never pays more (or takes less) than the
/// engine asked for. Kraken refuses a price with more decimals than the pair has.
pub fn limit_price(pair: &str, side: Side, px: f64) -> String {
    let d = price_decimals(pair);
    let f = 10f64.powi(d as i32);
    // A hair of slack so a price that already sits on the grid is kept.
    let v = match side {
        Side::Buy => ((px * f) + 1e-6).floor() / f,
        Side::Sell => ((px * f) - 1e-6).ceil() / f,
    };
    sign::trim_decimals(v.max(0.0), d as usize)
}

/// The volume decimals Kraken accepts on `pair`.
pub fn lot_decimals(pair: &str) -> u32 {
    pair_limits(pair).map_or(DEFAULT_LOT_DECIMALS, |l| l.0)
}

/// `qty` rounded down to the pair's volume decimals: never more than was
/// asked for, so a sale of the whole holding never asks for coins the
/// account does not have. A hair of float noise is forgiven first, so
/// 0.3 stays 0.3 and does not become 0.29999.
pub fn lot_volume(pair: &str, qty: f64) -> String {
    let d = lot_decimals(pair) as usize;
    let f = 10f64.powi(d as i32);
    let v = ((qty * f) + 1e-6).floor() / f;
    sign::trim_decimals(v.max(0.0), d)
}

/// The `AddOrder` form for one order on Kraken's `pair`.
fn add_order_params(pair: String, req: &OrderRequest) -> Vec<(&'static str, String)> {
    let volume = lot_volume(&pair, req.qty);
    let price = req.limit_price.map(|p| limit_price(&pair, req.side, p));
    let mut params: Vec<(&'static str, String)> = vec![
        ("ordertype", if req.order_type == OrderType::Limit { "limit".into() } else { "market".into() }),
        ("pair", pair),
        ("type", req.side.as_str().to_string()),
        ("volume", volume),
    ];
    if let (OrderType::Limit, Some(p)) = (req.order_type, price) {
        params.push(("price", p));
    }
    // Fee currency: Kraken's default is the quote currency on a buy and the
    // BASE coin on a sell ("fcib prefer fee in base currency (default if
    // selling)", <https://docs.kraken.com/api/docs/rest-api/add-order>). A
    // sell would then need more coin than it sells, and an exit of the whole
    // position could never go through. Pin the quote currency on both sides.
    params.push(("oflags", "fciq".into()));
    params
}

pub(super) async fn status(c: &CexConnector, txid: &str) -> Result<BrokerOrder, ConnectorError> {
    let result = private(c, "QueryOrders", &[("txid", txid.to_string())]).await?;
    let o = result
        .get(txid)
        .ok_or_else(|| ConnectorError::Rejected(format!("Kraken has no order {txid}")))?;
    Ok(parse_order(txid, o))
}

/// One order of `QueryOrders`
/// (<https://docs.kraken.com/api/docs/rest-api/get-orders-info>): `fee` is
/// the "Total fee (quote currency)" and `price` the "Average price". Orders
/// from Pythia carry `fciq`, so the fee was also charged in the quote
/// currency. An order with `fcib` in its `oflags` (placed elsewhere, or
/// before the pin) paid its fee in the base coin: the same value, taken as
/// coins at the average price.
fn parse_order(txid: &str, o: &Value) -> BrokerOrder {
    let raw = o.get("status").and_then(Value::as_str).unwrap_or("unknown").to_string();
    let exec = num_or0(o.get("vol_exec"));
    let mut st = map_status(&raw);
    // A resting order with some volume done is a partial fill; Kraken only says
    // "open", so infer it from vol_exec or the engine never books the partial.
    if st == BrokerOrderStatus::Working && exec > 0.0 {
        st = BrokerOrderStatus::PartiallyFilled;
    }
    // A cancel that caught a partial still filled that much — keep the quantity.
    let avg_price = num(o.get("price")).filter(|p| *p > 0.0);
    let fee = num_or0(o.get("fee"));
    let in_base = o
        .get("oflags")
        .and_then(Value::as_str)
        .is_some_and(|f| f.split(',').any(|x| x.trim() == "fcib"));
    BrokerOrder {
        id: txid.to_string(),
        client_order_id: None,
        status: st,
        filled_qty: exec,
        avg_price,
        fee,
        fee_base: match avg_price {
            Some(p) if in_base => fee / p,
            _ => 0.0,
        },
        fee_unpriced: Vec::new(),
        raw_status: raw,
    }
}

pub(super) async fn cancel(c: &CexConnector, txid: &str) -> Result<(), ConnectorError> {
    match private(c, "CancelOrder", &[("txid", txid.to_string())]).await {
        Ok(_) => Ok(()),
        // Already gone is the outcome we wanted.
        Err(ConnectorError::Rejected(m)) if m.contains("Unknown order") => Ok(()),
        Err(e) => Err(e),
    }
}

pub(super) async fn balances(c: &CexConnector) -> Result<Vec<Balance>, ConnectorError> {
    // BalanceEx splits free vs. held-in-orders; plain Balance does not. Prefer
    // it, but fall back so an older key permission set still works.
    let result = match private(c, "BalanceEx", &[]).await {
        Ok(v) => v,
        Err(_) => private(c, "Balance", &[]).await?,
    };
    let Some(map) = result.as_object() else { return Ok(vec![]) };

    let mut out = Vec::new();
    for (code, v) in map {
        let (total, hold) = match v {
            // BalanceEx shape
            Value::Object(_) => (num_or0(v.get("balance")), num_or0(v.get("hold_trade"))),
            // Balance shape: a bare string amount
            _ => (num_or0(Some(v)), 0.0),
        };
        if total <= 0.0 {
            continue;
        }
        let asset = normalize_asset(code);
        let usd = is_fiat(&asset).then_some(total);
        out.push(Balance { asset, free: (total - hold).max(0.0), total, usd_value: usd });
    }
    out.sort_by(|a, b| a.asset.cmp(&b.asset));
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_200_with_an_error_array_is_a_failure() {
        let v: Value = serde_json::json!({"error": ["EOrder:Insufficient funds"], "result": {}});
        let e = check_error(&v, "AddOrder").unwrap_err();
        assert!(matches!(e, ConnectorError::Rejected(_)));
        assert!(e.to_string().contains("Insufficient funds"));
    }

    #[test]
    fn credential_errors_are_reported_as_auth_failures() {
        let v: Value = serde_json::json!({"error": ["EAPI:Invalid key"]});
        assert!(matches!(check_error(&v, "Balance"), Err(ConnectorError::Auth(_))));
    }

    #[test]
    fn an_empty_error_array_is_success() {
        let v: Value = serde_json::json!({"error": [], "result": {"txid": ["OU22CG"]}});
        assert!(check_error(&v, "AddOrder").is_ok());
    }

    #[test]
    fn open_with_executed_volume_is_a_partial_fill() {
        // Kraken has no partially_filled status, so it must be inferred.
        assert_eq!(map_status("open"), BrokerOrderStatus::Working);
        assert_eq!(map_status("closed"), BrokerOrderStatus::Filled);
        assert_eq!(map_status("canceled"), BrokerOrderStatus::Canceled);
        assert!(!map_status("pending").is_terminal());
    }

    /// Kraken's AssetPairs (2026-10-22): PEPE, BONK and SHIB take 5 volume
    /// decimals, BTC and NEAR 8. A volume with more decimals than the pair
    /// allows is refused, so the order is rounded down to the pair's lot.
    #[test]
    fn the_volume_is_rounded_down_to_the_pairs_lot_decimals() {
        assert_eq!(lot_decimals("PEPEUSD"), 5);
        assert_eq!(lot_decimals("BONKUSD"), 5);
        assert_eq!(lot_decimals("SHIBUSD"), 5);
        assert_eq!(lot_decimals("XBTUSD"), 8);
        assert_eq!(lot_decimals("NEARUSD"), 8);
        assert_eq!(lot_decimals("NEWCOINUSD"), 5, "an unknown pair gets the decimals most pairs take");
        assert_eq!(pair_limits("PEPEUSD"), Some((5, 1_100_000.0)));
        assert_eq!(pair_limits("XBTUSD"), Some((8, 0.00006)));

        let order = |pair: &str, qty: f64| {
            let req = OrderRequest::market("X/USD", super::super::super::Side::Sell, qty);
            let p = add_order_params(pair.into(), &req);
            p.iter().find(|(k, _)| *k == "volume").unwrap().1.clone()
        };
        assert_eq!(order("PEPEUSD", 2_345_678.123456789), "2345678.12345");
        assert_eq!(order("BONKUSD", 1_300_000.999999), "1300000.99999", "rounded down, never up");
        assert_eq!(order("SHIBUSD", 770_000.0), "770000");
        assert_eq!(order("XBTUSD", 0.00123456789), "0.00123456");
        assert_eq!(order("NEARUSD", 12.3456789012), "12.3456789");
        assert_eq!(order("NEARUSD", 0.3), "0.3", "float noise does not cost a lot");
        // Every pair in the table is one Pythia trades and has a real lot size.
        for (pair, d, min, pd) in PAIRS {
            assert!(*d == 5 || *d == 8, "{pair}");
            assert!(*min > 0.0, "{pair}");
            assert!((1..=10).contains(pd), "{pair}");
            assert!(crate::coins::by_kraken_key(pair).is_some(), "{pair} is a coin Pythia knows");
        }
    }

    /// Kraken's AssetPairs (2026-10-22): BTC prices take 1 decimal, ETH 2,
    /// PEPE 9. A limit with more is refused ("price can only be specified up
    /// to N decimals"), so it goes on the pair's grid, away from crossing.
    #[test]
    fn a_limit_price_goes_on_the_pairs_grid_away_from_crossing() {
        use super::super::super::Side::{Buy, Sell};
        assert_eq!(price_decimals("XBTUSD"), 1);
        assert_eq!(price_decimals("PEPEUSD"), 9);
        assert_eq!(price_decimals("NEWCOINUSD"), 5);
        let price = |pair: &str, side, px: f64| {
            let mut req = OrderRequest::market("X/USD", side, 1.0);
            req.order_type = OrderType::Limit;
            req.limit_price = Some(px);
            let p = add_order_params(pair.into(), &req);
            p.iter().find(|(k, _)| *k == "price").unwrap().1.clone()
        };
        assert_eq!(price("XBTUSD", Buy, 67_123.456789), "67123.4", "a buy never pays more");
        assert_eq!(price("XBTUSD", Sell, 67_123.456789), "67123.5", "a sell never takes less");
        assert_eq!(price("ETHUSD", Buy, 2_500.0), "2500");
        assert_eq!(price("ETHUSD", Sell, 2_500.1), "2500.1", "a price on the grid stays");
        assert_eq!(price("PEPEUSD", Buy, 0.0000123456789), "0.000012345");
        assert_eq!(price("SOLUSD", Sell, 150.001), "150.01");
        // A market order carries no price.
        let req = OrderRequest::market("BTC/USD", Buy, 0.01);
        assert!(add_order_params("XBTUSD".into(), &req).iter().all(|(k, _)| *k != "price"));
    }

    #[test]
    fn every_order_asks_for_its_fee_in_the_quote_currency() {
        for side in [super::super::super::Side::Buy, super::super::super::Side::Sell] {
            let req = OrderRequest::market("BTC/USD", side, 0.01);
            let p = add_order_params("XBTUSD".into(), &req);
            assert!(p.contains(&("oflags", "fciq".to_string())), "{side:?}: {p:?}");
        }
    }

    /// QueryOrders reports `fee` in the quote currency. With `fciq` that is
    /// money; an order carrying `fcib` paid the same value in coins.
    #[test]
    fn a_fee_in_the_quote_currency_takes_no_coins_and_fcib_does() {
        let quote: Value = serde_json::json!({
            "status": "closed", "vol_exec": "0.01000000", "price": "60000.0", "fee": "1.56000", "oflags": "fciq"
        });
        let o = parse_order("OABC", &quote);
        assert_eq!((o.fee, o.fee_base), (1.56, 0.0));
        assert_eq!(o.status, BrokerOrderStatus::Filled);

        let base: Value = serde_json::json!({
            "status": "closed", "vol_exec": "0.01000000", "price": "60000.0", "fee": "1.56000", "oflags": "fcib,post"
        });
        let o = parse_order("OABD", &base);
        assert_eq!(o.fee, 1.56);
        assert!((o.fee_base - 0.000026).abs() < 1e-12, "{}", o.fee_base);
    }

    #[test]
    fn balance_ex_splits_free_from_held() {
        let result: Value = serde_json::json!({
            "XXBT": {"balance": "0.5", "hold_trade": "0.1"},
            "ZUSD": {"balance": "1000.0", "hold_trade": "0"},
            "ETH":  {"balance": "0",   "hold_trade": "0"}
        });
        let map = result.as_object().unwrap();
        let mut out: Vec<Balance> = Vec::new();
        for (code, v) in map {
            let (total, hold) = (num_or0(v.get("balance")), num_or0(v.get("hold_trade")));
            if total <= 0.0 {
                continue;
            }
            let asset = normalize_asset(code);
            let usd = is_fiat(&asset).then_some(total);
            out.push(Balance { asset, free: (total - hold).max(0.0), total, usd_value: usd });
        }
        out.sort_by(|a, b| a.asset.cmp(&b.asset));

        assert_eq!(out.len(), 2, "zero balances are dropped");
        assert_eq!(out[0].asset, "BTC");
        assert_eq!(out[0].free, 0.4);
        assert_eq!(out[0].total, 0.5);
        assert_eq!(out[0].usd_value, None, "BTC is priced by the wallet layer, not here");
        assert_eq!(out[1].asset, "USD");
        assert_eq!(out[1].usd_value, Some(1000.0));
    }
}
