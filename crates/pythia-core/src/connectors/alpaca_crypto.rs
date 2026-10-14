//! What the Alpaca crypto book accepts, what its refusals mean, and what it
//! has open. Pure functions, no network: the connector feeds them Alpaca's
//! JSON, the engine and the executor act on the answers, and the tests use the
//! documented shapes directly.
//!
//! ## Size rules
//!
//! Every crypto asset in `GET /v2/assets` carries three numbers
//! (<https://docs.alpaca.markets/reference/get-v2-assets-1>, and the crypto
//! guide <https://docs.alpaca.markets/docs/crypto-trading>, section "Crypto
//! Spot Trading", both checked 2026-10-12): `min_order_size` (the smallest
//! quantity an order may have), `min_trade_increment` (the quantity step) and
//! `price_increment` (the limit price step). Quantities go out with up to 9
//! decimals. [`CryptoRules`] rounds a quantity *down* to the step, so an order
//! can never ask for more than the book (or the account) has, and says when
//! what is left is below the minimum: that order is skipped, never sent to be
//! rejected.
//!
//! ## Refusals
//!
//! [`RejectKind`] sorts an order refusal into what it means for the next
//! attempt: a size below the minimum will be refused again, an empty balance
//! until cash arrives, a wash trade until the opposite order is gone, a 403
//! on the whole route until someone looks at the keys. Each kind backs off
//! for its own time and is journaled once per window, so a signal that fires
//! every tick does not become a request (and a journal line) every tick.

use super::{num, Side};
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// The most decimals Alpaca takes on a crypto quantity or price.
pub const MAX_DECIMALS: u32 = 9;

/// One crypto asset's order size rules, from `GET /v2/assets/{symbol}`.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CryptoRules {
    /// Smallest quantity an order may have, in coins. 0: none published.
    pub min_order_size: f64,
    /// Quantity step, in coins. 0: none published (9 decimals then).
    pub min_trade_increment: f64,
    /// Limit price step, in dollars. 0: none published.
    pub price_increment: f64,
}

/// What [`CryptoRules::fit_qty`] made of a quantity.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum QtyFit {
    /// Rounded down to the step and at least the minimum: send this.
    Ok(f64),
    /// Below the minimum once rounded: skip, do not send.
    BelowMinimum { qty: f64, min: f64 },
}

/// How many decimals a step needs, at most [`MAX_DECIMALS`].
fn decimals_of(step: f64) -> u32 {
    if !(step > 0.0) || !step.is_finite() {
        return MAX_DECIMALS;
    }
    (0..=MAX_DECIMALS)
        .find(|&d| {
            let scaled = step * 10f64.powi(d as i32);
            scaled.round() >= 1.0 && (scaled - scaled.round()).abs() < 1e-6 * scaled
        })
        .unwrap_or(MAX_DECIMALS)
}

/// `x` written with `decimals` decimals, trailing zeros dropped.
fn trimmed(x: f64, decimals: u32) -> String {
    let decimals = safe_decimals(x, decimals);
    let s = format!("{x:.*}", decimals as usize);
    if s.contains('.') {
        s.trim_end_matches('0').trim_end_matches('.').to_string()
    } else {
        s
    }
}

impl CryptoRules {
    /// Read the rules from one asset object. `None` when the asset carries
    /// none of them (an equity, or an answer without the fields).
    pub fn from_asset(v: &Value) -> Option<CryptoRules> {
        let get = |k: &str| num(v.get(k)).filter(|x| x.is_finite() && *x > 0.0);
        let (min, inc, px) = (get("min_order_size"), get("min_trade_increment"), get("price_increment"));
        if min.is_none() && inc.is_none() && px.is_none() {
            return None;
        }
        Some(CryptoRules {
            min_order_size: min.unwrap_or(0.0),
            min_trade_increment: inc.unwrap_or(0.0),
            price_increment: px.unwrap_or(0.0),
        })
    }

    pub fn qty_decimals(&self) -> u32 {
        decimals_of(self.min_trade_increment)
    }

