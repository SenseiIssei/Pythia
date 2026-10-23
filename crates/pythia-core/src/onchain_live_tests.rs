//! The on-chain wallet's data: the views of the trader's files, the conversions
//! (request, proposal, confirm, result in one), each refusal, and the kill file
//! that only the server removes.

use super::*;

fn temp(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("pythia-onchain-live-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(convert_dir_in(&d)).unwrap();
    d
}

/// A made-up address (base58, 32 characters), not a real wallet.
const ADDR: &str = "11111111111111111111111111111111";
const NOW: i64 = 1_792_450_000_000;

fn status_with(root: &Path, t: i64, running: bool, kill: bool) {
    let s = serde_json::json!({
        "t": t, "running": running, "on": false, "mode": "test",
        "gate": ["the proof gate has not passed", "no simulate within 24 h"],
        "address": ADDR, "sol_lamports": 1_500_000_000u64,
        "balances": [{"coin": "SOL", "symbol": "SOL", "mint": "MintSo1", "amount": 1.5, "usd": 225.0, "price_usd": 150.0},
                     {"coin": "USDC", "symbol": "USDC", "mint": "MintUsdc", "amount": 20.0, "usd": 20.0, "price_usd": 1.0}],
        "total_usd": 245.0,
        "day": {"start_usd": 240.0, "pnl_usd": 5.0, "swaps": 0, "converts": 1, "convert_usd": 10.0},
        "ack": {"mode": "test", "books": ["onchain_breakout_top10_live"], "mints": ["SOL", "USDC"], "book_usd": 150,
                "max_total_usd": 200, "max_trade_usd": 100, "max_daily_loss_usd": 30, "max_convert_usd": 100,
                "expires": "2026-12-31", "on_kill": "hold"},
        "hard": {"max_total_usd": 500, "max_trade_usd": 100, "max_daily_loss_usd": 100, "max_convert_usd": 250,
                 "reserve_sol": 0.02, "max_converts": 10, "confirm_s": 60},
        "limits": {"max_total_usd": 200, "max_trade_usd": 100, "max_daily_loss_usd": 30, "max_convert_usd": 100},
        "coins": [{"coin": "SOL", "symbol": "SOL", "mint": "MintSo1", "decimals": 9, "allowed": true},
                  {"coin": "USDC", "symbol": "USDC", "mint": "MintUsdc", "decimals": 6, "allowed": true},
                  {"coin": "BONK", "symbol": "BONK", "mint": "MintBonk", "decimals": 5, "allowed": false}],
        "kill": kill,
        "simulate": {"t": t, "ok": true},
        "books": [{"book": "onchain_breakout_top10_live", "allowed": false, "why": "paper first"}],
        "reconcile": {"t": t, "ok": true, "diffs": []},
        "stops": {"daily": false, "total": false},
        "extra": 1
    });
    std::fs::write(dir_in(root).join("status.json"), s.to_string()).unwrap();
}

fn status(root: &Path) {
    status_with(root, NOW - 10_000, true, false);
}

fn put(root: &Path, id: &str, part: &str, v: serde_json::Value) {
    std::fs::write(convert_dir_in(root).join(format!("{id}.{part}.json")), v.to_string()).unwrap();
}

fn request(root: &Path, id: &str) {
    put(root, id, "request", serde_json::json!({"id": id, "from": "USDC", "to": "SOL", "amount": 10.0, "t": NOW - 5_000}));
}

fn proposal(root: &Path, id: &str, status: &str, expires_ms: i64) {
    let why = if status == "refused" { serde_json::json!("over the daily convert cap") } else { serde_json::Value::Null };
    put(
        root,
        id,
        "proposal",
        serde_json::json!({"id": id, "from": "USDC", "to": "SOL", "amount": 10.0, "in_raw": "10000000", "expected_out": 0.0501,
            "min_out": 0.0499, "min_out_raw": "49900000", "cost_bps": 4.2, "in_usd": 10.0, "route": ["Whirlpool"],
            "t": NOW - 4_000, "expires_ms": expires_ms, "status": status,
            "why": why}),
    );
}

fn result(root: &Path, id: &str, status: &str) {
    put(root, id, "result", serde_json::json!({"id": id, "status": status, "why": null, "sig": "FakeSig1", "out_amount": 0.05, "t": NOW - 1_000}));
}

#[test]
fn the_view_reads_the_traders_files_in_the_apps_spelling() {
    let d = temp("view");
    status(&d);
    std::fs::write(
        dir_in(&d).join("trades.json"),
        r#"{"trades": [
            {"t": 1, "kind": "convert", "from": "USDC", "to": "SOL", "in_amount": 10.0, "out_amount": 0.05, "status": "filled"},
            {"t": 3, "kind": "book", "book": "onchain_breakout_top10_live", "from": "SOL", "to": "JUP", "in_amount": 0.1,
             "fee_sol": 0.00004, "sig": "FakeSig2", "status": "failed", "why": "slippage"},
            {"t": "not a time"},
            {"t": 2, "kind": "convert", "from": "SOL", "to": "USDC", "in_amount": 0.1, "status": "filled"}
        ]}"#,
    )
    .unwrap();
    let v = view_in(&d, NOW);
    assert!(v.running && !v.kill_file);
    let s = v.status.as_ref().unwrap();
    assert_eq!((s.balances.len(), s.total_usd, s.gate.len(), s.coins.len()), (2, Some(245.0), 2, 3));
    assert_eq!(s.limits.as_ref().unwrap().max_trade_usd, Some(100.0));
    assert_eq!(v.address.as_deref(), Some(ADDR));
    // Newest first; the odd line is passed over, the others stay.
    assert_eq!(v.trades.iter().map(|t| t.t).collect::<Vec<_>>(), vec![Some(3.0), Some(2.0), Some(1.0)]);
    let json = serde_json::to_value(&v).unwrap();
    assert_eq!(json["status"]["balances"][0]["priceUsd"], 150.0);
    assert_eq!(json["status"]["solLamports"], 1_500_000_000u64);
    assert_eq!(json["status"]["ack"]["maxConvertUsd"], 100.0);
    assert_eq!(json["status"]["hard"]["reserveSol"], 0.02);
    assert_eq!(json["status"]["day"]["pnlUsd"], 5.0);
    assert_eq!(json["trades"][0]["feeSol"], 0.00004);
    assert_eq!(json["killFile"], false);
    assert!(json["eurUsd"].is_null());
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn a_stale_or_stopped_trader_is_not_running_and_the_wallet_file_gives_the_address() {
    let d = temp("stale");
    std::fs::write(dir_in(&d).join("wallet.json"), format!(r#"{{"address": "{ADDR}", "created_ms": 1}}"#)).unwrap();
    let v = view_in(&d, NOW);
    assert!(!v.running && v.status.is_none());
    assert_eq!(v.address.as_deref(), Some(ADDR));
    status_with(&d, NOW - STALE_MS - 1, true, false);
    let v = view_in(&d, NOW);
    assert!(!v.running && v.status.is_some());
    status_with(&d, NOW, false, false);
    assert!(!view_in(&d, NOW).running);
    std::fs::write(dir_in(&d).join("wallet.json"), r#"{"address": "not an address <script>"}"#).unwrap();
    std::fs::remove_file(dir_in(&d).join("status.json")).unwrap();
    assert_eq!(view_in(&d, NOW).address, None);
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn the_trades_are_capped_at_a_hundred() {
    let d = temp("many");
    let trades: Vec<serde_json::Value> = (0..150).map(|i| serde_json::json!({"t": i, "kind": "book", "status": "filled"})).collect();
    std::fs::write(dir_in(&d).join("trades.json"), serde_json::json!({ "trades": trades }).to_string()).unwrap();
    let v = view_in(&d, NOW);
    assert_eq!(v.trades.len(), MAX_TRADES);
    assert_eq!(v.trades[0].t, Some(149.0));
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn each_conversion_merges_its_files_into_one_state() {
    let d = temp("merge");
    let ids = [
        "c1792449990001-0001", // waiting
        "c1792449990002-0002", // proposed
        "c1792449990003-0003", // refused by the trader
        "c1792449990004-0004", // proposed, but too late
        "c1792449990005-0005", // confirmed
        "c1792449990006-0006", // filled
        "c1792449990007-0007", // failed
        "c1792449990008-0008", // expired by the trader
    ];
    for id in ids {
        request(&d, id);
    }
    proposal(&d, ids[1], "proposed", NOW + 30_000);
    proposal(&d, ids[2], "refused", NOW + 30_000);
    proposal(&d, ids[3], "proposed", NOW);
    for id in &ids[4..] {
        proposal(&d, id, "proposed", NOW - 1);
    }
    put(&d, ids[4], "confirm", serde_json::json!({"id": ids[4], "proposal_t": NOW - 4_000, "min_out_raw": "49900000", "t": NOW - 3_000}));
    result(&d, ids[5], "filled");
    result(&d, ids[6], "failed");
    result(&d, ids[7], "expired");
    // Not conversions: a half-written file, an odd name, a file whose id is another one's.
    std::fs::write(convert_dir_in(&d).join("c1792449990009-0009.request.json.tmp"), "{").unwrap();
    std::fs::write(convert_dir_in(&d).join("notes.json"), "{}").unwrap();
    put(&d, "c1792449990010-000a", "request", serde_json::json!({"id": "c1792449990001-0001", "from": "SOL", "to": "USDC", "amount": 1.0, "t": 1}));
    let v = view_in(&d, NOW);
    let states: Vec<(&str, &str)> = v.converts.iter().map(|c| (c.id.as_str(), c.state.as_str())).collect();
    assert_eq!(
        states,
        vec![
            (ids[7], "expired"),
            (ids[6], "failed"),
            (ids[5], "filled"),
            (ids[4], "confirmed"),
            (ids[3], "expired"),
            (ids[2], "refused"),
            (ids[1], "proposed"),
            (ids[0], "waiting"),
        ]
    );
    let p = &v.converts[6];
    assert_eq!((p.from.as_deref(), p.to.as_deref(), p.amount), (Some("USDC"), Some("SOL"), Some(10.0)));
    assert_eq!((p.expected_out, p.min_out, p.cost_bps, p.expires_ms), (Some(0.0501), Some(0.0499), Some(4.2), Some(NOW + 30_000)));
    assert_eq!(p.route, vec!["Whirlpool".to_string()]);
    assert_eq!(v.converts[5].why.as_deref(), Some("over the daily convert cap"));
    assert_eq!((v.converts[2].sig.as_deref(), v.converts[2].out_amount), (Some("FakeSig1"), Some(0.05)));
    assert_eq!(v.converts[3].confirmed_ms, Some(NOW - 3_000));
    let json = serde_json::to_value(&v.converts[6]).unwrap();
    assert_eq!((json["expectedOut"].clone(), json["costBps"].clone()), (serde_json::json!(0.0501), serde_json::json!(4.2)));
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn only_the_newest_twenty_conversions_are_shown() {
    let d = temp("twenty");
    for i in 0..25 {
        result(&d, &format!("c17924499900{i:02}-abcd"), "filled");
    }
    let v = view_in(&d, NOW);
    assert_eq!(v.converts.len(), MAX_CONVERTS);
    assert_eq!(v.converts[0].id, "c1792449990024-abcd");
    assert_eq!(v.converts[19].id, "c1792449990005-abcd");
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn a_conversion_request_is_written_atomically_with_a_fresh_id() {
    let d = temp("ask");
    status(&d);
    let id = convert_in(&d, "USDC", "SOL", 10.0, NOW).unwrap();
    assert!(is_id(&id), "{id}");
    assert!(id.starts_with(&format!("c{NOW}-")), "{id}");
    let text = std::fs::read_to_string(convert_dir_in(&d).join(format!("{id}.request.json"))).unwrap();
    let r: serde_json::Value = serde_json::from_str(&text).unwrap();
    assert_eq!(r, serde_json::json!({"id": id, "from": "USDC", "to": "SOL", "amount": 10.0, "t": NOW}));
    assert!(!convert_dir_in(&d).join(format!("{id}.request.json.tmp")).exists());
    let v = view_in(&d, NOW);
    assert_eq!((v.converts.len(), v.converts[0].state.as_str()), (1, "waiting"));
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn a_conversion_is_refused_unless_the_trader_runs_and_allows_both_coins() {
    let d = temp("refuse");
    let e = convert_in(&d, "USDC", "SOL", 10.0, NOW).unwrap_err();
    assert!(e.contains("not running"), "{e}");
    status_with(&d, NOW - STALE_MS - 1, true, false);
    assert!(convert_in(&d, "USDC", "SOL", 10.0, NOW).unwrap_err().contains("not running"));
    status_with(&d, NOW, false, false);
    assert!(convert_in(&d, "USDC", "SOL", 10.0, NOW).unwrap_err().contains("not running"));
    status_with(&d, NOW, true, true);
    assert!(convert_in(&d, "USDC", "SOL", 10.0, NOW).unwrap_err().contains("kill switch"));
    status(&d);
    for (from, to, amount, word) in [
        ("SOL", "SOL", 1.0, "different"),
        ("USDC", "BONK", 1.0, "BONK is not"),
        ("WIF", "SOL", 1.0, "WIF is not"),
        ("USDC", "../../x", 1.0, "is not"),
        ("USDC", "SOL", 0.0, "positive"),
        ("USDC", "SOL", -1.0, "positive"),
        ("USDC", "SOL", f64::NAN, "positive"),
        ("USDC", "SOL", f64::INFINITY, "positive"),
    ] {
        let e = convert_in(&d, from, to, amount, NOW).unwrap_err();
        assert!(e.contains(word), "{from} {to} {amount}: {e}");
    }
    assert_eq!(std::fs::read_dir(convert_dir_in(&d)).unwrap().count(), 0, "a refused request writes nothing");
    std::fs::write(kill_path_in(&d), "x").unwrap();
    assert!(convert_in(&d, "USDC", "SOL", 10.0, NOW).unwrap_err().contains("kill switch"));
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn at_most_three_requests_wait_for_the_trader() {
    let d = temp("three");
    status(&d);
    request(&d, "c1792449990001-0001");
    request(&d, "c1792449990002-0002");
    request(&d, "c1792449990003-0003");
    result(&d, "c1792449990003-0003", "filled");
    // Two open: a third is fine, a fourth is not.
    convert_in(&d, "USDC", "SOL", 1.0, NOW).unwrap();
    let e = convert_in(&d, "SOL", "USDC", 0.1, NOW).unwrap_err();
    assert!(e.contains("still waiting"), "{e}");
    result(&d, "c1792449990001-0001", "failed");
    assert!(convert_in(&d, "SOL", "USDC", 0.1, NOW).is_ok());
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn a_fresh_proposal_is_confirmed_with_its_time_and_minimum_out() {
    let d = temp("confirm");
    let id = "c1792449990001-0001";
    request(&d, id);
    proposal(&d, id, "proposed", NOW + 30_000);
    confirm_in(&d, id, NOW).unwrap();
    let text = std::fs::read_to_string(convert_dir_in(&d).join(format!("{id}.confirm.json"))).unwrap();
    let c: serde_json::Value = serde_json::from_str(&text).unwrap();
    assert_eq!(c, serde_json::json!({"id": id, "proposal_t": NOW - 4_000, "min_out_raw": "49900000", "t": NOW}));
    assert!(!convert_dir_in(&d).join(format!("{id}.confirm.json.tmp")).exists());
    assert_eq!(view_in(&d, NOW).converts[0].state, "confirmed");
    // Once only.
    assert!(confirm_in(&d, id, NOW).unwrap_err().contains("already confirmed"));
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn a_confirm_is_refused_for_bad_ids_and_proposals_that_are_not_open() {
    let d = temp("noconfirm");
    for bad in [
        "",
        "c1792449990001-001",
        "c1792449990001-00011",
        "c1792449990001-ABCD",
        "C1792449990001-abcd",
        "c179244999000x-abcd",
        "../../../etc/passwd",
        "c1792449990001-ab/d",
        "c1792449990001-abcd.proposal",
        "c1792449990001_abcd",
    ] {
        let e = confirm_in(&d, bad, NOW).unwrap_err();
        assert!(e.contains("Not a conversion id"), "{bad}: {e}");
    }
    let id = "c1792449990001-0001";
    request(&d, id);
    assert!(confirm_in(&d, id, NOW).unwrap_err().contains("no proposal"));
    proposal(&d, id, "refused", NOW + 30_000);
    let e = confirm_in(&d, id, NOW).unwrap_err();
    assert!(e.contains("refused") && e.contains("daily convert cap"), "{e}");
    proposal(&d, id, "proposed", NOW);
    assert!(confirm_in(&d, id, NOW).unwrap_err().contains("expired"));
    assert!(confirm_in(&d, id, NOW - 1).is_ok());
    let id2 = "c1792449990002-0002";
    proposal(&d, id2, "proposed", NOW + 30_000);
    result(&d, id2, "failed");
    assert!(confirm_in(&d, id2, NOW).unwrap_err().contains("already has a result"));
    let id3 = "c1792449990003-0003";
    put(&d, id3, "proposal", serde_json::json!({"id": id3, "status": "proposed", "expires_ms": NOW + 30_000}));
    assert!(confirm_in(&d, id3, NOW).unwrap_err().contains("incomplete"));
    // A proposal file carrying another id is not this one's.
    let id4 = "c1792449990004-0004";
    put(&d, id4, "proposal", serde_json::json!({"id": id, "status": "proposed", "expires_ms": NOW + 30_000, "t": NOW, "min_out_raw": "1"}));
    assert!(confirm_in(&d, id4, NOW).unwrap_err().contains("no proposal"));
    let id5 = "c1792449990005-0005";
    proposal(&d, id5, "proposed", NOW + 30_000);
    std::fs::write(kill_path_in(&d), "x").unwrap();
    assert!(confirm_in(&d, id5, NOW).unwrap_err().contains("kill switch"));
    assert!(!convert_dir_in(&d).join(format!("{id5}.confirm.json")).exists());
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn ids_are_c_thirteen_digits_dash_four_hex() {
    assert!(is_id("c1792449990001-a1b2"));
    assert!(is_id(&new_id(NOW)));
    assert!(!is_id("c1792449990001-a1b2 "));
    assert!(!is_id("c1792449990001-g1b2"));
}

#[test]
fn unknown_fields_are_refused_in_what_the_app_posts() {
    let r: Result<ConvertAsk, _> = serde_json::from_str(r#"{"from": "USDC", "to": "SOL", "amount": 1, "slippageBps": 5000}"#);
    assert!(r.is_err());
    let r: ConvertAsk = serde_json::from_str(r#"{"from": "USDC", "to": "SOL", "amount": 1.5}"#).unwrap();
    assert_eq!((r.from.as_str(), r.to.as_str(), r.amount), ("USDC", "SOL", 1.5));
    let r: Result<ConfirmAsk, _> = serde_json::from_str(r#"{"id": "c1792449990001-a1b2", "minOutRaw": "0"}"#);
    assert!(r.is_err());
}

#[test]
fn the_kill_file_is_written_once_and_never_removed_here() {
    let d = temp("kill");
    let k = kill_in(&d, NOW).unwrap();
    assert!(k.kill_file && !k.already);
    assert_eq!(k.path, "reports/onchain_live/KILL");
    let text = std::fs::read_to_string(kill_path_in(&d)).unwrap();
    assert!(text.contains("Delete it on the server") && text.contains("docs/ONCHAIN-STAGE2.md"), "{text}");
    let again = kill_in(&d, NOW + 1).unwrap();
    assert!(again.already);
    assert_eq!(std::fs::read_to_string(kill_path_in(&d)).unwrap(), text);
    assert!(view_in(&d, NOW).kill_file);
    let _ = std::fs::remove_dir_all(&d);
}
