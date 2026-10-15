//! The crypto universe: which coins the engine quotes, charts and trades.
//!
//! [`COINS`] is every coin Pythia knows how to fetch, with the venues that
//! list it. The universe the engine runs is a selection from it, set by the
//! operator (see [`configured`]):
//!
//! * `PYTHIA_CRYPTO_UNIVERSE`: a list of coins (`BTC, ETH, BONK` or
//!   `BTC/USD ...`, commas, spaces or new lines, `#` starts a comment) or one
//!   of the presets `default`, `alpaca`, `lab20`, `memes`; a preset and coins
//!   can be mixed (`lab20 BONK WIF`)
//! * else `PYTHIA_CRYPTO_UNIVERSE_FILE`: a file in the same format
//! * else `default`: every pair the Alpaca paper account trades that is not a
//!   stablecoin or gold (32 coins), plus the five coins of the research lab's
//!   20-coin universe Alpaca does not list (TRX, SUI, NEAR, ATOM, XLM), so the
//!   lab books and any position already held keep their markets. Crypto demo
//!   orders skip those five as before (`Engine::demo_not_listed`).
//!
//! Stablecoins and gold are never part of the universe: no strategy has
//! anything to earn on a peg. A coin outside [`COINS`] is accepted (a plain
//! ticker of 2 to 10 letters and digits) and served by the sources whose
//! requests tolerate a symbol they do not list (Alpaca, Coinbase, Bybit, OKX);
//! Kraken and Binance answer a whole multi-coin request with an error when one
//! symbol is unknown, so they only get the coins marked here.

use std::sync::OnceLock;

use crate::feeds::FeedSource;

/// One coin and where it trades. `kraken` is (pair to request, the key
/// Kraken answers with): Kraken renames some pairs in its replies (XBTUSD
/// comes back as XXBTZUSD, DOGE trades as XDG), so the reply key is matched
/// exactly rather than guessed.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Coin {
    /// Our symbol, `BTC/USD`.
    pub symbol: &'static str,
    pub kraken: Option<(&'static str, &'static str)>,
    /// A `<BASE>USDT` spot market on Binance.
    pub binance: bool,
    /// Tradable on the Alpaca paper account.
    pub alpaca: bool,
    /// A memecoin: the study's separate sleeve with its own small risk budget.
    pub meme: bool,
    /// A rough price for the simulator before the first live quote. Never a
    /// mark: the engine trades a market only once a feed has priced it.
    pub seed: f64,
}

const fn c(symbol: &'static str, kraken: Option<(&'static str, &'static str)>, binance: bool, alpaca: bool, meme: bool, seed: f64) -> Coin {
    Coin { symbol, kraken, binance, alpaca, meme, seed }
}

