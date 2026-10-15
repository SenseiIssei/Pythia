//! The look of an alert, the switches, quiet hours, big moves and batching,
//! without a network.

use super::card::*;
use super::*;
use chrono::TimeZone;

fn utc(y: i32, m: u32, d: u32, h: u32, min: u32) -> i64 {
    chrono::Utc.with_ymd_and_hms(y, m, d, h, min, 0).unwrap().timestamp_millis()
}

fn tg(text: &str) -> AlertConfig {
    let mut c = AlertConfig::new("https://api.telegram.org/bot1:x/sendMessage", AlertFormat::Telegram);
    c.chat_id = Some("42".into());
    let _ = text;
    c
}

#[test]
fn numbers_have_signs_separators_and_percent() {
    assert_eq!(thousands(1234567.891, 2), "1,234,567.89");
    assert_eq!(thousands(-0.001, 2), "0.00", "no minus zero");
    assert_eq!(usd(12345.678), "$12,345.68");
    assert_eq!(usd(-12.3), "-$12.30");
    assert_eq!(signed_usd(1234.5), "+$1,234.50");
    assert_eq!(signed_usd(-87.654), "-$87.65");
    assert_eq!(signed_usd(0.0), "+$0.00");
    assert_eq!(signed_pct(1.234, 2), "+1.23 %");
    assert_eq!(signed_pct(-0.4, 1), "-0.4 %");
    assert_eq!(price(67234.1), "$67,234.10");
    assert_eq!(price(0.00001234), "$0.000012");
    assert_eq!(qty(0.01230000), "0.0123");
    assert_eq!(qty(1500.0), "1,500");
    assert_eq!(Tone::of(2.0).dot(), "🟢");
    assert_eq!(Tone::of(-2.0).dot(), "🔴");
    assert_eq!(Tone::of(0.0).dot(), "⚪");
}

#[test]
fn html_is_escaped_everywhere() {
    assert_eq!(esc("a < b & c > d"), "a &lt; b &amp; c &gt; d");
    let c = Card::new("🧪", "<script>alert(1)</script>")
        .summary("P&L <b>up</b>")
        .row(Row::new("A&B", "<1>"))
        .footer("x < y");
    let html = c.render(AlertFormat::Telegram);
    assert!(html.starts_with("<b>🧪 &lt;script&gt;alert(1)&lt;/script&gt;</b>\n"), "{html}");
    assert!(html.contains("P&amp;L &lt;b&gt;up&lt;/b&gt;"));
    assert!(html.contains("<pre>A&amp;B  &lt;1&gt;</pre>"));
    assert!(html.ends_with("<i>x &lt; y</i>"));
    // Only the tags the card itself writes remain.
    let tags: Vec<&str> = html.match_indices('<').map(|(i, _)| &html[i..i + 3]).collect();
    assert!(tags.iter().all(|t| ["<b>", "</b", "<pr", "</p", "<i>", "</i"].contains(t)), "{tags:?}");
}

#[test]
fn a_card_is_title_summary_aligned_rows_footer() {
    let c = Card::new("🛑", "Momentum stopped")
        .summary("Max loss reached.")
        .row(Row::new("Equity", usd(9412.3)))
        .row(Row::toned("P&L", format!("{} {}", signed_usd(-587.7), signed_pct(-5.877, 2)), -587.7))
        .row(Row::new("Trades", "14"))
        .footer("Pythia");
    let html = c.render(AlertFormat::Telegram);
    let want = "<b>🛑 Momentum stopped</b>\nMax loss reached.\n<pre>Equity         $9,412.30\nP&amp;L     -$587.70 -5.88 % 🔴\nTrades                14</pre>\n<i>Pythia</i>";
    assert_eq!(html, want);
    // The same card in Discord's markdown.
    let md = c.render(AlertFormat::Discord);
    assert!(md.starts_with("**🛑 Momentum stopped**\nMax loss reached.\n```\nEquity"), "{md}");
    assert!(md.ends_with("```\n*Pythia*"));
    assert!(c.render(AlertFormat::Slack).starts_with("*🛑 Momentum stopped*"));
}

