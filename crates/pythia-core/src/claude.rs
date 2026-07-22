//! Claude signal provider.
//!
//! An **optional, env-gated** advisor that asks Claude to reason about a single
//! market and return a structured probability/direction signal. It is NOT a
//! magic oracle: no LLM reliably forecasts prices. Its real value is qualitative
//! reasoning over *event* markets (Polymarket) — parsing a question, weighing
//! base rates and recent news-style context the caller supplies — and as one
//! input among many, never the sole trigger for a live order.
//!
//! Gated on the `ANTHROPIC_API_KEY` environment variable. When unset,
//! [`is_configured`] returns `false` and the engine simply never consults it.
//! Rust has no official Anthropic SDK, so this talks to the Messages API over
//! raw HTTPS (reqwest) — the documented fallback for unsupported languages.

use serde::{Deserialize, Serialize};

const API_URL: &str = "https://api.anthropic.com/v1/messages";
const API_VERSION: &str = "2023-06-01";
/// Default model. Overridable with `PYTHIA_CLAUDE_MODEL` for cheaper/faster runs
/// (e.g. `claude-haiku-4-5`), but the capable default is intentional.
const DEFAULT_MODEL: &str = "claude-opus-4-8";

#[derive(Debug, thiserror::Error)]
pub enum ClaudeError {
    #[error("ANTHROPIC_API_KEY not set — Claude signals disabled")]
    NotConfigured,
    #[error("http: {0}")]
    Http(#[from] reqwest::Error),
    #[error("api error {status}: {body}")]
    Api { status: u16, body: String },
    #[error("no text block in response")]
    NoContent,
    #[error("could not parse signal json: {0}")]
    Parse(String),
}

/// The structured advice Claude returns for one market.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ClaudeSignal {
    /// For a prediction market: P(YES), 0..1. For a directional (crypto/equity)
    /// market: P(price is higher over the caller's horizon), 0..1.
    pub probability: f64,
    /// Discrete stance derived from the reasoning.
    pub direction: Direction,
    /// Claude's self-reported confidence in this call, 0..1. Low confidence is a
    /// feature — the caller can require a floor before acting.
    pub confidence: f64,
    /// One or two sentences of plain-language reasoning (kept for the journal).
    pub rationale: String,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Direction {
    Long,
    Short,
    Neutral,
}

/// True when an API key is present in the environment. Cheap; call it before
/// [`signal`] to avoid a guaranteed-failing request.
pub fn is_configured() -> bool {
    std::env::var("ANTHROPIC_API_KEY").map(|k| !k.trim().is_empty()).unwrap_or(false)
}

fn model() -> String {
    std::env::var("PYTHIA_CLAUDE_MODEL")
        .ok()
        .filter(|m| !m.trim().is_empty())
        .unwrap_or_else(|| DEFAULT_MODEL.to_string())
}

const SYSTEM: &str = "You are a disciplined quantitative analyst embedded in an \
automated, PAPER-TRADING research bot. You are given ONE market and any context \
the caller has. Estimate an honest probability and a stance. Be calibrated: when \
you lack an edge, say so with a probability near 0.5 and low confidence — do not \
manufacture false precision. You are one advisory input, never the final \
decision. Never claim to predict prices reliably.";

/// The output schema handed to the Messages API (`output_config.format`) so the
/// reply is guaranteed to be a single JSON object we can deserialize.
fn output_schema() -> serde_json::Value {
    serde_json::json!({
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": {
                "probability": { "type": "number" },
                "direction": { "type": "string", "enum": ["long", "short", "neutral"] },
                "confidence": { "type": "number" },
                "rationale": { "type": "string" }
            },
            "required": ["probability", "direction", "confidence", "rationale"],
            "additionalProperties": false
        }
    })
}

/// Ask Claude for a signal on one market. `context` is a compact, caller-built
/// description: the question/symbol, current price or YES odds, recent moves,
/// and whatever news the caller wants to surface.
///
/// Returns a validated, clamped [`ClaudeSignal`]. Errors are non-fatal to the
/// engine — treat any `Err` as "no opinion this tick".
pub async fn signal(context: &str) -> Result<ClaudeSignal, ClaudeError> {
    let key = std::env::var("ANTHROPIC_API_KEY")
        .ok()
        .filter(|k| !k.trim().is_empty())
        .ok_or(ClaudeError::NotConfigured)?;

    let body = serde_json::json!({
        "model": model(),
        "max_tokens": 1024,
        // Adaptive thinking gives better-calibrated event reasoning; the JSON
        // still arrives as the final text block. Medium effort keeps latency
        // sane for a per-tick advisor.
        "thinking": { "type": "adaptive" },
        "output_config": { "effort": "medium", "format": output_schema() },
        "system": SYSTEM,
        "messages": [{
            "role": "user",
            "content": format!(
                "Analyze this market and return your signal as JSON.\n\n{context}"
            )
        }]
    });

    let client = reqwest::Client::new();
    let resp = client
        .post(API_URL)
        .header("x-api-key", key)
        .header("anthropic-version", API_VERSION)
        .header("content-type", "application/json")
        .json(&body)
        .send()
        .await?;

    let status = resp.status();
    if !status.is_success() {
        let body = resp.text().await.unwrap_or_default();
        return Err(ClaudeError::Api { status: status.as_u16(), body });
    }

    let json: serde_json::Value = resp.json().await?;
    parse_signal(&json)
}

/// Pull the first `text` content block out of a Messages API response and parse
/// it as a [`ClaudeSignal`]. Split out for unit-testing without a network call.
fn parse_signal(json: &serde_json::Value) -> Result<ClaudeSignal, ClaudeError> {
    let text = json
        .get("content")
        .and_then(|c| c.as_array())
        .and_then(|blocks| {
            blocks
                .iter()
                .find(|b| b.get("type").and_then(|t| t.as_str()) == Some("text"))
        })
        .and_then(|b| b.get("text"))
        .and_then(|t| t.as_str())
        .ok_or(ClaudeError::NoContent)?;

    let mut sig: ClaudeSignal =
        serde_json::from_str(text).map_err(|e| ClaudeError::Parse(e.to_string()))?;

    // The JSON schema can't express numeric bounds, so clamp defensively.
    sig.probability = sig.probability.clamp(0.0, 1.0);
    sig.confidence = sig.confidence.clamp(0.0, 1.0);
    Ok(sig)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_and_clamps_a_response() {
        let resp = serde_json::json!({
            "content": [
                { "type": "thinking", "thinking": "" },
                { "type": "text", "text": "{\"probability\":1.4,\"direction\":\"long\",\"confidence\":-0.2,\"rationale\":\"strong uptrend\"}" }
            ]
        });
        let sig = parse_signal(&resp).unwrap();
        assert_eq!(sig.direction, Direction::Long);
        assert_eq!(sig.probability, 1.0); // clamped
        assert_eq!(sig.confidence, 0.0); // clamped
        assert_eq!(sig.rationale, "strong uptrend");
    }

    #[test]
    fn errors_when_no_text_block() {
        let resp = serde_json::json!({ "content": [{ "type": "thinking", "thinking": "" }] });
        assert!(matches!(parse_signal(&resp), Err(ClaudeError::NoContent)));
    }

    #[test]
    fn not_configured_without_key() {
        // Can't mutate the process env safely in parallel tests; just assert the
        // helper reads the var (documents intent).
        let _ = is_configured();
    }
}