/// Every coin Pythia knows. The first twenty are the research lab's universe
/// (`marketdata::KRAKEN_PAIRS`), in its order.
pub const COINS: &[Coin] = &[
    c("BTC/USD", Some(("XBTUSD", "XXBTZUSD")), true, true, false, 67_250.0),
    c("ETH/USD", Some(("ETHUSD", "XETHZUSD")), true, true, false, 3_520.0),
    c("SOL/USD", Some(("SOLUSD", "SOLUSD")), true, true, false, 168.4),
    c("XRP/USD", Some(("XRPUSD", "XXRPZUSD")), true, true, false, 0.52),
    c("DOGE/USD", Some(("XDGUSD", "XDGUSD")), true, true, true, 0.0934),
    c("ADA/USD", Some(("ADAUSD", "ADAUSD")), true, true, false, 0.45),
    c("AVAX/USD", Some(("AVAXUSD", "AVAXUSD")), true, true, false, 27.5),
    c("LINK/USD", Some(("LINKUSD", "LINKUSD")), true, true, false, 14.3),
    c("LTC/USD", Some(("LTCUSD", "XLTCZUSD")), true, true, false, 72.0),
    c("DOT/USD", Some(("DOTUSD", "DOTUSD")), true, true, false, 6.2),
    c("BCH/USD", Some(("BCHUSD", "BCHUSD")), true, true, false, 310.4),
    c("TRX/USD", Some(("TRXUSD", "TRXUSD")), true, false, false, 0.3357),
    c("SUI/USD", Some(("SUIUSD", "SUIUSD")), true, false, false, 1.18),
    c("NEAR/USD", Some(("NEARUSD", "NEARUSD")), true, false, false, 5.11),
    c("ATOM/USD", Some(("ATOMUSD", "ATOMUSD")), true, false, false, 1.79),
    c("UNI/USD", Some(("UNIUSD", "UNIUSD")), true, true, false, 8.55),
    c("AAVE/USD", Some(("AAVEUSD", "AAVEUSD")), true, true, false, 180.0),
    c("XLM/USD", Some(("XLMUSD", "XXLMZUSD")), true, false, false, 0.2126),
    c("PEPE/USD", Some(("PEPEUSD", "PEPEUSD")), true, true, true, 0.000004266),
    c("FIL/USD", Some(("FILUSD", "FILUSD")), true, true, false, 1.159),
    // The rest of what the Alpaca paper account trades. HYPE, ONDO and SKY
    // are left off Binance and HYPE and SKY off Kraken: listed or not, a wrong
    // "listed" would fail the whole multi-coin request there.
    c("ARB/USD", Some(("ARBUSD", "ARBUSD")), true, true, false, 0.40),
    c("BAT/USD", Some(("BATUSD", "BATUSD")), true, true, false, 0.15),
    c("BONK/USD", Some(("BONKUSD", "BONKUSD")), true, true, true, 0.000015),
    c("CRV/USD", Some(("CRVUSD", "CRVUSD")), true, true, false, 0.60),
    c("GRT/USD", Some(("GRTUSD", "GRTUSD")), true, true, false, 0.08),
    c("HYPE/USD", None, false, true, false, 40.0),
    c("LDO/USD", Some(("LDOUSD", "LDOUSD")), true, true, false, 1.0),
    c("ONDO/USD", Some(("ONDOUSD", "ONDOUSD")), false, true, false, 0.80),
    c("POL/USD", Some(("POLUSD", "POLUSD")), true, true, false, 0.20),
    c("RENDER/USD", Some(("RENDERUSD", "RENDERUSD")), true, true, false, 3.5),
    c("SHIB/USD", Some(("SHIBUSD", "SHIBUSD")), true, true, true, 0.000012),
    c("SKY/USD", None, false, true, false, 0.07),
    c("SUSHI/USD", Some(("SUSHIUSD", "SUSHIUSD")), true, true, false, 0.60),
    c("TRUMP/USD", Some(("TRUMPUSD", "TRUMPUSD")), true, true, true, 8.0),
    c("WIF/USD", Some(("WIFUSD", "WIFUSD")), true, true, true, 0.80),
    c("XTZ/USD", Some(("XTZUSD", "XTZUSD")), true, true, false, 0.60),
    c("YFI/USD", Some(("YFIUSD", "YFIUSD")), true, true, false, 5_000.0),
];

/// Never in the universe: dollar pegs and gold. The first four are what the
/// Alpaca paper account lists of them.
pub const NOT_TRADED: &[&str] = &["USDC", "USDG", "USDT", "PAXG", "USD", "DAI", "USDS", "PYUSD", "FDUSD", "TUSD", "XAUT"];

pub fn base(symbol: &str) -> &str {
    symbol.split('/').next().unwrap_or(symbol)
}

/// The known coin behind `symbol` (`BTC/USD`) or market id (`crypto:BTC/USD`).
pub fn coin(symbol: &str) -> Option<&'static Coin> {
    let s = symbol.strip_prefix("crypto:").unwrap_or(symbol);
    COINS.iter().find(|c| c.symbol == s)
}

/// Kraken reply key or request pair (`XXBTZUSD`, `AVAXUSD`) to our symbol.
pub fn by_kraken_key(key: &str) -> Option<&'static str> {
    COINS.iter().find(|c| c.kraken.is_some_and(|(req, reply)| reply == key || req == key)).map(|c| c.symbol)
}