#[test]
fn values_line_up_on_the_right() {
    let c = Card::new("📊", "t").row(Row::new("A", "$1.00")).row(Row::new("Longer label", "$12,345.00"));
    let block = c.render(AlertFormat::Discord);
    let lines: Vec<&str> = block.lines().filter(|l| l.contains('$')).collect();
    assert_eq!(lines[0].len(), lines[1].len(), "{lines:?}");
}

fn line(book: &str, buy: bool, sym: &str, q: f64, p: f64, rebalance: bool) -> TradeLine {
    TradeLine {
        book: book.into(),
        buy,
        symbol: sym.into(),
        qty: q,
        price: p,
        fee: 0.1,
        realized: if buy { 0.0 } else { 5.0 },
        rebalance,
        mode: "demo".into(),
    }
}

#[test]
fn the_fills_of_a_rebalance_are_one_card_with_a_table() {
    let evs: Vec<AlertEvent> = vec![
        AlertEvent::trade("1", line("Momentum", true, "BTC", 0.01, 60_000.0, true)),
        AlertEvent::trade("2", line("Momentum", false, "ETH", 0.5, 3_000.0, true)),
        AlertEvent::trade("3", line("Momentum", true, "BTC", 0.01, 62_000.0, true)),
        AlertEvent::new(AlertKind::DataStale, "s", "quotes stale for 11 min"),
    ];
    let cards = cards_of(&evs);
    assert_eq!(cards.len(), 2, "one trade card, one stale card");
    let t = &cards[0];
    assert_eq!(t.title, "Rebalance · Momentum");
    assert_eq!(t.summary.as_deref(), Some("2 trades: bought $1,220.00, sold $1,500.00."));
    let table = t.table.as_ref().unwrap();
    assert_eq!(table.rows.len(), 2, "the two BTC buys are one line");
    assert_eq!(table.rows[0], vec!["Sell", "ETH", "$1,500", "$3,000.00"]);
    assert_eq!(table.rows[1], vec!["Buy", "BTC", "$1,220", "$61,000.00"]);
    let html = render_post(&cards, AlertFormat::Telegram, 4000);
    assert!(html.contains("<pre>Side Coin  Value      Price\nSell ETH  $1,500  $3,000.00\nBuy  BTC  $1,220 $61,000.00</pre>"), "{html}");
    assert!(html.contains("Realised  +$5.00 🟢"));
    assert!(html.contains("<b>📡 Market data stale</b>\nQuotes stale for 11 min"));
}

#[test]
fn a_single_trade_is_a_short_card() {
    let ev = AlertEvent::trade("1", line("Swing", false, "SOL", 3.0, 150.0, false));
    assert_eq!(ev.category(), Some(AlertCategory::Trades));
    let html = render_post(&cards_of(&[ev]), AlertFormat::Telegram, 4000);
    assert!(html.starts_with("<b>🔴 Swing sold SOL</b>\n<pre>Amount      3 SOL\nPrice     $150.00\n"), "{html}");
    assert!(html.contains("<i>Demo: virtual money at the venue</i>"));
}

#[test]
fn a_long_post_is_fitted_without_cutting_a_tag() {
    let fills: Vec<AlertEvent> = (0..300)
        .map(|i| AlertEvent::trade(i.to_string(), line("Big", i % 2 == 0, &format!("C{i}"), 1.0, 10.0 + i as f64, true)))
        .collect();
    let mut evs = fills;
    for i in 0..40 {
        evs.push(AlertEvent::new(AlertKind::Event, format!("e{i}"), "x".repeat(200)).titled(format!("Note {i}")));
    }
    let html = compose(&tg(""), &evs, 3);
    assert!(html.chars().count() <= 4000, "{}", html.chars().count());
    assert!(html.contains(" more\n") || html.contains(" more</pre>"), "the table says how many rows were left out");
    assert!(html.contains("more alert(s) in the app"));
    assert_eq!(html.matches("<pre>").count(), html.matches("</pre>").count());
    assert_eq!(html.matches("<b>").count(), html.matches("</b>").count());
}