    pub fn price_decimals(&self) -> u32 {
        decimals_of(self.price_increment)
    }

    /// Round `qty` down to the quantity step (to 9 decimals without one).
    pub fn floor_qty(&self, qty: f64) -> f64 {
        floor_to(qty, self.min_trade_increment, self.qty_decimals())
    }

    /// Round down to the step, then hold it against the minimum.
    pub fn fit_qty(&self, qty: f64) -> QtyFit {
        let q = self.floor_qty(qty);
        // A hair of float noise must not turn "exactly the minimum" into "below".
        if q <= 0.0 || (self.min_order_size > 0.0 && q < self.min_order_size * (1.0 - 1e-9)) {
            return QtyFit::BelowMinimum { qty: q.max(0.0), min: self.min_order_size };
        }
        QtyFit::Ok(q)
    }

    /// A limit price on the price step: a buy rounds down (never pays more
    /// than asked), a sell rounds up (never takes less).
    pub fn round_price(&self, price: f64, side: Side) -> f64 {
        let d = self.price_decimals();
        let step = self.price_increment;
        if !(step > 0.0) {
            return clean(price, d);
        }
        let steps = price / step;
        let n = match side {
            Side::Buy => (steps + 1e-9).floor(),
            Side::Sell => (steps - 1e-9).ceil(),
        };
        clean(n * step, d)
    }

    /// The quantity as the order body writes it.
    pub fn format_qty(&self, qty: f64) -> String {
        trimmed(self.floor_qty(qty), self.qty_decimals())
    }

    /// A limit price as the order body writes it.
    pub fn format_price(&self, price: f64) -> String {
        trimmed(price, self.price_decimals())
    }
}

/// Significant decimal digits an `f64` carries exactly.
const F64_DIGITS: u32 = 15;

/// At most `d` decimals, and no more than an `f64` of this size can carry.
/// 490974559.154990649 PEPE has nine digits before the point, so only six
/// after it are real: written with nine, the float prints 490974559.154990673,
/// more than the account holds, and Alpaca refuses the sell.
pub fn safe_decimals(x: f64, d: u32) -> u32 {
    let int_digits = if x.abs() >= 1.0 { x.abs().log10().floor() as u32 + 1 } else { 0 };
    d.min(F64_DIGITS.saturating_sub(int_digits))
}

/// Round `x` to `d` decimals, removing float noise.
fn clean(x: f64, d: u32) -> f64 {
    format!("{x:.*}", d as usize).parse().unwrap_or(x)
}

/// Round `qty` down to `step` (to `d` decimals when there is no step).
pub fn floor_to(qty: f64, step: f64, d: u32) -> f64 {
    if !(qty > 0.0) || !qty.is_finite() {
        return 0.0;
    }
    // Below the float's precision the step cannot be written exactly: the
    // grid of the last real decimal is used instead, which is coarser.
    let d = safe_decimals(qty, d);
    let grid = 10f64.powi(-(d as i32));
    if step > 0.0 && step >= grid * (1.0 - 1e-9) {
        let n = (qty / step + 1e-9).floor();
        return clean(n * step, d);
    }
    let f = 10f64.powi(d as i32);
    clean((qty * f + 1e-6).floor() / f, d)
}

/// A crypto quantity written for the order body when no rules are known:
/// 9 decimals, rounded down, trailing zeros dropped.
pub fn format_qty_plain(qty: f64) -> String {
    trimmed(floor_to(qty, 0.0, MAX_DECIMALS), MAX_DECIMALS)
}

// ── refusals ────────────────────────────────────────────────────────────────

/// What a refused order means for the next attempt.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum RejectKind {
    /// Below the asset's minimum order size (or Alpaca's own size floor).
    BelowMinimum,
    /// Not enough cash, buying power or coins for the order.
    InsufficientBalance,
    /// An opposite-side order of the same account is open in the pair.
    WashTrade,
    /// 401/403 that is not about the balance: keys, permissions, account.
    Forbidden,
    /// Any other 422: the venue found the order malformed.
    Unprocessable,
    /// Anything else: kept as before (short backoff, journaled each time).
    Other,
}

