//! Request-signing primitives shared by the exchange connectors.
//!
//! Almost every centralised exchange authenticates the same way: an HMAC over
//! some canonical string, differing only in hash, encoding, and what goes into
//! the string. Keeping the crypto in one small, tested module means a new venue
//! is a two-line signature function rather than a fresh chance to get it wrong.
//!
//! The exception is Coinbase Advanced Trade, which signs a short-lived ES256
//! JWT with an EC private key instead; see [`cdp_jwt`].
//!
//! Secrets are borrowed as `&str` and never stored, logged, or returned, and
//! no error message here ever quotes the secret it failed to read.

use base64::Engine as _;
use hmac::{Hmac, Mac};
use p256::ecdsa::signature::Signer as _;
use p256::elliptic_curve::zeroize::Zeroizing;
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

// ── Coinbase CDP API keys: ES256 JWTs ───────────────────────────────────────

/// How long a Coinbase JWT is valid. Coinbase's limit is 2 minutes.
pub const CDP_JWT_TTL_SECS: i64 = 120;

/// Rebuild a PEM block from however it was pasted.
///
/// Coinbase hands the key out as a multi-line PEM inside a JSON file, so it
/// reaches us in every shape imaginable: with real newlines, with literal `\n`
/// escapes copied out of the JSON, in surrounding quotes, or squashed onto one
/// line by a single-line input field. All of them carry the same base64 body,
/// so strip it out and wrap it again at 64 columns.
///
/// Errors describe the shape of the problem, never the content.
fn normalize_pem(raw: &str) -> Result<Zeroizing<String>, String> {
    let s = Zeroizing::new(
        raw.trim()
            .trim_matches('"')
            .replace("\\r", "")
            .replace("\\n", "\n"),
    );
    let Some(begin) = s.find("-----BEGIN ") else {
        // A bare base64 blob of 64 bytes is the shape of a CDP Ed25519 key
        // (32-byte seed + 32-byte public key), which Advanced Trade refuses.
        let compact: String = s.chars().filter(|c| !c.is_whitespace()).collect();
        let decoded_len = base64::engine::general_purpose::STANDARD
            .decode(compact.as_bytes())
            .map(|v| Zeroizing::new(v).len())
            .unwrap_or(0);
        return Err(if decoded_len == 64 || decoded_len == 32 {
            "this looks like an Ed25519 key; Coinbase Advanced Trade needs an ECDSA key. \
             Create a new API key and choose ECDSA as the signature algorithm"
                .into()
        } else {
            "the Coinbase private key must be the whole PEM block, including the \
             -----BEGIN EC PRIVATE KEY----- and -----END EC PRIVATE KEY----- lines"
                .into()
        });
    };
    let after = &s[begin + "-----BEGIN ".len()..];
    let label_end = after.find("-----").ok_or("the PEM BEGIN line is cut off")?;
    let label = after[..label_end].trim().to_string();
    let rest = &after[label_end + "-----".len()..];
    let end_marker = format!("-----END {label}-----");
    let end = rest
        .find(&end_marker)
        .ok_or("the PEM block has no matching END line; copy the whole key again")?;
    let body: Zeroizing<String> = Zeroizing::new(rest[..end].chars().filter(|c| !c.is_whitespace()).collect());
    if body.is_empty() {
        return Err("the PEM block is empty".into());
    }

    let mut out = Zeroizing::new(String::with_capacity(body.len() + 80));
    out.push_str(&format!("-----BEGIN {label}-----\n"));
    for chunk in body.as_bytes().chunks(64) {
        // The body was filtered from a &str and base64 is ASCII; a stray
        // multi-byte character can only make the decode below fail, cleanly.
        out.push_str(&String::from_utf8_lossy(chunk));
        out.push('\n');
    }
    out.push_str(&end_marker);
    out.push('\n');
    Ok(out)
}

/// Parse the private key of a Coinbase CDP API key: a P-256 key as SEC1
/// (`-----BEGIN EC PRIVATE KEY-----`, what Coinbase issues) or PKCS#8
/// (`-----BEGIN PRIVATE KEY-----`, what `openssl pkcs8` turns it into).
pub fn cdp_signing_key(private_key_pem: &str) -> Result<p256::ecdsa::SigningKey, String> {
    let pem = normalize_pem(private_key_pem)?;
    let label_is_ec = pem.starts_with("-----BEGIN EC PRIVATE KEY-----");
    match p256::SecretKey::from_pem(&pem) {
        Ok(sk) => Ok(p256::ecdsa::SigningKey::from(sk)),
        Err(_) if label_is_ec => Err(
            "the Coinbase private key could not be read; copy the whole PEM block again".into(),
        ),
        // A PKCS#8 block that is not P-256 is almost always an Ed25519 key.
        Err(_) => Err("this is not an ECDSA P-256 private key; Coinbase Advanced Trade needs a key \
             created with the ECDSA signature algorithm, not Ed25519"
            .into()),
    }
}

