//! Secrets vault. API keys are stored in the OS keychain (Windows Credential
//! Manager / macOS Keychain / libsecret) — never in files, never in the app
//! state, never logged. One entry per venue holds a JSON blob of that venue's
//! fields. Secret values are only ever read back by the connectors that need
//! them (Phase 2); they are NEVER returned to the UI.

use keyring::Entry;
use std::collections::BTreeMap;

const SERVICE: &str = "com.senseiissei.pythia";

/// Alpaca issues **separate** keys for the paper and live accounts, and each
/// pair only authenticates against its own endpoint. Storing one pair and
/// flipping the endpoint just produces a 401, so both live here side by side and
/// the connector picks by which endpoint is selected.
pub const ALPACA_PAPER: &str = "alpaca";
pub const ALPACA_LIVE: &str = "alpaca-live";

/// Venue-level credential slots (one per `connectors::Venue`, plus the
/// separate Alpaca live-account slot).
pub const VENUES: [&str; 4] = ["polymarket", "crypto", ALPACA_PAPER, ALPACA_LIVE];

/// The vault slot holding the credentials for one Alpaca endpoint.
pub fn alpaca_slot(paper: bool) -> &'static str {
    if paper {
        ALPACA_PAPER
    } else {
        ALPACA_LIVE
    }
}

/// Where a crypto exchange's key/secret/passphrase lives. One slot per venue
/// so switching exchanges never sends a Kraken key to Binance.
pub fn exchange_slot(exchange_id: &str) -> String {
    format!("exchange:{exchange_id}")
}

/// The slot holding watch-only on-chain addresses (a JSON array under
/// `addresses`). Deliberately never holds a private key — see `wallets.rs`.
pub const WALLETS: &str = "wallets";

/// Which crypto exchange `Venue::Crypto` routes through, stored under the
/// `crypto` venue slot as the field `exchange`.
pub fn selected_exchange() -> Option<String> {
    get("crypto")?.get("exchange").cloned()
}

/// Every slot that currently holds something, for the settings UI. Values are
/// never included — only whether a slot is populated.
pub fn status(exchange_ids: &[&str]) -> Vec<(String, bool)> {
    let mut out: Vec<(String, bool)> = VENUES.iter().map(|v| (v.to_string(), has_keys(v))).collect();
    for id in exchange_ids {
        let slot = exchange_slot(id);
        let present = has_keys(&slot);
        out.push((slot, present));
    }
    out.push((WALLETS.to_string(), has_keys(WALLETS)));
    out
}

fn entry(venue: &str) -> Result<Entry, String> {
    Entry::new(SERVICE, &format!("venue:{venue}")).map_err(|e| e.to_string())
}

/// Store a venue's fields. Overwrites any existing entry.
pub fn save(venue: &str, fields: &BTreeMap<String, String>) -> Result<(), String> {
    let json = serde_json::to_string(fields).map_err(|e| e.to_string())?;
    entry(venue)?.set_password(&json).map_err(|e| e.to_string())
}

/// True if a (non-empty) credential exists for this venue.
pub fn has_keys(venue: &str) -> bool {
    match entry(venue) {
        Ok(e) => matches!(e.get_password(), Ok(p) if !p.is_empty()),
        Err(_) => false,
    }
}

/// Remove a venue's credential. Missing entry is treated as success.
pub fn clear(venue: &str) -> Result<(), String> {
    let e = entry(venue)?;
    match e.delete_credential() {
        Ok(()) => Ok(()),
        Err(keyring::Error::NoEntry) => Ok(()),
        Err(err) => Err(err.to_string()),
    }
}

/// Read a venue's fields — for connector use only (Phase 2). Never expose the
/// return value to the frontend.
pub fn get(venue: &str) -> Option<BTreeMap<String, String>> {
    let json = entry(venue).ok()?.get_password().ok()?;
    serde_json::from_str(&json).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn vault_round_trip() {
        // Uses a throwaway venue name so real credentials are never touched.
        let venue = "test-ci-throwaway";
        let _ = clear(venue);
        assert!(!has_keys(venue), "should start empty");

        let mut fields = BTreeMap::new();
        fields.insert("key".to_string(), "abc123".to_string());
        fields.insert("secret".to_string(), "s3cr3t".to_string());
        save(venue, &fields).expect("save");

        assert!(has_keys(venue), "should report keys after save");
        let got = get(venue).expect("get");
        assert_eq!(got.get("secret").map(String::as_str), Some("s3cr3t"));

        clear(venue).expect("clear");
        assert!(!has_keys(venue), "should be empty after clear");
    }

    #[test]
    fn paper_and_live_alpaca_keys_are_separate_slots() {
        // The failure this prevents: save paper keys, flip the Live page to the
        // live endpoint, and every request 401s because Alpaca issues a
        // different pair per account. One shared slot cannot represent both.
        assert_ne!(alpaca_slot(true), alpaca_slot(false));
        assert!(VENUES.contains(&alpaca_slot(true)));
        assert!(VENUES.contains(&alpaca_slot(false)));
    }
}
