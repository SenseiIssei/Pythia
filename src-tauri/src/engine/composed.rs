//! User-composed rule strategies. Mirrors the TypeScript `composedRules.ts` so a
//! strategy built in the Composer runs identically in the native engine.

use super::indicators as ind;
use crate::connectors::Side;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum IndKind {
    Price,
    Rsi,
    Ema,
    Sma,
    Zscore,
    Roc,
    MacdHist,
    Atr,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Operand {
    pub kind: IndKind,
    pub period: f64,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum Op {
    #[serde(rename = "<")]
    Lt,
    #[serde(rename = ">")]
    Gt,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum RightMode {
    Const,
    Indicator,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Rule {
    pub left: Operand,
    pub op: Op,
    pub right_mode: RightMode,
    pub right_const: f64,
    pub right_operand: Operand,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Direction {
    Long,
    Short,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Composed {
    pub direction: Direction,
    pub rules: Vec<Rule>,
}

fn eval_operand(o: &Operand, hist: &[f64], price: f64) -> Option<f64> {
    let n = o.period.max(0.0) as usize;
    match o.kind {
        IndKind::Price => Some(price),
        IndKind::Rsi => ind::rsi(hist, n),
        IndKind::Ema => ind::ema(hist, n),
        IndKind::Sma => ind::sma(hist, n),
        IndKind::Zscore => ind::zscore(hist, n),
        IndKind::Roc => ind::roc(hist, n).map(|r| r * 100.0),
        IndKind::Atr => ind::atr_proxy(hist, n),
        IndKind::MacdHist => ind::macd(hist).map(|(l, s)| l - s),
    }
}

/// `Some(side)` when every rule passes (AND), else `None`.
pub fn eval_composed(c: &Composed, hist: &[f64], price: f64) -> Option<Side> {
    if c.rules.is_empty() {
        return None;
    }
    for r in &c.rules {
        let l = eval_operand(&r.left, hist, price)?;
        let rv = match r.right_mode {
            RightMode::Const => r.right_const,
            RightMode::Indicator => eval_operand(&r.right_operand, hist, price)?,
        };
        let pass = match r.op {
            Op::Lt => l < rv,
            Op::Gt => l > rv,
        };
        if !pass {
            return None;
        }
    }
    Some(match c.direction {
        Direction::Long => Side::Buy,
        Direction::Short => Side::Sell,
    })
}