#[test]
fn the_compose_footer_carries_the_prefix_and_the_held_back_count() {
    let ev = AlertEvent::new(AlertKind::KillSwitch, "k", "engaged by hand. Only closing orders pass.");
    let html = compose(&tg(""), &[ev], 2);
    assert_eq!(
        html,
        "<b>🚨 Kill switch</b>\nEngaged by hand. Only closing orders pass.\n<i>2 more held back by the hourly limit · Pythia</i>"
    );
}

#[test]
fn telegram_bodies_use_html_parse_mode_and_too_long_falls_back_to_plain() {
    let b = AlertFormat::Telegram.body("<b>hi</b>");
    assert_eq!(b["parse_mode"], "HTML");
    assert_eq!(b["disable_web_page_preview"], true);
    let long = format!("<b>{}</b>", "x".repeat(5000));
    let b = AlertFormat::Telegram.body(&long);
    assert!(b.get("parse_mode").is_none());
    assert!(!b["text"].as_str().unwrap().contains("<b>"));
}

#[test]
fn quiet_hours_run_over_midnight_in_berlin_time() {
    let q = QuietHours::default();
    // October 15 2026: summer time, UTC+2.
    assert!(q.contains(utc(2026, 10, 15, 22, 30)), "00:30 Berlin");
    assert!(q.contains(utc(2026, 10, 15, 21, 0)), "23:00 Berlin starts it");
    assert!(!q.contains(utc(2026, 10, 15, 20, 59)), "22:59 Berlin");
    assert!(q.contains(utc(2026, 10, 16, 4, 59)), "06:59 Berlin");
    assert!(!q.contains(utc(2026, 10, 16, 5, 0)), "07:00 Berlin ends it");
    // December: winter time, UTC+1.
    assert!(q.contains(utc(2026, 12, 1, 22, 0)), "23:00 Berlin in winter");
    assert!(!q.contains(utc(2026, 12, 1, 21, 30)), "22:30 Berlin in winter");
    // Off, or a window of no length.
    let off = QuietHours { enabled: false, ..QuietHours::default() };
    assert!(!off.contains(utc(2026, 10, 15, 22, 30)));
    let none = QuietHours { start: "07:00".into(), end: "07:00".into(), ..QuietHours::default() };
    assert!(!none.contains(utc(2026, 10, 15, 5, 0)));
    // A daytime window.
    let day = QuietHours { start: "12:00".into(), end: "14:00".into(), ..QuietHours::default() };
    assert!(day.contains(utc(2026, 10, 15, 10, 30)) && !day.contains(utc(2026, 10, 15, 12, 30)));
}

