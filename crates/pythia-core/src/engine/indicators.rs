//! Technical indicators over a close-price series in chronological order
//! (oldest first, latest last). Pure functions that return `None` when there
//! isn't enough data. Mirrored 1:1 by the TypeScript engine so the browser and
//! native builds produce identical signals.

/// Simple moving average of the last `n` closes.
pub fn sma(s: &[f64], n: usize) -> Option<f64> {
    if n == 0 || s.len() < n {
        return None;
    }
    Some(s[s.len() - n..].iter().sum::<f64>() / n as f64)
}

/// Exponential moving average, seeded with the SMA of the first `n` samples.
pub fn ema(s: &[f64], n: usize) -> Option<f64> {
    if n == 0 || s.len() < n {
        return None;
    }
    let k = 2.0 / (n as f64 + 1.0);
    let mut e = s[..n].iter().sum::<f64>() / n as f64;
    for &x in &s[n..] {
        e = x * k + e * (1.0 - k);
    }
    Some(e)
}

/// Population standard deviation of the last `n` closes.
pub fn stddev(s: &[f64], n: usize) -> Option<f64> {
    if n < 2 || s.len() < n {
        return None;
    }
    let w = &s[s.len() - n..];
    let m = w.iter().sum::<f64>() / n as f64;
    let var = w.iter().map(|x| (x - m) * (x - m)).sum::<f64>() / n as f64;
    Some(var.sqrt())
}

/// Z-score of the latest close vs the last-`n` mean/stddev (Bollinger position).
pub fn zscore(s: &[f64], n: usize) -> Option<f64> {
    let m = sma(s, n)?;
    let sd = stddev(s, n)?;
    if sd == 0.0 {
        return Some(0.0);
    }
    Some((s[s.len() - 1] - m) / sd)
}

/// Rate of change over `n` bars, as a fraction (0.02 = +2%).
pub fn roc(s: &[f64], n: usize) -> Option<f64> {
    if n == 0 || s.len() <= n {
        return None;
    }
    let past = s[s.len() - 1 - n];
    if past == 0.0 {
        return None;
    }
    Some(s[s.len() - 1] / past - 1.0)
}

/// Wilder-style RSI (simple average variant) over `n` periods, 0..100.
pub fn rsi(s: &[f64], n: usize) -> Option<f64> {
    if n == 0 || s.len() < n + 1 {
        return None;
    }
    let w = &s[s.len() - n - 1..];
    let (mut gain, mut loss) = (0.0, 0.0);
    for i in 1..w.len() {
        let d = w[i] - w[i - 1];
        if d >= 0.0 {
            gain += d;
        } else {
            loss -= d;
        }
    }
    let avg_loss = loss / n as f64;
    if avg_loss == 0.0 {
        return Some(100.0);
    }
    let rs = (gain / n as f64) / avg_loss;
    Some(100.0 - 100.0 / (1.0 + rs))
}

/// Highest close over the last `n` bars (Donchian upper).
pub fn donchian_high(s: &[f64], n: usize) -> Option<f64> {
    if n == 0 || s.len() < n {
        return None;
    }
    Some(s[s.len() - n..].iter().cloned().fold(f64::MIN, f64::max))
}

/// Lowest close over the last `n` bars (Donchian lower).
pub fn donchian_low(s: &[f64], n: usize) -> Option<f64> {
    if n == 0 || s.len() < n {
        return None;
    }
    Some(s[s.len() - n..].iter().cloned().fold(f64::MAX, f64::min))
}