impl RejectKind {
    /// How long the next order waits after this refusal, in ms.
    pub fn backoff_ms(self) -> i64 {
        match self {
            RejectKind::BelowMinimum => 30 * 60_000,
            RejectKind::InsufficientBalance => 15 * 60_000,
            RejectKind::WashTrade => 5 * 60_000,
            RejectKind::Forbidden => 15 * 60_000,
            RejectKind::Unprocessable => 30 * 60_000,
            RejectKind::Other => 60_000,
        }
    }

    /// How long the same refusal stays out of the journal once said, in ms.
    /// `Other` is said every time, as before.
    pub fn quiet_ms(self) -> i64 {
        match self {
            RejectKind::BelowMinimum => 6 * 3_600_000,
            RejectKind::Other => 0,
            _ => 3_600_000,
        }
    }

    /// True when the refusal is about the route (keys, account), not the
    /// market: every market on it waits.
    pub fn whole_route(self) -> bool {
        self == RejectKind::Forbidden
    }

    pub fn label(self) -> &'static str {
        match self {
            RejectKind::BelowMinimum => "below the minimum order size",
            RejectKind::InsufficientBalance => "insufficient balance",
            RejectKind::WashTrade => "wash trade",
            RejectKind::Forbidden => "403 forbidden",
            RejectKind::Unprocessable => "422 unprocessable",
            RejectKind::Other => "refused",
        }
    }
}

/// Sort a refusal message (a connector error as text) into its kind. The
/// balance and wash trade words come first: Alpaca answers both with 403.
pub fn classify_reject(msg: &str) -> RejectKind {
    let m = msg.to_ascii_lowercase();
    let any = |words: &[&str]| words.iter().any(|w| m.contains(w));
    if any(&["below the minimum", "below alpaca's minimum", "minimum order size", "min order size", "cost basis must be", "qty must be >="]) {
        RejectKind::BelowMinimum
    } else if any(&["insufficient", "but buying power is", "but the broker only shows"]) {
        RejectKind::InsufficientBalance
    } else if m.contains("wash trade") {
        RejectKind::WashTrade
    } else if any(&[" 403", "403:", "http 403", "forbidden", "authentication failed", " 401"]) {
        RejectKind::Forbidden
    } else if any(&[" 422", "422:", "unprocessable"]) {
        RejectKind::Unprocessable
    } else {
        RejectKind::Other
    }
}

// ── open orders ─────────────────────────────────────────────────────────────

/// One order Alpaca has open (`GET /v2/orders?status=open`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct OpenOrder {
    pub id: String,
    #[serde(default)]
    pub client_order_id: String,
    /// In the pair form orders use, `BTC/USD`.
    pub symbol: String,
    pub side: Side,
    pub qty: f64,
    pub filled_qty: f64,
    pub status: String,
}

