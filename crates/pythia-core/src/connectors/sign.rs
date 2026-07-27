//! Request-signing primitives shared by the exchange connectors.
//!
//! Every centralised exchange authenticates the same way — an HMAC over some
//! canonical string, differing only in hash, encoding, and what goes into the
//! string. Keeping the crypto in one small, tested module means a new venue is
//! a two-line signature function rather than a fresh chance to get it wrong.
//!
//! Secrets are borrowed as `&str` and never stored, logged, or returned.

use base64::Engine as _;
use hmac::{Hmac, Mac};
use sha2::{Digest, Sha256, Sha512};

type HmacSha256 = Hmac<Sha256>;
type HmacSha512 = Hmac<Sha512>;

/// HMAC-SHA256, hex-encoded. Binance, Bybit.
pub fn hmac_sha256_hex(secret: &str, msg: &str) -> String {
    let mut mac = HmacSha256::new_from_slice(secret.as_bytes()).expect("HMAC accepts any key length");
    mac.update(msg.as_bytes());
    hex::encode(mac.finalize().into_bytes())
}

/// HMAC-SHA256, base64-encoded. OKX.
pub fn hmac_sha256_b64(secret: &str, msg: &str) -> String {
    let mut mac = HmacSha256::new_from_slice(secret.as_bytes()).expect("HMAC accepts any key length");
    mac.update(msg.as_bytes());
    base64::engine::general_purpose::STANDARD.encode(mac.finalize().into_bytes())
}

/// Kraken's private-endpoint signature:
/// `base64(HMAC-SHA512(base64decode(secret), path || SHA256(nonce || postdata)))`
///
/// Note the secret is base64 *decoded* first — passing the raw string through
/// produces a well-formed signature that Kraken silently rejects, which is a
/// miserable thing to debug, hence the explicit error here.
pub fn kraken_signature(secret_b64: &str, path: &str, nonce: &str, postdata: &str) -> Result<String, String> {
    let key = base64::engine::general_purpose::STANDARD
        .decode(secret_b64.trim())
        .map_err(|_| "Kraken API secret is not valid base64 — copy it again from the API page".to_string())?;

    let mut sha = Sha256::new();
    sha.update(nonce.as_bytes());
    sha.update(postdata.as_bytes());
    let inner = sha.finalize();

    let mut mac = HmacSha512::new_from_slice(&key).map_err(|e| e.to_string())?;
    mac.update(path.as_bytes());
    mac.update(&inner);
    Ok(base64::engine::general_purpose::STANDARD.encode(mac.finalize().into_bytes()))
}

/// Percent-encode one query/form value (RFC 3986 unreserved set kept as-is).
pub fn urlencode(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => out.push(b as char),
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

/// Build a `k=v&k=v` string in the given order. Order matters: the signature is
/// over the literal string, so it must match what is actually sent on the wire.
pub fn form_encode(pairs: &[(&str, String)]) -> String {
    pairs
        .iter()
        .map(|(k, v)| format!("{}={}", urlencode(k), urlencode(v)))
        .collect::<Vec<_>>()
        .join("&")
}

/// Milliseconds since the Unix epoch — the nonce/timestamp every venue wants.
pub fn epoch_ms() -> i64 {
    chrono::Utc::now().timestamp_millis()
}

/// Format a quantity with at most `dp` decimals and no trailing zeros. Venues
/// reject `0.10000000` for a 2-decimal lot size, and scientific notation from
/// Rust's default float formatting is rejected everywhere.
pub fn trim_decimals(v: f64, dp: usize) -> String {
    let s = format!("{v:.dp$}");
    if !s.contains('.') {
        return s;
    }
    let t = s.trim_end_matches('0').trim_end_matches('.');
    if t.is_empty() || t == "-" {
        "0".into()
    } else {
        t.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hmac_sha256_matches_known_vector() {
        // RFC 4231 test case 1: key = 20 x 0x0b, data = "Hi There".
        let key = "\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b";
        assert_eq!(
            hmac_sha256_hex(key, "Hi There"),
            "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7"
        );
    }

    #[test]
    fn kraken_signature_matches_the_documented_example() {
        // The worked example from Kraken's own API docs.
        let secret = "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg==";
        let path = "/0/private/AddOrder";
        let nonce = "1616492376594";
        let postdata = "nonce=1616492376594&ordertype=limit&pair=XBTUSD&price=37500&type=buy&volume=1.25";
        assert_eq!(
            kraken_signature(secret, path, nonce, postdata).unwrap(),
            "4/dpxb3iT4tp/ZCVEwSnEsLxx0bqyhLpdfOpc6fn7OR8+UClSV5n9E6aSS8MPtnRfp32bAb0nmbRn6H8ndwLUQ=="
        );
    }

    #[test]
    fn kraken_signature_rejects_a_non_base64_secret() {
        // A secret pasted with a character dropped is the classic failure; say so
        // rather than signing garbage and getting an opaque "Invalid key".
        let err = kraken_signature("not base64!!", "/0/private/Balance", "1", "nonce=1").unwrap_err();
        assert!(err.contains("base64"), "{err}");
    }

    #[test]
    fn form_encoding_escapes_and_preserves_order() {
        let s = form_encode(&[("pair", "XBT/USD".into()), ("type", "buy".into())]);
        assert_eq!(s, "pair=XBT%2FUSD&type=buy");
    }

    #[test]
    fn quantities_never_use_scientific_notation_or_trailing_zeros() {
        assert_eq!(trim_decimals(0.000_012_3, 8), "0.0000123");
        assert_eq!(trim_decimals(1.500_000, 8), "1.5");
        assert_eq!(trim_decimals(42.0, 8), "42");
        assert_eq!(trim_decimals(0.0, 8), "0");
    }
}
