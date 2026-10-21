//! The language of the chat: every engine message in English and German, the
//! German number and date formats, and the setting's round trip.

use super::i18n::*;
use super::{
    card, compose_in, overnight_event, test_event, AlertCategory, AlertConfig, AlertEvent, AlertFormat, AlertKind,
    AlertSettings, AlertSettingsPatch, Card, TradeLine,
};

/// English words that must not turn up in a German message. Established
/// trading words (Stop, Take-Profit, Drawdown, Paper, Demo, Live, Coin,
/// Orders, Autopilot) are German enough and not listed.
const ENGLISH: &[&str] = &[
    "the", "and", "of", "is", "are", "to", "at", "on", "by", "from", "with", "for", "its", "was", "were", "now",
    "stopped", "started", "finished", "reached", "equity", "fees", "fee", "trades", "trade", "rules", "refused", "quiet",
    "hours", "held", "more", "price", "value", "amount", "change", "ago", "muted", "range", "outside", "message",
    "realised", "bought", "sold", "buy", "sell", "side", "alert", "alerts", "loss", "floor", "peak", "gain", "mode",
    "venue", "capital", "split", "books", "inputs", "market", "data", "fresh", "again", "released", "engaged",
    "book", "pair", "pairs", "positions", "differ", "differed", "page", "test", "example",
    "categories", "off", "big", "move", "time", "ends", "runs", "until", "closed", "left", "open", "paused", "idle",
    "still", "running", "strategies", "waiting", "otherwise", "trailing", "target", "max", "today", "limit", "entries",
    "quotes", "candles", "within", "only", "orders", "in", "a",
];

/// The English words in a post. "in", "Orders" and "Test" are German as well
/// and pass.
fn english_words(text: &str) -> Vec<String> {
    let allowed_in_german = ["in", "orders", "test"];
    plain(text)
        .split(|c: char| !c.is_alphabetic())
        .filter(|w| !w.is_empty())
        .map(|w| w.to_lowercase())
        .filter(|w| ENGLISH.contains(&w.as_str()) && !allowed_in_german.contains(&w.as_str()))
        .collect()
}

fn plain(s: &str) -> String {
    card::plain(s)
}

fn messages() -> Vec<Msg> {
    let day = 1_792_072_800_000; // Thu 15 Oct 2026, 14:00 UTC
    vec![
        Msg::AutopilotStarted {
            name: "Momentum".into(),
            mode: ApMode::Paper,
            place: Place::Portfolio,
            capital: 10_000.0,
            split: Some(vec![(AssetClass::Crypto, 0.7), (AssetClass::UsShares, 0.3)]),
            books: vec!["TSMOM".into(), "Breakout".into()],
            rules: Rules {
                capital: 10_000.0,
                max_loss_pct: Some(5.0),
                max_loss_usd: Some(400.0),
                trailing_pct: Some(3.5),
                take_profit_pct: Some(10.0),
                lock: true,
                end_ms: Some(day),
            },
        },
        Msg::AutopilotHalted {
            name: "Momentum".into(),
            finished: false,
            why: StopWhy::Trailing { equity: 9_412.3, pct: 3.0, peak: 9_700.0, floor: 9_409.0 },
            equity: 9_412.3,
            pnl: -587.7,
            pnl_pct: -5.877,
            vs_btc: Some(-1.2),
            trades: 14,
            fees: 12.5,
            foot: Some(HaltFoot::Closed(3)),
        },
        Msg::DataStale { mins: 12, quotes: Some("BTC, ETH".into()), candles: Some("SOL".into()) },
        Msg::DataFresh,
        Msg::DailyLoss { loss_pct: 3.2, limit_pct: 3.0 },
        Msg::KillDrawdown { equity: 9_100.0, dd_pct: 9.1, limit_pct: 9.0 },
        Msg::KillByHand,
        Msg::KillReleased,
        Msg::Reconcile { venue: "Kraken".into(), changes: 2 },
        Msg::ReconcileDemo { mismatches: 1 },
        Msg::OrderRejects { n: 4, demo: true, symbol: "BTC/USD".into(), reason: "HTTP 403".into() },
        Msg::DriftOn { model: DriftModel::Vol, total: 12, hits: vec![("rv_24h".into(), 7.0), ("funding".into(), 6.0)] },
        Msg::DriftOff { model: DriftModel::Picks },
        Msg::BigMove {
            of: MoveOf::Coin,
            label: "BTC".into(),
            held_by: "Momentum".into(),
            window: "1 h",
            now: 61_234.5,
            then: 59_000.0,
            pct: 3.79,
        },
        Msg::BigMove {
            of: MoveOf::Equity,
            label: "Momentum".into(),
            held_by: String::new(),
            window: "24 h",
            now: 9_000.0,
            then: 10_000.0,
            pct: -10.0,
        },
        Msg::Test { on: 12, total: 14, quiet: Some(("23:00".into(), "07:00".into())), hour_pct: 2.5, day_pct: 8.0 },
        Msg::Overnight {
            fills: vec![HeldFills {
                book: "Momentum".into(),
                rebalance: true,
                buys: 3,
                sells: 9,
                bought: 567.0,
                sold: 1_234.0,
                fees: 2.1,
                realized: 12.3,
            }],
            others: vec![HeldGroup { kind: AlertKind::BigMove, category: None, n: 2, last: format!("BTC {day}") }],
            start: "23:00".into(),
            end: "07:00".into(),
            timezone: "Europe/Berlin".into(),
        },
    ]
}