/// Every crypto order in an open-orders answer (a JSON array). Equities and
/// entries without an id are left out.
pub fn parse_open_orders(v: &Value) -> Vec<OpenOrder> {
    let Some(arr) = v.as_array() else { return Vec::new() };
    arr.iter()
        .filter_map(|o| {
            let id = o.get("id")?.as_str()?.to_string();
            let class = o.get("asset_class").and_then(Value::as_str).unwrap_or("");
            let raw = o.get("symbol")?.as_str()?;
            if class != "crypto" && !raw.contains('/') {
                return None;
            }
            let symbol = super::alpaca::alpaca_crypto_pair(raw)?;
            let side = match o.get("side").and_then(Value::as_str)? {
                "buy" => Side::Buy,
                "sell" => Side::Sell,
                _ => return None,
            };
            Some(OpenOrder {
                id,
                client_order_id: o.get("client_order_id").and_then(Value::as_str).unwrap_or_default().to_string(),
                symbol,
                side,
                qty: num(o.get("qty")).unwrap_or(0.0),
                filled_qty: num(o.get("filled_qty")).unwrap_or(0.0),
                status: o.get("status").and_then(Value::as_str).unwrap_or_default().to_string(),
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// BTC/USD and PEPE/USD as `GET /v2/assets` lists them (string numbers).
    fn btc() -> CryptoRules {
        let v: Value = serde_json::from_str(
            r#"{"symbol":"BTC/USD","class":"crypto","min_order_size":"0.0001",
                "min_trade_increment":"0.000000001","price_increment":"1"}"#,
        )
        .unwrap();
        CryptoRules::from_asset(&v).unwrap()
    }

    fn pepe() -> CryptoRules {
        let v: Value = serde_json::from_str(
            r#"{"symbol":"PEPE/USD","class":"crypto","min_order_size":"1000",
                "min_trade_increment":"1","price_increment":"0.000000001"}"#,
        )
        .unwrap();
        CryptoRules::from_asset(&v).unwrap()
    }

    #[test]
    fn a_large_quantity_is_written_with_only_the_decimals_its_float_carries() {
        assert_eq!(safe_decimals(0.5, 9), 9);
        assert_eq!(safe_decimals(123_456.0, 9), 9);
        assert_eq!(safe_decimals(490_974_559.15, 9), 6);
        assert_eq!(safe_decimals(1e16, 9), 0);
        let held: f64 = "490974559.154990649".parse().unwrap();
        assert_eq!(format_qty_plain(held), "490974559.15499");
        assert!(floor_to(held, 1e-9, 9) <= held);
        assert_eq!(floor_to(held, 1.0, 0), 490_974_559.0);
        // Small quantities keep all nine.
        assert_eq!(format_qty_plain(0.000123456789), "0.000123456");
    }

    #[test]
    fn reads_the_three_rules_and_nothing_from_an_equity() {
        let r = btc();
        assert_eq!(r.min_order_size, 0.0001);
        assert_eq!(r.min_trade_increment, 1e-9);
        assert_eq!(r.price_increment, 1.0);
        assert_eq!(r.qty_decimals(), 9);
        assert_eq!(r.price_decimals(), 0);
        let aapl: Value = serde_json::from_str(r#"{"symbol":"AAPL","class":"us_equity","fractionable":true}"#).unwrap();
        assert!(CryptoRules::from_asset(&aapl).is_none());
        // Numbers instead of strings read the same.
        let n: Value = serde_json::from_str(r#"{"min_order_size":0.01,"min_trade_increment":0.001}"#).unwrap();
        let r = CryptoRules::from_asset(&n).unwrap();
        assert_eq!((r.min_order_size, r.min_trade_increment, r.price_increment), (0.01, 0.001, 0.0));
    }

    #[test]
    fn quantities_round_down_to_the_step_and_never_up() {
        // The 13.10. buys: 0.007471 BTC and 49452471.482889 PEPE.
        assert_eq!(btc().fit_qty(0.0074719999), QtyFit::Ok(0.007471999));
        assert_eq!(btc().fit_qty(0.007471), QtyFit::Ok(0.007471));
        assert_eq!(pepe().fit_qty(49_452_471.482889), QtyFit::Ok(49_452_471.0));
        assert_eq!(btc().format_qty(0.0074719999), "0.007471999");
        assert_eq!(pepe().format_qty(49_452_471.9), "49452471");
        // 9 decimals at most, even without a step.
        assert_eq!(format_qty_plain(0.1234567899), "0.123456789");
        assert_eq!(format_qty_plain(2.0), "2");
        for q in [0.00012345678912, 1.9999999999, 0.30000000000000004] {
            match btc().fit_qty(q) {
                QtyFit::Ok(x) => assert!(x <= q, "{x} > {q}"),
                QtyFit::BelowMinimum { .. } => panic!("{q} is above the minimum"),
            }
        }
    }

    #[test]
    fn below_the_minimum_is_said_not_sent() {
        assert_eq!(btc().fit_qty(0.00005), QtyFit::BelowMinimum { qty: 0.00005, min: 0.0001 });
        assert_eq!(btc().fit_qty(0.0001), QtyFit::Ok(0.0001), "exactly the minimum is fine");
        assert_eq!(pepe().fit_qty(999.9), QtyFit::BelowMinimum { qty: 999.0, min: 1000.0 });
        assert!(matches!(btc().fit_qty(0.0), QtyFit::BelowMinimum { .. }));
        assert!(matches!(btc().fit_qty(f64::NAN), QtyFit::BelowMinimum { .. }));
    }

    #[test]
    fn limit_prices_sit_on_the_price_step_on_the_safe_side() {
        assert_eq!(btc().round_price(60_123.7, Side::Buy), 60_123.0);
        assert_eq!(btc().round_price(60_123.2, Side::Sell), 60_124.0);
        assert_eq!(btc().round_price(60_123.0, Side::Sell), 60_123.0, "already on the step");
        // A PEPE limit is not "0.00".
        assert_eq!(pepe().format_price(pepe().round_price(0.0000123456789, Side::Buy)), "0.000012345");
    }

    #[test]
    fn refusals_are_sorted_by_what_they_mean_for_the_next_order() {
        let cases = [
            ("venue rejected order: submit 403: {\"code\":40310000,\"message\":\"insufficient balance for USD (requested: 1000, available: 12.5)\"}", RejectKind::InsufficientBalance),
            ("venue rejected order: submit 403: {\"message\":\"potential wash trade detected. use complex orders\"}", RejectKind::WashTrade),
            ("venue rejected order: submit 422: {\"message\":\"qty must be >= 0.0001\"}", RejectKind::BelowMinimum),
            ("venue rejected order: submit 422: {\"message\":\"invalid time_in_force\"}", RejectKind::Unprocessable),
            ("0.00005 BTC/USD is below Alpaca's minimum order size of 0.0001", RejectKind::BelowMinimum),
            ("order needs $1200.00 but buying power is $50.00", RejectKind::InsufficientBalance),
            ("network error: timed out", RejectKind::Other),
            ("dry-run: not submitted", RejectKind::Other),
        ];
        for (msg, want) in cases {
            assert_eq!(classify_reject(msg), want, "{msg}");
        }
        // A 403 that is about the keys, as the connector words it.
        let auth = super::super::ConnectorError::Auth("HTTP 403 on submit: are these paper keys?".into()).to_string();
        assert_eq!(classify_reject(&auth), RejectKind::Forbidden, "{auth}");
        assert!(RejectKind::Forbidden.whole_route());
        assert!(!RejectKind::InsufficientBalance.whole_route());
        assert!(RejectKind::BelowMinimum.backoff_ms() > RejectKind::Other.backoff_ms());
        assert_eq!(RejectKind::Other.quiet_ms(), 0, "unclassified refusals are journaled as before");
    }

    #[test]
    fn open_orders_keep_crypto_only_in_the_pair_form() {
        let v: Value = serde_json::from_str(
            r#"[{"id":"a1","client_order_id":"pythia-x-ord_7","symbol":"BTC/USD","asset_class":"crypto",
                 "side":"buy","qty":"0.01","filled_qty":"0.004","status":"partially_filled"},
                {"id":"a2","client_order_id":"","symbol":"PEPEUSD","asset_class":"crypto",
                 "side":"sell","qty":"1000","filled_qty":"0","status":"new"},
                {"id":"a3","symbol":"AAPL","asset_class":"us_equity","side":"buy","qty":"1","status":"new"},
                {"symbol":"ETH/USD","side":"buy","qty":"1"}]"#,
        )
        .unwrap();
        let o = parse_open_orders(&v);
        assert_eq!(o.len(), 2);
        assert_eq!(o[0].symbol, "BTC/USD");
        assert_eq!((o[0].qty, o[0].filled_qty), (0.01, 0.004));
        assert_eq!(o[0].client_order_id, "pythia-x-ord_7");
        assert_eq!(o[1].symbol, "PEPE/USD");
        assert_eq!(o[1].side, Side::Sell);
    }
}