#[test]
fn settings_switch_categories_and_check_what_they_are_given() {
    let mut s = AlertSettings::default();
    assert!(AlertCategory::ALL.iter().all(|c| s.enabled(*c)), "everything on by default");
    let patch: AlertSettingsPatch = serde_json::from_value(serde_json::json!({
        "categories": {"trades": false, "daily_pnl": false},
        "quietHours": {"start": "22:30"},
        "bigMoves": {"hourPct": 4.5}
    }))
    .unwrap();
    s.apply(patch).unwrap();
    assert!(!s.enabled(AlertCategory::Trades) && !s.enabled(AlertCategory::DailyPnl));
    assert!(s.enabled(AlertCategory::Risk));
    assert_eq!(s.quiet_hours.start, "22:30");
    assert_eq!(s.quiet_hours.end, "07:00");
    assert_eq!(s.big_moves.hour_pct, 4.5);
    // All or nothing: a bad field leaves everything as it was.
    let before = s.clone();
    let bad: AlertSettingsPatch =
        serde_json::from_value(serde_json::json!({"categories": {"risk": false, "nope": true}})).unwrap();
    assert!(s.apply(bad).unwrap_err().contains("nope"));
    let bad: AlertSettingsPatch = serde_json::from_value(serde_json::json!({"quietHours": {"end": "25:00"}})).unwrap();
    assert!(s.apply(bad).is_err());
    let bad: AlertSettingsPatch = serde_json::from_value(serde_json::json!({"quietHours": {"timezone": "Mars/Base"}})).unwrap();
    assert!(s.apply(bad).is_err());
    let bad: AlertSettingsPatch = serde_json::from_value(serde_json::json!({"bigMoves": {"dayPct": 0}})).unwrap();
    assert!(s.apply(bad).is_err());
    assert_eq!(s, before);
    assert!(serde_json::from_value::<AlertSettingsPatch>(serde_json::json!({"color": "red"})).is_err());
    // The view lists every category with its switch.
    let v = s.view(utc(2026, 10, 15, 12, 0));
    assert_eq!(v["categories"].as_array().unwrap().len(), 14);
    assert_eq!(v["categories"][0]["id"], "trades");
    assert_eq!(v["categories"][0]["on"], false);
    assert_eq!(v["quietNow"], false);
    // Saved and read back.
    let back: AlertSettings = serde_json::from_str(&serde_json::to_string(&s).unwrap()).unwrap();
    assert_eq!(back, s);
    let empty: AlertSettings = serde_json::from_str("{}").unwrap();
    assert_eq!(empty, AlertSettings::default());
}

#[test]
fn sorting_follows_switches_mute_and_quiet_hours_and_urgent_always_goes() {
    let mut s = AlertSettings::default();
    s.categories.insert("venue".into(), false);
    let night = utc(2026, 10, 15, 23, 0);
    let day = utc(2026, 10, 15, 10, 0);
    let evs = || {
        vec![
            AlertEvent::new(AlertKind::DataStale, "a", "stale"),
            AlertEvent::new(AlertKind::KillSwitch, "b", "engaged"),
            AlertEvent::new(AlertKind::AutopilotStarted, "c", "started"),
            AlertEvent::new(AlertKind::Event, "d", "a lab job").in_category(AlertCategory::Studies).urgent(),
        ]
    };
    let r = sort_events(evs(), &s, false, day);
    assert_eq!(r.off, 1, "venue is off");
    assert_eq!(r.send.len(), 3);
    let r = sort_events(evs(), &s, false, night);
    assert_eq!(r.send.iter().map(|e| e.kind).collect::<Vec<_>>(), vec![AlertKind::KillSwitch, AlertKind::Event]);
    assert_eq!(r.quiet.len(), 1);
    let r = sort_events(evs(), &s, true, day);
    assert_eq!(r.muted.len(), 1);
    assert_eq!(r.send.len(), 2);
    // The kill switch goes out even with its category off.
    s.categories.insert("risk".into(), false);
    assert_eq!(sort_events(evs(), &s, false, day).send[0].kind, AlertKind::KillSwitch);
}

#[test]
fn the_morning_note_lists_what_was_held() {
    let s = AlertSettings::default();
    let held = vec![(utc(2026, 10, 15, 22, 5), "Momentum started".to_string()), (utc(2026, 10, 16, 1, 40), "BTC +4.1 % in 1 h".into())];
    let ev = overnight_event(&held, 2, &s);
    let html = compose(&tg(""), &[ev], 0);
    assert!(html.starts_with("<b>🌙 Quiet hours are over</b>\n4 alerts were held back from 23:00 to 07:00. Urgent ones went out at once."), "{html}");
    assert!(html.contains("<pre>Time  Alert\n00:05 Momentum started\n03:40 BTC +4.1 % in 1 h\n+2 more</pre>"), "{html}");
}