/// Whether `src` can be asked about `symbol` (`BTC/USD` or `crypto:BTC/USD`).
pub fn lists(src: FeedSource, symbol: &str) -> bool {
    match (coin(symbol), src) {
        (Some(c), FeedSource::Kraken | FeedSource::KrakenWs) => c.kraken.is_some(),
        (Some(c), FeedSource::Binance | FeedSource::BinanceVision) => c.binance,
        (Some(c), FeedSource::Alpaca) => c.alpaca,
        (Some(_), _) => true,
        // Unknown: only where an unlisted symbol fails alone.
        (None, FeedSource::Kraken | FeedSource::KrakenWs | FeedSource::Binance | FeedSource::BinanceVision) => false,
        (None, _) => true,
    }
}

pub fn is_meme(symbol: &str) -> bool {
    coin(symbol).is_some_and(|c| c.meme)
}

fn preset(name: &str) -> Option<Vec<String>> {
    let pick = |f: fn(&Coin) -> bool| COINS.iter().filter(|c| f(c)).map(|c| c.symbol.to_string()).collect();
    Some(match name {
        "DEFAULT" | "ALL" => pick(|_| true),
        "ALPACA" => pick(|c| c.alpaca),
        "LAB20" => COINS[..20].iter().map(|c| c.symbol.to_string()).collect(),
        "MEMES" => pick(|c| c.meme),
        _ => return None,
    })
}

/// The coins in a universe setting, as `BTC/USD`, in the order given and
/// without repeats. A token is a preset, a base (`BTC`) or a pair (`BTC/USD`,
/// `BTC-USD`, `BTCUSD`); a stablecoin, another quote currency or anything that
/// is not a plain ticker is skipped.
pub fn parse_universe(text: &str) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    let mut push = |s: String| {
        if !out.contains(&s) {
            out.push(s);
        }
    };
    for line in text.lines() {
        let line = line.split('#').next().unwrap_or("");
        for tok in line.split(|ch: char| ch == ',' || ch.is_whitespace()) {
            let t = tok.trim().to_ascii_uppercase();
            if t.is_empty() {
                continue;
            }
            if let Some(list) = preset(&t) {
                list.into_iter().for_each(&mut push);
                continue;
            }
            let b = match t.split_once(['/', '-']) {
                Some((b, "USD")) => b.to_string(),
                Some(_) => continue,
                None if t.ends_with("USDT") || t.ends_with("USDC") => continue,
                None => t.strip_suffix("USD").filter(|b| !b.is_empty()).unwrap_or(&t).to_string(),
            };
            let b = match b.as_str() {
                "XBT" => "BTC".to_string(),
                "XDG" => "DOGE".to_string(),
                _ => b,
            };
            let ok = (2..=10).contains(&b.len())
                && b.starts_with(|ch: char| ch.is_ascii_uppercase())
                && b.chars().all(|ch| ch.is_ascii_uppercase() || ch.is_ascii_digit());
            if ok && !NOT_TRADED.contains(&b.as_str()) {
                push(format!("{b}/USD"));
            }
        }
    }
    out
}

fn universe_from(env: Option<&str>, file: Option<&str>) -> Vec<String> {
    for text in [env, file].into_iter().flatten() {
        let list = parse_universe(text);
        if !list.is_empty() {
            return list;
        }
    }
    preset("DEFAULT").unwrap_or_default()
}