fn tg() -> AlertConfig {
    let mut c = AlertConfig::new("https://example.invalid/hook", AlertFormat::Telegram);
    c.prefix = String::new();
    c
}

#[test]
fn every_engine_message_renders_in_both_languages() {
    for m in messages() {
        let ev = AlertEvent::from_msg("k", m.clone());
        let mut seen = Vec::new();
        for lang in Lang::ALL {
            let card = ev.card_in(lang);
            assert!(!card.title.trim().is_empty(), "{m:?} in {lang:?} has no title");
            assert!(card.summary.as_deref().is_some_and(|s| !s.trim().is_empty()), "{m:?} in {lang:?} has no summary");
            assert!(!m.text(lang).trim().is_empty(), "{m:?} in {lang:?} has no text");
            let post = compose_in(&tg(), std::slice::from_ref(&ev), 0, lang);
            assert!(!post.contains('\u{2014}'), "no em dash: {post}");
            seen.push(post);
        }
        assert_ne!(seen[0], seen[1], "{m:?}: the German post is the English one");
        let left = english_words(&seen[1]);
        assert!(left.is_empty(), "English left in the German post of {m:?}: {left:?}\n{}", plain(&seen[1]));
    }
}

/// Every message in both languages, for a read:
/// `cargo test -p pythia-core show_every_message -- --ignored --nocapture`.
#[test]
#[ignore]
fn show_every_message() {
    for m in messages() {
        let ev = AlertEvent::from_msg("k", m);
        for lang in Lang::ALL {
            println!("{}\n", plain(&compose_in(&tg(), std::slice::from_ref(&ev), 0, lang)));
        }
    }
}

#[test]
fn the_english_post_is_unchanged_by_the_catalog() {
    // The kill switch from the drawdown brake, as it read before the catalog.
    let ev = AlertEvent::from_msg("kill:on", Msg::KillDrawdown { equity: 9100.0, dd_pct: 9.1, limit_pct: 9.0 });
    assert_eq!(ev.kind, AlertKind::KillSwitch);
    assert_eq!(
        ev.text,
        "tripped by the drawdown brake: equity 9100.00 is 9.1 % below its peak, limit 9.0 %. Only closing orders pass until it is released."
    );
    let c = ev.card();
    assert_eq!(c.title, "Kill switch");
    assert!(c.summary.unwrap().starts_with("Tripped by the drawdown brake"));
    let de = ev.card_in(Lang::De);
    assert_eq!(de.title, "Not-Aus");
    assert_eq!(
        de.summary.as_deref(),
        Some("Von der Drawdown-Bremse ausgelöst: Wert 9.100,00 $ liegt 9,1 % unter dem Höchststand, Grenze 9,0 %. Bis zur Freigabe gehen nur schließende Orders durch.")
    );
}