#[test]
fn big_moves_need_history_and_are_said_once() {
    let mut w = MoveWatch::default();
    let t0 = utc(2026, 10, 15, 10, 0);
    let coin = |v: f64| MoveInput {
        key: "crypto:BTC/USD".into(),
        label: "BTC".into(),
        held_by: "Momentum".into(),
        subject: MoveSubject::Coin,
        value: v,
    };
    // 30 minutes of history is not an hour: no alert even for a jump.
    for m in 0..=30 {
        let v = if m == 30 { 105.0 } else { 100.0 };
        assert!(w.check(&[coin(v)], 3.0, 8.0, t0 + m * 60_000).is_empty());
    }
    for m in 31..=60 {
        let out = w.check(&[coin(100.0)], 3.0, 8.0, t0 + m * 60_000);
        assert!(out.is_empty());
    }
    let out = w.check(&[coin(104.0)], 3.0, 8.0, t0 + 61 * 60_000);
    assert_eq!(out.len(), 1);
    let ev = &out[0];
    assert_eq!(ev.kind, AlertKind::BigMove);
    assert_eq!(ev.category(), Some(AlertCategory::BigMoves));
    assert_eq!(ev.title.as_deref(), Some("BTC +4.0 % in 1 h"));
    assert_eq!(ev.emoji.as_deref(), Some("📈"));
    assert!(!ev.is_urgent());
    // Still up: not said again; up another full threshold: said again.
    assert!(w.check(&[coin(105.0)], 3.0, 8.0, t0 + 62 * 60_000).is_empty());
    let out = w.check(&[coin(108.0)], 3.0, 8.0, t0 + 63 * 60_000);
    assert_eq!(out.len(), 1);
    assert!(out[0].title.as_deref().unwrap().starts_with("BTC +8.0 %"));
}

#[test]
fn an_autopilot_falling_twice_the_threshold_is_urgent() {
    let mut w = MoveWatch::default();
    let t0 = utc(2026, 10, 15, 10, 0);
    let eq = |v: f64| MoveInput {
        key: "ap:a1".into(),
        label: "Momentum".into(),
        held_by: String::new(),
        subject: MoveSubject::Equity,
        value: v,
    };
    for m in 0..=60 {
        w.check(&[eq(1000.0)], 3.0, 8.0, t0 + m * 60_000);
    }
    let out = w.check(&[eq(930.0)], 3.0, 8.0, t0 + 61 * 60_000);
    assert_eq!(out.len(), 1);
    assert_eq!(out[0].title.as_deref(), Some("Momentum equity -7.0 % in 1 h"));
    assert_eq!(out[0].emoji.as_deref(), Some("📉"));
    assert!(out[0].is_urgent(), "7 % is more than twice 3 %");
}

#[test]
fn photo_bodies_are_multipart_with_the_caption_in_html() {
    let png = [0x89, b'P', b'N', b'G', 1, 2, 3];
    let b = photo_body("42", "<b>Daily</b>", &png, "XYZ");
    let s = String::from_utf8_lossy(&b);
    assert!(s.starts_with("--XYZ\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n42\r\n"));
    assert!(s.contains("name=\"caption\"\r\n\r\n<b>Daily</b>\r\n"));
    assert!(s.contains("name=\"parse_mode\"\r\n\r\nHTML\r\n"));
    assert!(s.contains("filename=\"chart.png\"\r\nContent-Type: image/png\r\n\r\n"));
    assert!(s.ends_with("\r\n--XYZ--\r\n"));
    let cfg = tg("");
    assert_eq!(cfg.photo_url(), "https://api.telegram.org/bot1:x/sendPhoto");
}

#[test]
fn plain_takes_the_markup_out() {
    assert_eq!(plain("<b>🚨 Kill &amp; switch</b>\n<pre>a &lt; b</pre>"), "🚨 Kill & switch\na < b");
}