/// Wilder's Average True Range over real candles, in price units.
///
/// True range counts the overnight gap (`|high − prev close|`, `|low − prev
/// close|`), which [`atr_proxy`] cannot see from closes alone. On equities that
/// difference is the whole ballgame: a stop sized off close-to-close moves is
/// far too tight to survive a normal opening gap, and gets swept for a loss on
/// days the position was never actually wrong.
pub fn atr(bars: &[crate::marketdata::Ohlc], n: usize) -> Option<f64> {
    if n == 0 || bars.len() < n + 1 {
        return None;
    }
    let tr = |i: usize| -> f64 {
        let prev_close = bars[i - 1].close;
        (bars[i].high - bars[i].low)
            .max((bars[i].high - prev_close).abs())
            .max((bars[i].low - prev_close).abs())
    };
    // Seed with the simple average of the first n true ranges, then smooth.
    let mut avg = (1..=n).map(tr).sum::<f64>() / n as f64;
    for i in (n + 1)..bars.len() {
        avg = (avg * (n as f64 - 1.0) + tr(i)) / n as f64;
    }
    Some(avg)
}

/// Average absolute close-to-close move over `n` bars — an ATR proxy in price
/// units, for series where only closes are available (the simulator, and
/// prediction markets). Prefer [`atr`] whenever real candles exist.
pub fn atr_proxy(s: &[f64], n: usize) -> Option<f64> {
    if n == 0 || s.len() < n + 1 {
        return None;
    }
    let w = &s[s.len() - n - 1..];
    let mut sum = 0.0;
    for i in 1..w.len() {
        sum += (w[i] - w[i - 1]).abs();
    }
    Some(sum / n as f64)
}

/// Standard deviation of the last `n` simple returns (per-bar volatility).
pub fn ret_vol(s: &[f64], n: usize) -> Option<f64> {
    if n < 2 || s.len() < n + 1 {
        return None;
    }
    let w = &s[s.len() - n - 1..];
    let rets: Vec<f64> = (1..w.len())
        .map(|i| if w[i - 1] != 0.0 { w[i] / w[i - 1] - 1.0 } else { 0.0 })
        .collect();
    let m = rets.iter().sum::<f64>() / rets.len() as f64;
    let var = rets.iter().map(|x| (x - m) * (x - m)).sum::<f64>() / rets.len() as f64;
    Some(var.sqrt())
}

/// Kaufman efficiency ratio over `n` bars: |net move| / (sum of |bar moves|).
/// ~1.0 = clean trend, ~0.0 = choppy/mean-reverting. Used for regime detection.
pub fn efficiency_ratio(s: &[f64], n: usize) -> Option<f64> {
    if n == 0 || s.len() < n + 1 {
        return None;
    }
    let w = &s[s.len() - n - 1..];
    let net = (w[w.len() - 1] - w[0]).abs();
    let mut vol = 0.0;
    for i in 1..w.len() {
        vol += (w[i] - w[i - 1]).abs();
    }
    if vol == 0.0 {
        return Some(0.0);
    }
    Some((net / vol).clamp(0.0, 1.0))
}

