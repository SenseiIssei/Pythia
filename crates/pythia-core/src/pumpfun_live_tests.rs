//! The pump.fun wallet page's data: the views of the live service's files, the
//! limits that can only go down, and the kill file that only the server removes.

use super::*;

fn temp(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("pythia-pumpfun-live-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(dir_in(&d)).unwrap();
    d
}

const ADDR: &str = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU";
const NOW: i64 = 1_792_450_000_000;

fn status(root: &Path, mode: &str, t: i64) {
    let s = serde_json::json!({
        "t": t, "running": true, "on": true, "mode": mode, "rule": "P_pool60", "address": ADDR,
        "balance_sol": 1.25, "balance_t": t, "holdings": [{"mint": "So11111111111111111111111111111111111111112", "amount": 5}],
        "positions": [{"pid": 3, "mint": "Mint1111111111111111111111111111111111111111", "symbol": "TST", "venue": "pool",
                       "state": "open", "tokens": 1000, "cost_sol": 0.02, "mark_sol": 0.025, "signal_ms": t, "land_ms": t,
                       "pool": "ignored"}],
        "leftovers": [], "pnl_today_sol": -0.01, "trades_today": 2, "wins_today": 1, "pnl_total_sol": -0.03,
        "trades_total": 7, "since_ms": t, "gate": [], "refusing": null,
        "ack": {"mode": mode, "strategy": "auto", "max_total_sol": 1.0, "max_daily_loss_sol": 0.3, "max_trade_sol": 0.02},
        "settings": {}, "limits": {"max_trade_sol": 0.02, "max_open": 5, "max_exposure_sol": 0.6,
                                    "max_daily_loss_sol": 0.3, "max_total_sol": 1.0},
        "hard": {}, "stops": {"daily": false, "total": false}, "kill": false,
        "simulate": {"t": t, "ok": true, "venue": "pool", "mint": "M"}, "exposure_sol": 0.02,
        "skipped": {"max open positions": 3}
    });
    std::fs::write(dir_in(root).join("live_status.json"), s.to_string()).unwrap();
}

#[test]
fn the_view_reads_the_services_files_in_the_apps_spelling() {
    let d = temp("view");
    status(&d, "test", NOW - 10_000);
    std::fs::write(
        dir_in(&d).join("live_trades.json"),
        r#"{"t": 1, "trades": [{"mode": "test", "rule": "P_pool60", "mint": "M", "pnl_sol": -0.004, "ret": -0.2, "lat_buy_ms": 1500, "legs": 2}]}"#,
    )
    .unwrap();
    std::fs::write(
        dir_in(&d).join("execution.json"),
        r#"{"verdict": "3 live buys", "fills": 3, "lat_buy_ms": {"n": 3, "median": 2000, "p10": 1500, "p90": 2500}, "assumed": {"lat_median_ms": 1000}, "lat_ratio": 2.0, "extra": 1}"#,
    )
    .unwrap();
    let v = view_in(&d, NOW);
    assert!(v.running && !v.kill_file);
    let s = v.status.as_ref().unwrap();
    assert_eq!((s.mode.as_deref(), s.balance_sol, s.positions.len(), s.trades_total), (Some("test"), Some(1.25), 1, 7));
    assert_eq!(s.ack.max_total_sol, Some(1.0));
    assert_eq!(v.address.as_deref(), Some(ADDR));
    assert_eq!(v.trades[0].lat_buy_ms, Some(1500.0));
    assert_eq!(v.execution.as_ref().unwrap().lat_buy_ms.median, Some(2000.0));
    let json = serde_json::to_value(&v).unwrap();
    assert_eq!(json["status"]["balanceSol"], 1.25);
    assert_eq!(json["status"]["positions"][0]["costSol"], 0.02);
    assert_eq!(json["status"]["skipped"]["max open positions"], 3);
    assert_eq!(json["hard"]["testMaxTotalSol"], 2.0);
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn a_stale_or_stopped_service_is_not_running_and_the_wallet_file_gives_the_address() {
    let d = temp("stale");
    std::fs::write(dir_in(&d).join("wallet.json"), format!(r#"{{"address": "{ADDR}", "created_ms": 1}}"#)).unwrap();
    let v = view_in(&d, NOW);
    assert!(!v.running && v.status.is_none());
    assert_eq!(v.address.as_deref(), Some(ADDR));
    status(&d, "test", NOW - STALE_MS - 1);
    assert!(!view_in(&d, NOW).running);
    std::fs::write(dir_in(&d).join("wallet.json"), r#"{"address": "not an address <script>"}"#).unwrap();
    std::fs::remove_file(dir_in(&d).join("live_status.json")).unwrap();
    assert_eq!(view_in(&d, NOW).address, None);
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn limits_can_only_be_set_below_the_confirmation_file() {
    let d = temp("limits");
    let patch = |t: Option<f64>, l: Option<f64>, x: Option<f64>, n: Option<u32>| SettingsPatch {
        max_total_sol: t,
        max_daily_loss_sol: l,
        max_trade_sol: x,
        max_open: n,
    };
    // Without the service's report of the confirmation file nothing can be set.
    assert!(write_settings_in(&d, patch(Some(0.5), None, None, None), NOW).unwrap_err().contains("confirmation file"));
    status(&d, "test", NOW);
    let s = write_settings_in(&d, patch(Some(0.5), Some(0.1), Some(0.01), Some(2)), NOW).unwrap();
    assert_eq!((s.max_total_sol, s.max_daily_loss_sol, s.max_trade_sol, s.max_open, s.updated_ms), (Some(0.5), Some(0.1), Some(0.01), Some(2), NOW));
    let text = std::fs::read_to_string(settings_path_in(&d)).unwrap();
    assert!(text.contains("\"max_trade_sol\": 0.01"), "{text}");
    // At the file's value is fine, above it is not; nor above the code's maximum.
    assert!(write_settings_in(&d, patch(Some(1.0), Some(0.3), Some(0.02), None), NOW).is_ok());
    for (p, word) in [
        (patch(Some(1.01), None, None, None), "total budget"),
        (patch(None, Some(0.31), None, None), "daily loss"),
        (patch(None, None, Some(0.03), None), "per trade"),
        (patch(Some(-1.0), None, None, None), "positive"),
        (patch(None, Some(f64::NAN), None, None), "positive"),
        (patch(None, None, None, Some(6)), "between 1 and 5"),
        (patch(None, None, None, Some(0)), "between 1 and 5"),
    ] {
        let e = write_settings_in(&d, p, NOW).unwrap_err();
        assert!(e.contains(word), "{e}");
    }
    assert_eq!(settings_in(&d).max_total_sol, Some(1.0)); // a refused write changes nothing
    // Null clears a limit of mine: the file's value applies again.
    assert_eq!(write_settings_in(&d, SettingsPatch::default(), NOW).unwrap().max_total_sol, None);
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn ceilings_never_exceed_the_hard_maxima() {
    let ack = AckView { mode: Some("test".into()), strategy: None, max_total_sol: Some(9.0), max_daily_loss_sol: Some(9.0), max_trade_sol: Some(9.0) };
    let c = ceilings(&ack).unwrap();
    assert_eq!((c.max_total_sol, c.max_daily_loss_sol, c.max_trade_sol), (Some(2.0), 0.5, 0.25));
    let small = AckView { max_trade_sol: Some(0.1), ..ack.clone() };
    assert_eq!(ceilings(&small).unwrap().max_trade_sol, 0.1); // the ack still rules under the cap
    let full = AckView { mode: Some("full".into()), max_daily_loss_sol: Some(0.4), ..AckView::default() };
    let c = ceilings(&full).unwrap();
    assert_eq!((c.max_total_sol, c.max_daily_loss_sol, c.max_trade_sol), (None, 0.4, 0.25));
    assert!(ceilings(&AckView::default()).is_err());
}

#[test]
fn unknown_fields_are_refused_so_nothing_can_raise_a_limit_by_another_name() {
    let r: Result<SettingsPatch, _> = serde_json::from_str(r#"{"maxTradeSol": 0.01, "hardMaxTradeSol": 5}"#);
    assert!(r.is_err());
    let r: SettingsPatch = serde_json::from_str(r#"{"maxTradeSol": 0.01, "maxTotalSol": null}"#).unwrap();
    assert_eq!((r.max_trade_sol, r.max_total_sol), (Some(0.01), None));
}

#[test]
fn the_kill_file_is_written_once_and_never_removed_here() {
    let d = temp("kill");
    let k = kill_in(&d, NOW).unwrap();
    assert!(k.kill_file && !k.already);
    let text = std::fs::read_to_string(kill_path_in(&d)).unwrap();
    assert!(text.contains("Delete it on the server"), "{text}");
    let again = kill_in(&d, NOW + 1).unwrap();
    assert!(again.already);
    assert_eq!(std::fs::read_to_string(kill_path_in(&d)).unwrap(), text);
    assert!(view_in(&d, NOW).kill_file);
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn addresses_are_base58_only() {
    assert!(is_address(ADDR));
    assert!(!is_address("0xabc"));
    assert!(!is_address(&"1".repeat(45)));
    assert!(!is_address("7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAs0"));
}

#[test]
fn reads_sol_in_euro_from_krakens_ticker() {
    let body = serde_json::json!({"error": [], "result": {"SOLEUR": {
        "a": ["93.10", "1", "1.000"], "b": ["93.05", "4", "4.000"], "c": ["93.08", "0.5"], "o": "90.00"}}});
    let p = parse_sol_eur(&body, 5).unwrap();
    assert_eq!((p.price, p.open, p.t), (93.08, 90.0, 5));
    assert!(parse_sol_eur(&serde_json::json!({"error": ["EQuery:Unknown asset pair"], "result": {}}), 5).is_none());
    assert!(parse_sol_eur(&serde_json::json!({"result": {"SOLEUR": {"c": ["0", "1"], "o": "90"}}}), 5).is_none());
}

#[test]
fn reads_the_euro_in_dollars_from_the_same_ticker_shape() {
    // Kraken answers the EURUSD pair under its own key; the first entry is read.
    let body = serde_json::json!({"error": [], "result": {"ZEURZUSD": {"c": ["1.0812", "10"], "o": "1.0790"}}});
    let p = parse_sol_eur(&body, 7).unwrap();
    assert_eq!((p.price, p.open, p.t), (1.0812, 1.079, 7));
    assert!(view_in(&temp("eurusd"), NOW).eur_usd.is_none());
}

#[test]
fn the_feed_is_passed_on_and_every_file_moves_its_stamp() {
    let d = temp("feed");
    assert!(feed_in(&d).is_none());
    let (view0, feed0) = stamps_in(&d);
    assert!(view0.iter().all(Option::is_none) && feed0.is_none());
    let feed = serde_json::json!({"t": NOW, "coins": [{"mint": "M", "points": [[NOW, 2e-6, 0.5, 1]], "exit": null}],
                                  "balance_sol": 0.7});
    std::fs::write(dir_in(&d).join("live_feed.json"), feed.to_string()).unwrap();
    assert_eq!(feed_in(&d), Some(feed));
    status(&d, "test", NOW);
    let (view1, feed1) = stamps_in(&d);
    assert!(view1[0].is_some() && feed1.is_some());
    std::fs::write(kill_path_in(&d), "x").unwrap();
    assert!(stamps_in(&d).0[4].is_some(), "the kill file changes the view");
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn the_trends_file_and_the_dexscreener_list_are_passed_on() {
    let d = temp("trends");
    assert_eq!(trends_in(&d), serde_json::json!({"trends": null, "dexscreener": null}));
    let t = serde_json::json!({"t": NOW, "lists": {"hot": [{"mint": "M", "vol_5m": 1.5, "badges": ["smart"]}], "migrating": [], "fresh": []}});
    std::fs::write(dir_in(&d).join("trends.json"), t.to_string()).unwrap();
    std::fs::create_dir_all(d.join("reports").join("trending")).unwrap();
    let rep = serde_json::json!({"title": "Trending watcher", "updatedMs": NOW, "status": "ok", "caveat": "watch only",
                                 "gainers": [{"name": "PEPE"}], "dex": [{"symbol": "CAT", "address": "A", "flags": ["thin liquidity"]}]});
    std::fs::write(d.join("reports").join("trending").join("latest.json"), rep.to_string()).unwrap();
    let v = trends_in(&d);
    assert_eq!(v["trends"], t);
    assert_eq!(v["dexscreener"], serde_json::json!({"updatedMs": NOW, "status": "ok", "caveat": "watch only",
                                                     "items": [{"symbol": "CAT", "address": "A", "flags": ["thin liquidity"]}]}));
    // A report without the DexScreener part still answers, with no items; a broken file is null.
    std::fs::write(d.join("reports").join("trending").join("latest.json"), r#"{"updatedMs": 5}"#).unwrap();
    assert_eq!(trends_in(&d)["dexscreener"]["items"], serde_json::json!([]));
    std::fs::write(dir_in(&d).join("trends.json"), "{not json").unwrap();
    assert!(trends_in(&d)["trends"].is_null());
    let _ = std::fs::remove_dir_all(&d);
}