#[test]
fn german_numbers_dates_and_words() {
    let de = Lang::De;
    assert_eq!(num(de, 12_345.678, 2), "12.345,68");
    assert_eq!(usd(de, 1_234.56), "1.234,56 $");
    assert_eq!(usd(de, -587.7), "-587,70 $");
    assert_eq!(signed_usd(de, 12.3), "+12,30 $");
    assert_eq!(signed_usd(de, -12.3), "-12,30 $");
    assert_eq!(signed_pct(de, 3.2, 1), "+3,2 %");
    assert_eq!(signed_pct(de, -0.004, 2), "+0,00 %");
    assert_eq!(signed_pct(de, f64::NAN, 2), "k. A.");
    assert_eq!(price(de, 61_234.5), "61.234,50 $");
    assert_eq!(price(de, 0.012345), "0,0123 $");
    assert_eq!(qty(de, 0.5), "0,5");
    assert_eq!(qty(de, 1234.0), "1.234");
    assert_eq!(pts(de, 1.234), "+1,23 Pkt.");
    assert_eq!(cents(de, -0.001), "0,00 $");
    assert_eq!(cents(de, 9_500.0), "9.500,00 $");
    assert_eq!(short_pct(de, 2.5), "2,5");
    // English stays as it was.
    assert_eq!(usd(Lang::En, 1_234.56), "$1,234.56");
    assert_eq!(signed_pct(Lang::En, 3.2, 1), "+3.2 %");
    assert_eq!(cents(Lang::En, 9_500.0), "$9,500.00");

    let d = chrono::NaiveDate::from_ymd_opt(2026, 10, 15).unwrap();
    assert_eq!(day_label(de, &d), "Do 15. Okt");
    assert_eq!(day_label(Lang::En, &d), "Thu 15 Oct");
    assert_eq!(day_label(de, &chrono::NaiveDate::from_ymd_opt(2026, 3, 2).unwrap()), "Mo 2. Mär");
    // 14:00 UTC in October is 16:00 in Berlin; in January 15:00.
    assert_eq!(berlin_when(de, 1_792_072_800_000), "Do 15. Okt, 16:00");
    assert_eq!(berlin_when(de, 1_768_485_600_000), "Do 15. Jan, 15:00");
}

#[test]
fn trades_and_rebalances_in_german() {
    let line = |buy: bool, sym: &str, q: f64, p: f64, reb: bool| TradeLine {
        book: "Momentum".into(),
        buy,
        symbol: sym.into(),
        qty: q,
        price: p,
        fee: 1.5,
        realized: if buy { 0.0 } else { 12.3 },
        rebalance: reb,
        mode: "paper".into(),
        experiment: false,
    };
    let one = line(true, "BTC", 0.01, 61_234.5, false);
    let html = compose_in(&tg(), &[AlertEvent::trade("t", one)], 0, Lang::De);
    assert!(html.contains("Momentum kaufte BTC"), "{html}");
    assert!(html.contains("Menge") && html.contains("0,01 BTC") && html.contains("61.234,50 $"), "{html}");
    assert!(html.contains("<i>Paper</i>"), "{html}");
    assert!(english_words(&html).is_empty(), "{html}");

    let evs: Vec<AlertEvent> = [line(false, "ETH", 2.0, 3_000.0, true), line(true, "SOL", 10.0, 150.0, true)]
        .into_iter()
        .map(|t| AlertEvent::trade("r", t))
        .collect();
    let html = compose_in(&tg(), &evs, 0, Lang::De);
    let text = plain(&html);
    assert!(text.contains("Umschichtung · Momentum"), "{text}");
    assert!(text.contains("2 Ausführungen: gekauft für 1.500,00 $, verkauft für 6.000,00 $."), "{text}");
    assert!(text.contains("Richtung") && text.contains("Verkauf") && text.contains("Kauf"), "{text}");
    // Sells first.
    assert!(text.find("Verkauf").unwrap() < text.find("Kauf ").unwrap(), "{text}");
    assert!(text.contains("Realisiert") && text.contains("Gebühren"), "{text}");
    assert!(english_words(&html).is_empty(), "{text}");
    // The English card reads as before.
    let en = plain(&compose_in(&tg(), &evs, 0, Lang::En));
    assert!(en.contains("Rebalance · Momentum") && en.contains("2 fills: bought $1,500.00, sold $6,000.00."), "{en}");
}