/// MACD: returns (line, signal). Line = EMA(12) − EMA(26); signal = EMA(9) of
/// the MACD line over the recent window.
pub fn macd(s: &[f64]) -> Option<(f64, f64)> {
    const FAST: usize = 12;
    const SLOW: usize = 26;
    const SIG: usize = 9;
    if s.len() < SLOW + SIG {
        return None;
    }
    let mut line_series = Vec::with_capacity(SIG);
    for i in (s.len() - SIG)..s.len() {
        let slice = &s[..=i];
        line_series.push(ema(slice, FAST)? - ema(slice, SLOW)?);
    }
    let line = *line_series.last().unwrap();
    let signal = ema(&line_series, SIG)?;
    Some((line, signal))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn approx(a: f64, b: f64) -> bool {
        (a - b).abs() < 1e-9
    }

    #[test]
    fn sma_basic() {
        assert!(approx(sma(&[1.0, 2.0, 3.0, 4.0], 4).unwrap(), 2.5));
        assert!(approx(sma(&[1.0, 2.0, 3.0, 4.0], 2).unwrap(), 3.5));
        assert!(sma(&[1.0], 2).is_none());
    }

    #[test]
    fn stddev_and_zscore() {
        let s = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0];
        assert!(approx(stddev(&s, 8).unwrap(), 2.0)); // classic textbook example
        let z = zscore(&s, 8).unwrap();
        assert!((z - (9.0 - 5.0) / 2.0).abs() < 1e-9);
    }

    #[test]
    fn roc_basic() {
        assert!(approx(roc(&[100.0, 110.0], 1).unwrap(), 0.1));
        assert!(approx(roc(&[100.0, 90.0], 1).unwrap(), -0.1));
    }

    #[test]
    fn rsi_extremes() {
        let up: Vec<f64> = (0..20).map(|i| 100.0 + i as f64).collect();
        assert!(rsi(&up, 14).unwrap() > 99.0); // only gains → ~100
        let down: Vec<f64> = (0..20).map(|i| 100.0 - i as f64).collect();
        assert!(rsi(&down, 14).unwrap() < 1.0); // only losses → ~0
    }

    #[test]
    fn ema_tracks_faster_when_shorter() {
        let s: Vec<f64> = (1..=30).map(|i| i as f64).collect();
        let e5 = ema(&s, 5).unwrap();
        let e20 = ema(&s, 20).unwrap();
        // On a rising series the shorter EMA sits closer to the latest value,
        // below it but above the slower EMA.
        assert!(e5 < 30.0 && e5 > e20);
    }

    #[test]
    fn donchian_bounds() {
        let s = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0];
        assert!(approx(donchian_high(&s, 5).unwrap(), 9.0));
        assert!(approx(donchian_low(&s, 5).unwrap(), 1.0));
    }

    #[test]
    fn ret_vol_basic() {
        // constant series → zero volatility
        assert!(approx(ret_vol(&[5.0; 30], 20).unwrap(), 0.0));
        // a series with moves → positive volatility
        let s: Vec<f64> = (0..30).map(|i| 100.0 + (i % 2) as f64 * 3.0).collect();
        assert!(ret_vol(&s, 20).unwrap() > 0.0);
    }

    #[test]
    fn efficiency_ratio_regime() {
        // a clean uptrend → ER near 1
        let trend: Vec<f64> = (0..30).map(|i| 100.0 + i as f64).collect();
        assert!(efficiency_ratio(&trend, 20).unwrap() > 0.95);
        // an oscillation → low ER
        let chop: Vec<f64> = (0..30).map(|i| 100.0 + (i % 2) as f64).collect();
        assert!(efficiency_ratio(&chop, 20).unwrap() < 0.2);
    }

    #[test]
    fn atr_counts_the_gap_that_atr_proxy_misses() {
        use crate::marketdata::Ohlc;
        // Flat intraday ranges, but every bar opens with a $10 gap. Close-to-close
        // sees the move; only true range sees both the gap and the intrabar range.
        let bars: Vec<Ohlc> = (0..20)
            .map(|i| {
                let base = 100.0 + i as f64 * 10.0;
                Ohlc { ts: i as i64 * 60_000, open: base, high: base + 1.0, low: base - 1.0, close: base, volume: 1.0 }
            })
            .collect();
        let a = atr(&bars, 14).unwrap();
        let closes: Vec<f64> = bars.iter().map(|b| b.close).collect();
        let p = atr_proxy(&closes, 14).unwrap();
        assert!(a > p, "true range ({a}) must exceed the close-to-close proxy ({p})");
        // gap of 10 plus 1 of range above the previous close
        assert!((a - 11.0).abs() < 0.5, "got {a}");
    }

    #[test]
    fn atr_needs_more_bars_than_its_period() {
        use crate::marketdata::Ohlc;
        let few: Vec<Ohlc> = (0..5)
            .map(|i| Ohlc { ts: i, open: 1.0, high: 1.0, low: 1.0, close: 1.0, volume: 0.0 })
            .collect();
        assert!(atr(&few, 14).is_none());
    }

    #[test]
    fn macd_trend_sign() {
        // steadily rising series → MACD line positive
        let s: Vec<f64> = (0..60).map(|i| 100.0 + i as f64).collect();
        let (line, _sig) = macd(&s).unwrap();
        assert!(line > 0.0);
    }
}