/// The configured universe (see the module docs), read once per process.
pub fn configured() -> &'static [&'static str] {
    static U: OnceLock<Vec<&'static str>> = OnceLock::new();
    U.get_or_init(|| {
        let list = universe_from(
            std::env::var("PYTHIA_CRYPTO_UNIVERSE").ok().as_deref(),
            std::env::var("PYTHIA_CRYPTO_UNIVERSE_FILE").ok().and_then(|f| std::fs::read_to_string(f).ok()).as_deref(),
        );
        list.into_iter()
            .map(|s| match coin(&s) {
                Some(c) => c.symbol,
                // Leaked once, for the life of the process: the universe is fixed at start.
                None => Box::leak(s.into_boxed_str()) as &'static str,
            })
            .collect()
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_table_is_consistent() {
        for (i, c) in COINS.iter().enumerate() {
            assert!(c.symbol.ends_with("/USD") && c.seed > 0.0, "{}", c.symbol);
            assert!(!COINS[..i].iter().any(|d| d.symbol == c.symbol), "{} twice", c.symbol);
            assert!(!NOT_TRADED.contains(&base(c.symbol)), "{}", c.symbol);
        }
        // The lab's twenty, in its order, with the Kraken pairs it always used.
        for (i, (req, reply, sym)) in crate::marketdata::KRAKEN_PAIRS.iter().enumerate() {
            assert_eq!(COINS[i].symbol, *sym);
            assert_eq!(COINS[i].kraken, Some((*req, *reply)));
        }
        let alpaca: Vec<&str> = COINS.iter().filter(|c| c.alpaca).map(|c| base(c.symbol)).collect();
        assert_eq!(alpaca.len(), 32, "the Alpaca paper list less USDC, USDG, USDT and PAXG");
        let memes: Vec<&str> = COINS.iter().filter(|c| c.meme).map(|c| base(c.symbol)).collect();
        assert_eq!(memes, ["DOGE", "PEPE", "BONK", "SHIB", "TRUMP", "WIF"]);
    }

    #[test]
    fn the_default_is_every_alpaca_coin_plus_the_lab_twenty() {
        let d = universe_from(None, None);
        assert_eq!(d.len(), 37);
        for c in COINS {
            assert!(d.iter().any(|s| s == c.symbol));
        }
        assert_eq!(&d[..2], ["BTC/USD", "ETH/USD"]);
    }

    #[test]
    fn a_setting_is_read_from_the_env_then_the_file() {
        assert_eq!(universe_from(Some("btc, eth\nbonk # memes"), Some("SOL")), ["BTC/USD", "ETH/USD", "BONK/USD"]);
        assert_eq!(universe_from(Some("  # nothing"), Some("SOL/USD")), ["SOL/USD"]);
        assert_eq!(universe_from(Some("USDT USDC PAXG"), None).len(), 37, "only pegs: the default");
        let a = universe_from(Some("alpaca"), None);
        assert_eq!(a.len(), 32);
        assert!(!a.contains(&"TRX/USD".to_string()));
        let mixed = universe_from(Some("lab20 BONK WIF BTC"), None);
        assert_eq!(mixed.len(), 22);
        assert_eq!(&mixed[20..], ["BONK/USD", "WIF/USD"]);
    }

    #[test]
    fn pairs_and_kraken_names_are_read_as_their_coin() {
        assert_eq!(parse_universe("XBTUSD xdg/usd ETH-USD SOLUSDT ADA/EUR ok"), ["BTC/USD", "DOGE/USD", "ETH/USD", "OK/USD"]);
        assert_eq!(parse_universe("A TOOLONGTICKER1 9LIVES"), Vec::<String>::new());
    }

    #[test]
    fn a_venue_is_only_asked_about_coins_it_lists() {
        assert!(lists(FeedSource::Kraken, "crypto:BTC/USD"));
        assert!(!lists(FeedSource::Kraken, "HYPE/USD"));
        assert!(!lists(FeedSource::KrakenWs, "SKY/USD"));
        assert!(lists(FeedSource::Alpaca, "HYPE/USD"));
        assert!(!lists(FeedSource::Alpaca, "TRX/USD"));
        assert!(!lists(FeedSource::Binance, "ONDO/USD"));
        assert!(lists(FeedSource::Bybit, "ONDO/USD"));
        // Unknown coins: only where a miss cannot fail the others.
        assert!(!lists(FeedSource::Binance, "NEWCOIN/USD"));
        assert!(lists(FeedSource::Alpaca, "NEWCOIN/USD"));
        assert_eq!(by_kraken_key("XXBTZUSD"), Some("BTC/USD"));
        assert_eq!(by_kraken_key("BONKUSD"), Some("BONK/USD"));
        assert_eq!(by_kraken_key("NOPE"), None);
    }
}