#[test]
fn the_small_words_of_a_post_follow_the_language() {
    let ev = AlertEvent::from_msg("k", Msg::KillByHand);
    let html = compose_in(&tg(), std::slice::from_ref(&ev), 3, Lang::De);
    assert!(html.contains("3 weitere vom Stundenlimit zurückgehalten"), "{html}");
    // Lines that had to be left out, and cards left out.
    let mut night = super::Overnight::default();
    for i in 0..150 {
        let t = TradeLine {
            book: format!("Autopilot mit einem langen Namen {i}"),
            buy: i % 2 == 0,
            symbol: "BTC".into(),
            qty: 0.01,
            price: 60_000.0,
            fee: 0.12,
            realized: 0.0,
            rebalance: true,
            mode: "demo".into(),
            experiment: false,
        };
        night.hold(&AlertEvent::trade(i.to_string(), t), 1_792_072_800_000, Lang::De);
    }
    let s = AlertSettings::default();
    let html = compose_in(&tg(), &[overnight_event(&night, &s)], 0, Lang::De);
    assert!(html.contains("Ruhezeit vorbei") && html.contains("150 Meldungen wurden von 23:00 bis 07:00"), "{html}");
    assert!(html.chars().count() <= 4000, "{html}");
    assert!(card::plain(&html).lines().any(|l| l.starts_with('+') && l.ends_with(" weitere")), "{html}");
    let last = card::plain(&html).lines().filter(|l| l.starts_with("Autopilot mit")).last().unwrap().to_string();
    assert!(last.ends_with("Gebühren 0,12 $"), "whole lines only: {last}");
    let many: Vec<Card> = (0..40).map(|_| ev.card_in(Lang::De)).map(|c| c.summary("x".repeat(200))).collect();
    let post = card::render_post(&many, AlertFormat::Telegram, 1000);
    assert!(post.contains("weitere in der App"), "{post}");
}

#[test]
fn the_halt_footer_is_the_first_thing_said_in_either_language() {
    let foot = HaltFoot::LeftOpen(2);
    assert_eq!(
        foot.text(Lang::En),
        "Left its 2 position(s) open, now managed by their strategies' stops; its P&L counts them at their price now."
    );
    assert!(foot.text(Lang::De).starts_with("2 Positionen offen gelassen"));
    assert_eq!(HaltFoot::Closed(1).text(Lang::De), "1 Position geschlossen.");
    for f in [
        HaltFoot::Closed(2),
        HaltFoot::AtVenue(1),
        HaltFoot::WaitPrice(2),
        HaltFoot::Stuck(1),
        HaltFoot::WaitOtherBook(2),
        HaltFoot::Refused(1),
        HaltFoot::Retrying(3),
        HaltFoot::LeftOpen(3),
        HaltFoot::Paused(vec!["TSMOM".into()]),
        HaltFoot::Still(vec!["TSMOM (in Carry)".into()]),
        HaltFoot::Idle(vec!["TSMOM".into()]),
    ] {
        let de = f.text(Lang::De);
        assert!(english_words(&de).is_empty(), "{de}");
        assert_ne!(de, f.text(Lang::En));
    }
    for why in [
        StopWhy::ByYou,
        StopWhy::TakeProfit { pct: 10.0, equity: 11_000.0, target: 11_000.0 },
        StopWhy::MaxLossPct { pct: 5.0, equity: 9_500.0, floor: 9_500.0 },
        StopWhy::MaxLossUsd { usd: 400.0, equity: 9_600.0, floor: 9_600.0 },
        StopWhy::Trailing { equity: 9_700.0, pct: 3.0, peak: 10_000.0, floor: 9_700.0 },
        StopWhy::LockedProfit { equity: 10_500.0, floor: 10_500.0 },
        StopWhy::EndTime,
    ] {
        let de = why.text(Lang::De);
        assert!(english_words(&de).is_empty(), "{de}");
    }
    assert_eq!(
        StopWhy::MaxLossPct { pct: 5.0, equity: 9_500.0, floor: 9_500.0 }.text(Lang::En),
        "max loss of 5 % reached (equity $9,500.00, floor $9,500.00)"
    );
}