/// A Coinbase CDP API JWT for one request, per Coinbase's "API key
/// authentication" guide
/// (<https://docs.cdp.coinbase.com/coinbase-app/authentication-authorization/api-key-authentication>,
/// read 2026-10-07):
///
/// - header: `alg` = `ES256`, `kid` = the key name
///   (`organizations/{org_id}/apiKeys/{key_id}`), `nonce` = random hex,
///   `typ` = `JWT`
/// - claims: `iss` = `cdp`, `sub` = the key name, `nbf` = now, `exp` = now +
///   120 s, `uri` = `"{METHOD} {host}{path}"`, e.g.
///   `GET api.coinbase.com/api/v3/brokerage/accounts`. The query string is not
///   part of `uri`.
/// - signature: ECDSA P-256 over SHA-256 of `b64url(header).b64url(claims)`,
///   encoded as the fixed 64-byte `r || s` (JWS, RFC 7518 §3.4), not DER.
///
/// A JWT is valid for exactly one method + path and two minutes, so a fresh
/// one is built for every request. `now` and `nonce` are parameters so tests
/// can pin them.
pub fn cdp_jwt(
    key_name: &str,
    private_key_pem: &str,
    method: &str,
    host: &str,
    path: &str,
    now: i64,
    nonce: &str,
) -> Result<String, String> {
    let key_name = key_name.trim();
    if key_name.is_empty() {
        return Err("the Coinbase API key name is empty".into());
    }
    let key = cdp_signing_key(private_key_pem)?;
    let path_only = path.split('?').next().unwrap_or(path);

    let header = serde_json::json!({
        "alg": "ES256",
        "kid": key_name,
        "nonce": nonce,
        "typ": "JWT",
    });
    let claims = serde_json::json!({
        "iss": "cdp",
        "sub": key_name,
        "nbf": now,
        "exp": now + CDP_JWT_TTL_SECS,
        "uri": format!("{} {host}{path_only}", method.to_ascii_uppercase()),
    });
    let b64 = |v: &serde_json::Value| base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(v.to_string());
    let signing_input = format!("{}.{}", b64(&header), b64(&claims));
    let sig: p256::ecdsa::Signature = key.sign(signing_input.as_bytes());
    let sig_b64 = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(sig.to_bytes());
    Ok(format!("{signing_input}.{sig_b64}"))
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

    // ── ES256 / Coinbase CDP ────────────────────────────────────────────────

    use p256::ecdsa::signature::Verifier as _;

    const KEY_NAME: &str = "organizations/test-org/apiKeys/test-key";

    /// A throwaway P-256 key built from a fixed scalar inside the test. It has
    /// never existed anywhere else and cannot authenticate against anything.
    fn test_key() -> (p256::SecretKey, String) {
        let sk = p256::SecretKey::from_slice(&[0x42u8; 32]).expect("valid scalar");
        let pem = sk.to_sec1_pem(Default::default()).expect("encode").to_string();
        (sk, pem)
    }

    fn b64url_json(part: &str) -> serde_json::Value {
        let bytes = base64::engine::general_purpose::URL_SAFE_NO_PAD.decode(part).expect("base64url");
        serde_json::from_slice(&bytes).expect("json")
    }

    #[test]
    fn cdp_jwt_has_the_documented_header_and_claims() {
        let (_, pem) = test_key();
        let jwt = cdp_jwt(KEY_NAME, &pem, "get", "api.coinbase.com", "/api/v3/brokerage/accounts?limit=250", 1_700_000_000, "abc123")
            .unwrap();
        let parts: Vec<&str> = jwt.split('.').collect();
        assert_eq!(parts.len(), 3, "header.claims.signature");

        let h = b64url_json(parts[0]);
        assert_eq!(h["alg"], "ES256");
        assert_eq!(h["kid"], KEY_NAME);
        assert_eq!(h["nonce"], "abc123");
        assert_eq!(h["typ"], "JWT");

        let c = b64url_json(parts[1]);
        assert_eq!(c["iss"], "cdp");
        assert_eq!(c["sub"], KEY_NAME);
        assert_eq!(c["nbf"], 1_700_000_000);
        assert_eq!(c["exp"], 1_700_000_120, "two minutes, Coinbase's maximum");
        assert_eq!(
            c["uri"], "GET api.coinbase.com/api/v3/brokerage/accounts",
            "method upper-cased, no scheme, no query string"
        );
    }

    #[test]
    fn cdp_jwt_signature_verifies_with_the_public_key() {
        let (sk, pem) = test_key();
        let jwt = cdp_jwt(KEY_NAME, &pem, "POST", "api.coinbase.com", "/api/v3/brokerage/orders", 1_700_000_000, "n")
            .unwrap();
        let (signing_input, sig_b64) = jwt.rsplit_once('.').unwrap();
        let sig_bytes = base64::engine::general_purpose::URL_SAFE_NO_PAD.decode(sig_b64).unwrap();
        assert_eq!(sig_bytes.len(), 64, "JWS wants raw r||s, not DER");
        let sig = p256::ecdsa::Signature::from_slice(&sig_bytes).unwrap();
        let vk = p256::ecdsa::VerifyingKey::from(&p256::ecdsa::SigningKey::from(&sk));
        assert!(vk.verify(signing_input.as_bytes(), &sig).is_ok(), "signature must verify");

        // And it binds the claims: a different path must not verify.
        let tampered = signing_input.replacen('.', ".x", 1);
        assert!(vk.verify(tampered.as_bytes(), &sig).is_err());

        // A different key must not verify either.
        let other = p256::SecretKey::from_slice(&[0x17u8; 32]).unwrap();
        let other_vk = p256::ecdsa::VerifyingKey::from(&p256::ecdsa::SigningKey::from(&other));
        assert!(other_vk.verify(signing_input.as_bytes(), &sig).is_err());
    }

    #[test]
    fn a_pem_survives_every_way_it_gets_pasted() {
        let (sk, pem) = test_key();
        let want = p256::ecdsa::SigningKey::from(&sk);
        let one_line = pem.replace('\n', " ");
        let json_escaped = format!("\"{}\"", pem.replace('\n', "\\n"));
        let crlf = pem.replace('\n', "\r\n");
        let squashed = pem.replace('\n', "");
        for (what, v) in [("one line", one_line), ("json", json_escaped), ("crlf", crlf), ("squashed", squashed)] {
            let got = cdp_signing_key(&v).unwrap_or_else(|e| panic!("{what}: {e}"));
            assert_eq!(got, want, "{what}");
        }
    }

    #[test]
    fn a_pkcs8_pem_is_accepted_too() {
        use p256::pkcs8::EncodePrivateKey as _;
        let (sk, _) = test_key();
        let pkcs8 = sk.to_pkcs8_pem(Default::default()).unwrap();
        assert!(pkcs8.starts_with("-----BEGIN PRIVATE KEY-----"));
        assert_eq!(cdp_signing_key(&pkcs8).unwrap(), p256::ecdsa::SigningKey::from(&sk));
    }

    #[test]
    fn key_errors_explain_the_shape_and_never_echo_the_key() {
        // An Ed25519 CDP secret is a bare 64-byte base64 blob.
        let ed = base64::engine::general_purpose::STANDARD.encode([7u8; 64]);
        let e = cdp_signing_key(&ed).unwrap_err();
        assert!(e.contains("Ed25519") && e.contains("ECDSA"), "{e}");
        assert!(!e.contains(&ed[..16]), "error must not quote the secret");

        let e = cdp_signing_key("hunter2-not-a-key").unwrap_err();
        assert!(e.contains("PEM"), "{e}");
        assert!(!e.contains("hunter2"));

        let (_, pem) = test_key();
        let body_line = pem.lines().nth(1).unwrap().to_string();
        let broken = pem.replace(&body_line, &body_line[..body_line.len() / 2]);
        let e = cdp_signing_key(&broken).unwrap_err();
        assert!(!e.contains(&body_line[..12]), "error must not quote the secret: {e}");

        let e = cdp_jwt("  ", &pem, "GET", "api.coinbase.com", "/x", 0, "n").unwrap_err();
        assert!(e.contains("key name"), "{e}");
    }
}
