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
    let ack = AckView {
        mode: Some("test".into()),
        strategy: None,
        max_total_sol: Some(9.0),
        max_daily_loss_sol: Some(9.0),
        max_trade_sol: Some(9.0),
        limits: None,
        stake_share: None,
    };
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
    write_control_in(&d, ControlPatch { paused: Some(true), ..ControlPatch::default() }, NOW).unwrap();
    assert!(stamps_in(&d).0[5].is_some(), "the owner's controls change the view");
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

fn share(s: f64) -> ControlPatch {
    ControlPatch { share: Some(s), ..ControlPatch::default() }
}

fn paused(p: bool) -> ControlPatch {
    ControlPatch { paused: Some(p), ..ControlPatch::default() }
}

#[test]
fn the_share_is_taken_from_one_to_a_hundred_percent_only() {
    let d = temp("control-bounds");
    for ok in [0.01, 0.05, 0.1, 1.0] {
        assert_eq!(write_control_in(&d, share(ok), NOW).unwrap().file.share, Some(ok), "{ok}");
    }
    for bad in [0.0099, 1.01, 0.0, -0.5, f64::NAN, f64::INFINITY] {
        let e = write_control_in(&d, share(bad), NOW + 1).unwrap_err();
        assert!(e.contains("0.01 to 1.0"), "{bad}: {e}");
    }
    assert_eq!(control_in(&d).file.share, Some(1.0)); // a refused write changes nothing
    let both = ControlPatch { share: Some(0.5), reset_share: Some(true), ..ControlPatch::default() };
    assert!(write_control_in(&d, both, NOW).unwrap_err().contains("not both"));
    assert!(write_control_in(&d, ControlPatch::default(), NOW).unwrap_err().contains("Nothing to change"));
    let no_reset = ControlPatch { reset_share: Some(false), ..ControlPatch::default() };
    assert!(write_control_in(&d, no_reset, NOW).unwrap_err().contains("Nothing to change"));
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn missing_fields_keep_their_value_and_the_times_follow_the_changes() {
    let d = temp("control-keep");
    let v = write_control_in(&d, share(0.05), NOW).unwrap();
    assert_eq!((v.file.share, v.file.paused, v.file.set_at, v.file.share_set_at, v.file.paused_at), (Some(0.05), false, Some(NOW), Some(NOW), None));
    // Stop keeps the share and its time; stopping again keeps the time Stop began.
    let v = write_control_in(&d, paused(true), NOW + 10).unwrap();
    assert_eq!((v.file.share, v.file.share_set_at, v.file.paused, v.file.paused_at, v.file.set_at), (Some(0.05), Some(NOW), true, Some(NOW + 10), Some(NOW + 10)));
    let v = write_control_in(&d, paused(true), NOW + 20).unwrap();
    assert_eq!((v.file.paused_at, v.file.set_at), (Some(NOW + 10), Some(NOW + 20)));
    // The same share again keeps its time; another one moves it; the pause stays.
    assert_eq!(write_control_in(&d, share(0.05), NOW + 30).unwrap().file.share_set_at, Some(NOW));
    let v = write_control_in(&d, share(0.08), NOW + 40).unwrap();
    assert_eq!((v.file.share_set_at, v.file.paused, v.file.paused_at), (Some(NOW + 40), true, Some(NOW + 10)));
    // The app may clear Stop (unlike the kill file); the reset goes back to the confirmation file.
    let v = write_control_in(&d, paused(false), NOW + 50).unwrap();
    assert_eq!((v.file.paused, v.file.paused_at, v.file.share), (false, None, Some(0.08)));
    let v = write_control_in(&d, ControlPatch { reset_share: Some(true), ..ControlPatch::default() }, NOW + 60).unwrap();
    assert_eq!((v.file.share, v.file.share_set_at, v.file.set_at), (None, None, Some(NOW + 60)));
    // On disk in the lab's spelling, nothing left behind.
    let text = std::fs::read_to_string(dir_in(&d).join("control.json")).unwrap();
    let disk: serde_json::Value = serde_json::from_str(&text).unwrap();
    assert_eq!(disk, serde_json::json!({"share": null, "paused": false, "set_at": NOW + 60, "share_set_at": null, "paused_at": null}));
    assert!(!dir_in(&d).join("control.json.tmp").exists());
    assert!(!kill_path_in(&d).exists(), "Stop never touches the kill file");
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn a_missing_or_malformed_control_file_reads_as_no_override() {
    let d = temp("control-bad");
    let none = ControlFile { brake: Some(true), floor_sol: Some(PAUSE_BELOW_SOL), ..ControlFile::default() };
    assert_eq!(control_in(&d), ControlView { file: none.clone(), effective: None });
    std::fs::write(dir_in(&d).join("control.json"), "{not json").unwrap();
    assert_eq!(control_in(&d).file, none);
    assert_eq!(view_in(&d, NOW).control, ControlFile::default());
    // A write over a malformed file starts from none.
    let v = write_control_in(&d, paused(true), NOW).unwrap();
    assert_eq!((v.file.share, v.file.paused, v.file.paused_at), (None, true, Some(NOW)));
    let json = serde_json::to_value(&view_in(&d, NOW)).unwrap();
    assert_eq!(json["control"], serde_json::json!({"share": null, "paused": true, "setAt": NOW, "shareSetAt": null, "pausedAt": NOW}));
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn without_wallet_limits_the_share_only_goes_down_to_ten_percent() {
    let d = temp("control-ten");
    // No status yet: the bounds alone (the lab checks the confirmation file again).
    assert!(write_control_in(&d, share(0.5), NOW).is_ok());
    status(&d, "test", NOW);
    let e = write_control_in(&d, share(0.11), NOW).unwrap_err();
    assert!(e.contains("limits=wallet") && e.contains("10 %"), "{e}");
    assert_eq!(write_control_in(&d, share(0.1), NOW).unwrap().file.share, Some(0.1));
    // Stop and the reset need no wallet limits.
    assert!(write_control_in(&d, paused(true), NOW).is_ok());
    // A status that cannot be read counts as without.
    std::fs::write(dir_in(&d).join("live_status.json"), "{broken").unwrap();
    assert!(write_control_in(&d, share(0.2), NOW).is_err());
    let mut s: serde_json::Value = serde_json::json!({"t": NOW, "running": true, "ack": {"mode": "test", "limits": "fixed"}});
    std::fs::write(dir_in(&d).join("live_status.json"), s.to_string()).unwrap();
    assert!(write_control_in(&d, share(0.2), NOW).is_err());
    s["ack"]["limits"] = serde_json::json!("wallet");
    std::fs::write(dir_in(&d).join("live_status.json"), s.to_string()).unwrap();
    assert_eq!(write_control_in(&d, share(0.75), NOW).unwrap().file.share, Some(0.75));
    assert!(write_control_in(&d, share(1.01), NOW).is_err()); // wallet limits keep the bounds
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn unknown_control_fields_are_refused() {
    assert!(serde_json::from_str::<ControlPatch>(r#"{"paused": true, "kill": false}"#).is_err());
    assert!(serde_json::from_str::<ControlPatch>(r#"{"share": 0.5, "maxShare": 2}"#).is_err());
    let p: ControlPatch = serde_json::from_str(r#"{"resetShare": true}"#).unwrap();
    assert_eq!((p.share, p.reset_share, p.paused), (None, Some(true), None));
    let p: ControlPatch = serde_json::from_str(r#"{"brake": false, "floor_sol": 0}"#).unwrap();
    assert_eq!((p.brake, p.floor_sol), (Some(false), Some(0.0)));
    let p: ControlPatch = serde_json::from_str(r#"{"floorSol": 1.5}"#).unwrap();
    assert_eq!(p.floor_sol, Some(1.5));
    assert!(serde_json::from_str::<ControlPatch>(r#"{"brake": "off"}"#).is_err());
}

#[test]
fn the_brake_and_the_floor_are_saved_with_their_times_and_bad_floors_are_refused() {
    let d = temp("control-allin");
    let v = control_in(&d);
    assert_eq!((v.file.brake, v.file.floor_sol, v.file.brake_set_at, v.file.floor_sol_set_at), (Some(true), Some(0.25), None, None));
    write_control_in(&d, share(1.0), NOW).unwrap();
    let allin = ControlPatch { brake: Some(false), floor_sol: Some(0.0), ..ControlPatch::default() };
    let v = write_control_in(&d, allin.clone(), NOW + 10).unwrap();
    assert_eq!((v.file.brake, v.file.brake_set_at, v.file.floor_sol, v.file.floor_sol_set_at), (Some(false), Some(NOW + 10), Some(0.0), Some(NOW + 10)));
    assert_eq!((v.file.share, v.file.share_set_at, v.file.paused), (Some(1.0), Some(NOW), false)); // the rest stays
    let v = write_control_in(&d, allin, NOW + 20).unwrap(); // the same again keeps the times
    assert_eq!((v.file.brake_set_at, v.file.floor_sol_set_at, v.file.set_at), (Some(NOW + 10), Some(NOW + 10), Some(NOW + 20)));
    let v = write_control_in(&d, paused(true), NOW + 30).unwrap(); // other changes keep them
    assert_eq!((v.file.brake, v.file.floor_sol), (Some(false), Some(0.0)));
    let disk: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(dir_in(&d).join("control.json")).unwrap()).unwrap();
    assert_eq!((disk["brake"].clone(), disk["brake_set_at"].clone(), disk["floor_sol"].clone(), disk["floor_sol_set_at"].clone()),
               (serde_json::json!(false), serde_json::json!(NOW + 10), serde_json::json!(0.0), serde_json::json!(NOW + 10)));
    for ok in [0.0, 0.25, 10.0] {
        assert_eq!(write_control_in(&d, ControlPatch { floor_sol: Some(ok), ..ControlPatch::default() }, NOW).unwrap().file.floor_sol, Some(ok));
    }
    for bad in [-0.01, 10.01, f64::NAN, f64::INFINITY] {
        let e = write_control_in(&d, ControlPatch { floor_sol: Some(bad), ..ControlPatch::default() }, NOW).unwrap_err();
        assert!(e.contains("0 to 10"), "{bad}: {e}");
    }
    assert_eq!(control_in(&d).file.floor_sol, Some(10.0)); // a refused write changes nothing
    let v = write_control_in(&d, ControlPatch { brake: Some(true), ..ControlPatch::default() }, NOW + 40).unwrap();
    assert_eq!((v.file.brake, v.file.brake_set_at), (Some(true), Some(NOW + 40)));
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn the_status_carries_the_wallet_limits_the_stake_and_the_controls() {
    let d = temp("control-status");
    let s = serde_json::json!({
        "t": NOW, "running": true, "on": false, "mode": "test", "refusing": "paused by the owner since 14:05 UTC",
        "ack": {"mode": "test", "limits": "wallet", "stake_share": 0.1},
        "limits": {"kind": "wallet", "max_trade_sol": 0.45, "max_open": 5, "max_exposure_sol": 0.8,
                   "max_daily_loss_sol": null, "max_total_sol": null},
        "stake": {"sol": 0.45, "why": "50 % of 0.90 SOL (limits: wallet)", "share": 0.5},
        "control": {"limits": "wallet", "share": 0.5, "share_source": "owner", "share_since": NOW - 5,
                    "ack_share": 0.1, "requested_share": 0.5, "paused": true, "paused_since": NOW - 3,
                    "note": null, "control_ok": true},
        "low": {"have": 0.2, "need": 0.25, "unit": "SOL"}
    });
    std::fs::write(dir_in(&d).join("live_status.json"), s.to_string()).unwrap();
    let v = view_in(&d, NOW);
    let st = v.status.as_ref().unwrap();
    assert_eq!((st.ack.limits.as_deref(), st.ack.stake_share), (Some("wallet"), Some(0.1)));
    assert_eq!(st.limits.as_ref().unwrap().kind.as_deref(), Some("wallet"));
    assert_eq!(st.stake.as_ref().unwrap().share, Some(0.5));
    let c = st.control.as_ref().unwrap();
    assert_eq!((c.share_source.as_deref(), c.paused, c.paused_since, c.control_ok), (Some("owner"), true, Some(NOW - 3), Some(true)));
    let json = serde_json::to_value(&v).unwrap();
    assert_eq!(json["status"]["ack"]["stakeShare"], 0.1);
    assert_eq!(json["status"]["limits"]["kind"], "wallet");
    assert!(json["status"]["limits"]["maxDailyLossSol"].is_null());
    assert_eq!(json["status"]["stake"]["why"], "50 % of 0.90 SOL (limits: wallet)");
    assert_eq!(json["status"]["control"]["shareSource"], "owner");
    assert_eq!(json["status"]["control"]["shareSince"], NOW - 5);
    assert_eq!(json["status"]["control"]["ackShare"], 0.1);
    assert_eq!(json["status"]["control"]["requestedShare"], 0.5);
    assert_eq!(json["status"]["control"]["controlOk"], true);
    assert_eq!(json["status"]["low"], serde_json::json!({"have": 0.2, "need": 0.25, "unit": "SOL"}));
    // The control route answers the file and the status's control in one.
    let cv = serde_json::to_value(write_control_in(&d, share(0.5), NOW).unwrap()).unwrap();
    assert_eq!((cv["share"].clone(), cv["paused"].clone(), cv["setAt"].clone()), (serde_json::json!(0.5), serde_json::json!(false), serde_json::json!(NOW)));
    assert_eq!(cv["effective"]["requestedShare"], 0.5);
    assert_eq!(cv["effective"]["pausedSince"], NOW - 3);
    // An older status without the new fields still reads.
    status(&d, "test", NOW);
    let st = view_in(&d, NOW).status.unwrap();
    assert!(st.control.is_none() && st.low.is_none() && st.stake.is_none() && st.ack.limits.is_none());
    assert!(control_in(&d).effective.is_none());
    let _ = std::fs::remove_dir_all(&d);
}