#[test]
fn the_language_setting_round_trips_and_the_environment_wins() {
    let mut s = AlertSettings::default();
    assert_eq!(s.language, Lang::En, "English unless set");
    let patch: AlertSettingsPatch = serde_json::from_str(r#"{"language": "de"}"#).unwrap();
    s.apply(patch).unwrap();
    assert_eq!(s.language, Lang::De);
    // Saved with the state and read back.
    let saved = serde_json::to_string(&s).unwrap();
    assert!(saved.contains(r#""language":"de""#), "{saved}");
    let back: AlertSettings = serde_json::from_str(&saved).unwrap();
    assert_eq!(back, s);
    // The view the app and the lab read.
    let v = s.view_with(0, None);
    assert_eq!(v["language"], "de");
    assert!(v["languageEnv"].is_null());
    assert_eq!(v["languages"][1]["label"], "Deutsch");
    let v = s.view_with(0, Some(Lang::En));
    assert_eq!(v["languageEnv"], "en");
    // A wrong value is refused, the rest stays.
    let bad: AlertSettingsPatch = serde_json::from_str(r#"{"language": "fr"}"#).unwrap();
    assert!(s.clone().apply(bad).unwrap_err().contains("en or de"));
    // An old save without the field, or one with a stray value, is English.
    let old: AlertSettings = serde_json::from_str(r#"{"categories": {"trades": false}}"#).unwrap();
    assert_eq!(old.language, Lang::En);
    assert!(!old.enabled(AlertCategory::Trades));
    let odd: AlertSettings = serde_json::from_str(r#"{"language": "klingon"}"#).unwrap();
    assert_eq!(odd.language, Lang::En);
    // PYTHIA_ALERT_LANG over the setting.
    let env = |k: &str| match k {
        "PYTHIA_TELEGRAM_BOT_TOKEN" => Some("123:abc".to_string()),
        "PYTHIA_TELEGRAM_CHAT_ID" => Some("42".to_string()),
        "PYTHIA_ALERT_LANG" => Some(" DE ".to_string()),
        _ => None,
    };
    let cfg = AlertConfig::from_lookup(env).unwrap();
    assert_eq!(cfg.lang, Some(Lang::De));
    assert_eq!(cfg.lang_for(&AlertSettings::default()), Lang::De);
    let no_env = AlertConfig::from_lookup(|k| env(k).filter(|_| k != "PYTHIA_ALERT_LANG")).unwrap();
    assert_eq!(no_env.lang, None);
    assert_eq!(no_env.lang_for(&s), Lang::De);
    assert_eq!(no_env.lang_for(&AlertSettings::default()), Lang::En);
    assert_eq!(Lang::parse("Deutsch"), Some(Lang::De));
    assert_eq!(Lang::parse("en-GB"), Some(Lang::En));
    assert_eq!(Lang::parse("fr"), None);
}

#[test]
fn the_test_message_and_held_titles_use_the_language() {
    let s = AlertSettings { language: Lang::De, ..Default::default() };
    let ev = test_event(&s);
    let de = plain(&compose_in(&tg(), std::slice::from_ref(&ev), 0, Lang::De));
    assert!(de.contains("Testnachricht") && de.contains("Ruhezeit") && de.contains("23:00 bis 07:00"), "{de}");
    assert!(de.contains("+1.234,50 $ +1,23 %"), "{de}");
    let en = plain(&compose_in(&tg(), std::slice::from_ref(&ev), 0, Lang::En));
    assert!(en.contains("Test message") && en.contains("+$1,234.50 +1.23 %"), "{en}");
    assert_eq!(ev.title_text_in(Lang::De), "Testnachricht");
    // A lab event keeps the words it came with; only a missing title is a label.
    let lab = AlertEvent::new(AlertKind::Event, "e", "Neuer Coin bei Kraken").titled("Neu gelistet");
    assert_eq!(lab.card_in(Lang::De).title, "Neu gelistet");
    assert_eq!(AlertEvent::new(AlertKind::DataStale, "s", "x").title_text_in(Lang::De), "Marktdaten veraltet");
}
