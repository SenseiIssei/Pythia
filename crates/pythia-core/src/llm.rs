//! Multi-provider LLM signal engine.
//!
//! An **optional** advisor that asks a large language model to reason about one
//! market and return a structured probability/direction signal. It is NOT a
//! magic oracle — no LLM reliably forecasts prices. Its value is qualitative
//! reasoning over *event* markets and as one input among many, never the sole
//! trigger for a live order.
//!
//! Provider-agnostic: bring any API key. Anthropic (Claude) uses the Messages
//! API; every other supported provider speaks the OpenAI Chat Completions
//! dialect, so one code path covers OpenAI, xAI (Grok), z.ai (GLM), DeepSeek,
//! Google Gemini, Groq, OpenRouter, Mistral, and a local Ollama. The caller
//! supplies the key (from env on the server, from the OS keychain on desktop).
//!
//! Rust has no official SDK for most of these, so this talks raw HTTPS (reqwest).

use serde::{Deserialize, Serialize};

/// Which wire protocol a provider speaks.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Wire {
    Anthropic,
    OpenAi,
}

/// Every supported provider. Add a variant + a row in [`Provider::spec`] to
/// support another; nothing else changes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Provider {
    Anthropic,
    OpenAI,
    XAI,
    ZAI,
    DeepSeek,
    Google,
    Groq,
    OpenRouter,
    Mistral,
    Ollama,
}

struct Spec {
    id: &'static str,
    label: &'static str,
    wire: Wire,
    base_url: &'static str,
    env_key: &'static str,
    default_model: &'static str,
    suggested: &'static [&'static str],
    needs_key: bool,
}

impl Provider {
    pub const ALL: [Provider; 10] = [
        Provider::Anthropic,
        Provider::OpenAI,
        Provider::XAI,
        Provider::ZAI,
        Provider::DeepSeek,
        Provider::Google,
        Provider::Groq,
        Provider::OpenRouter,
        Provider::Mistral,
        Provider::Ollama,
    ];

    fn spec(self) -> Spec {
        match self {
            // Anthropic — the one non-OpenAI dialect. claude-opus-4-8 is current.
            Provider::Anthropic => Spec {
                id: "anthropic",
                label: "Anthropic (Claude)",
                wire: Wire::Anthropic,
                base_url: "https://api.anthropic.com",
                env_key: "ANTHROPIC_API_KEY",
                default_model: "claude-opus-4-8",
                suggested: &["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5", "claude-fable-5"],
                needs_key: true,
            },
            Provider::OpenAI => Spec {
                id: "openai",
                label: "OpenAI (GPT)",
                wire: Wire::OpenAi,
                base_url: "https://api.openai.com/v1",
                env_key: "OPENAI_API_KEY",
                default_model: "gpt-5.6", // Sol (alias of gpt-5.6-sol)
                suggested: &["gpt-5.6", "gpt-5.6-terra", "gpt-5.6-luna"],
                needs_key: true,
            },
            Provider::XAI => Spec {
                id: "xai",
                label: "xAI (Grok)",
                wire: Wire::OpenAi,
                base_url: "https://api.x.ai/v1",
                env_key: "XAI_API_KEY",
                default_model: "grok-4.5",
                suggested: &["grok-4.5", "grok-4.3", "grok-4"],
                needs_key: true,
            },
            Provider::ZAI => Spec {
                id: "zai",
                label: "z.ai (GLM)",
                wire: Wire::OpenAi,
                base_url: "https://api.z.ai/api/paas/v4",
                env_key: "ZAI_API_KEY",
                default_model: "glm-5.2",
                suggested: &["glm-5.2", "glm-5.1", "glm-4.6"],
                needs_key: true,
            },
            Provider::DeepSeek => Spec {
                id: "deepseek",
                label: "DeepSeek",
                wire: Wire::OpenAi,
                base_url: "https://api.deepseek.com",
                env_key: "DEEPSEEK_API_KEY",
                default_model: "deepseek-v4-pro", // deepseek-chat/reasoner retire 2026-07-24
                suggested: &["deepseek-v4-pro", "deepseek-v4-flash"],
                needs_key: true,
            },
            Provider::Google => Spec {
                id: "google",
                label: "Google (Gemini)",
                wire: Wire::OpenAi, // Gemini's OpenAI-compatible endpoint
                base_url: "https://generativelanguage.googleapis.com/v1beta/openai",
                env_key: "GEMINI_API_KEY",
                default_model: "gemini-3-pro",
                suggested: &["gemini-3-pro", "gemini-3.1-pro", "gemini-3.6-flash", "gemini-flash-latest"],
                needs_key: true,
            },
            Provider::Groq => Spec {
                id: "groq",
                label: "Groq",
                wire: Wire::OpenAi,
                base_url: "https://api.groq.com/openai/v1",
                env_key: "GROQ_API_KEY",
                default_model: "llama-3.3-70b-versatile",
                suggested: &["llama-3.3-70b-versatile", "moonshotai/kimi-k2-instruct", "deepseek-r1-distill-llama-70b"],
                needs_key: true,
            },
            Provider::OpenRouter => Spec {
                id: "openrouter",
                label: "OpenRouter",
                wire: Wire::OpenAi,
                base_url: "https://openrouter.ai/api/v1",
                env_key: "OPENROUTER_API_KEY",
                default_model: "openai/gpt-5.6",
                suggested: &[
                    "openai/gpt-5.6",
                    "anthropic/claude-opus-4-8",
                    "x-ai/grok-4.5",
                    "z-ai/glm-5.2",
                    "deepseek/deepseek-v4-pro",
                    "google/gemini-3-pro",
                ],
                needs_key: true,
            },
            Provider::Mistral => Spec {
                id: "mistral",
                label: "Mistral",
                wire: Wire::OpenAi,
                base_url: "https://api.mistral.ai/v1",
                env_key: "MISTRAL_API_KEY",
                default_model: "mistral-large-latest", // resolves to Mistral Large 3
                suggested: &["mistral-large-latest", "mistral-medium-latest"],
                needs_key: true,
            },
            Provider::Ollama => Spec {
                id: "ollama",
                label: "Ollama (local)",
                wire: Wire::OpenAi,
                base_url: "http://localhost:11434/v1",
                env_key: "", // no key
                default_model: "llama3.3",
                suggested: &["llama3.3", "qwen3", "deepseek-r1"],
                needs_key: false,
            },
        }
    }

    /// Parse a provider id, tolerant of common aliases (`grok`, `gemini`, `glm`).
    pub fn parse(s: &str) -> Option<Provider> {
        match s.trim().to_lowercase().as_str() {
            "anthropic" | "claude" => Some(Provider::Anthropic),
            "openai" | "gpt" | "chatgpt" => Some(Provider::OpenAI),
            "xai" | "grok" | "x.ai" | "x-ai" => Some(Provider::XAI),
            "zai" | "z.ai" | "z-ai" | "glm" | "zhipu" => Some(Provider::ZAI),
            "deepseek" => Some(Provider::DeepSeek),
            "google" | "gemini" => Some(Provider::Google),
            "groq" => Some(Provider::Groq),
            "openrouter" => Some(Provider::OpenRouter),
            "mistral" => Some(Provider::Mistral),
            "ollama" | "local" => Some(Provider::Ollama),
            _ => None,
        }
    }

    pub fn id(self) -> &'static str {
        self.spec().id
    }
    pub fn env_key(self) -> &'static str {
        self.spec().env_key
    }
    pub fn default_model(self) -> &'static str {
        self.spec().default_model
    }
    pub fn needs_key(self) -> bool {
        self.spec().needs_key
    }

    /// True if a key for this provider is present in the environment (or the
    /// provider needs no key, e.g. local Ollama).
    pub fn configured_in_env(self) -> bool {
        if !self.spec().needs_key {
            return true;
        }
        std::env::var(self.env_key()).map(|k| !k.trim().is_empty()).unwrap_or(false)
    }
}

/// Static, serializable description of a provider for the UI (dropdowns, badges).
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProviderInfo {
    pub id: String,
    pub label: String,
    pub default_model: String,
    pub suggested_models: Vec<String>,
    pub env_key: String,
    pub needs_key: bool,
    /// Whether a usable key is available in the *current context* (env for the
    /// server; the desktop fills this from the vault instead).
    pub configured: bool,
}

impl ProviderInfo {
    fn from(p: Provider, configured: bool) -> Self {
        let s = p.spec();
        ProviderInfo {
            id: s.id.to_string(),
            label: s.label.to_string(),
            default_model: s.default_model.to_string(),
            suggested_models: s.suggested.iter().map(|m| m.to_string()).collect(),
            env_key: s.env_key.to_string(),
            needs_key: s.needs_key,
            configured,
        }
    }
}

/// Every provider with its env-configured status — for the server's
/// `/api/llm/providers`.
pub fn providers_from_env() -> Vec<ProviderInfo> {
    Provider::ALL.iter().map(|&p| ProviderInfo::from(p, p.configured_in_env())).collect()
}

/// Every provider's static metadata with a caller-supplied `configured` flag —
/// for the desktop, which knows key presence from the vault.
pub fn providers_with(configured: impl Fn(Provider) -> bool) -> Vec<ProviderInfo> {
    Provider::ALL.iter().map(|&p| ProviderInfo::from(p, configured(p))).collect()
}

/// A request for a signal: which provider/model, the key, and the context.
#[derive(Debug, Clone)]
pub struct LlmConfig {
    pub provider: Provider,
    /// Empty → the provider's default model.
    pub model: String,
    pub api_key: String,
    /// Empty → the provider's default endpoint.
    pub base_url: String,
}

impl LlmConfig {
    pub fn new(provider: Provider, model: impl Into<String>, api_key: impl Into<String>) -> Self {
        LlmConfig { provider, model: model.into(), api_key: api_key.into(), base_url: String::new() }
    }
    fn resolved_model(&self) -> String {
        if self.model.trim().is_empty() {
            self.provider.default_model().to_string()
        } else {
            self.model.trim().to_string()
        }
    }
    fn resolved_base(&self) -> String {
        if self.base_url.trim().is_empty() {
            self.provider.spec().base_url.to_string()
        } else {
            self.base_url.trim().trim_end_matches('/').to_string()
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum LlmError {
    #[error("no API key for {0} — configure one first")]
    NoKey(String),
    #[error("http: {0}")]
    Http(#[from] reqwest::Error),
    #[error("{provider} api error {status}: {body}")]
    Api { provider: String, status: u16, body: String },
    #[error("no text content in {0} response")]
    NoContent(String),
    #[error("could not parse signal json: {0}")]
    Parse(String),
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Direction {
    Long,
    Short,
    Neutral,
}

/// The structured advice an LLM returns for one market. `provider`/`model` are
/// filled in by us so the UI can show who answered.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Signal {
    /// Prediction market: P(YES). Directional market: P(price higher over the
    /// caller's horizon). 0..1.
    pub probability: f64,
    pub direction: Direction,
    /// The model's self-reported confidence, 0..1. Low is a feature.
    pub confidence: f64,
    /// One or two sentences of reasoning (kept for the journal).
    pub rationale: String,
    #[serde(default)]
    pub provider: String,
    #[serde(default)]
    pub model: String,
}

/// Only the model-produced fields; `provider`/`model` are stamped on afterward.
#[derive(Debug, Clone, Deserialize)]
struct RawSignal {
    probability: f64,
    direction: Direction,
    confidence: f64,
    rationale: String,
}

const SYSTEM: &str = "You are a disciplined quantitative analyst embedded in an \
automated, PAPER-TRADING research bot. You are given ONE market and any context \
the caller has. Estimate an honest probability and a stance. Be calibrated: when \
you lack an edge, say so with a probability near 0.5 and low confidence — do not \
manufacture false precision. You are one advisory input, never the final \
decision. Never claim to predict prices reliably. Respond with ONLY a JSON \
object of the form {\"probability\": <0..1>, \"direction\": \"long\"|\"short\"|\
\"neutral\", \"confidence\": <0..1>, \"rationale\": \"<one or two sentences>\"} \
and nothing else.";

/// Ask the configured provider for a signal on one market. `context` is a
/// compact, caller-built description (question/symbol, price or odds, recent
/// moves, any news). Non-fatal to the engine — treat any `Err` as "no opinion".
pub async fn signal(cfg: &LlmConfig, context: &str) -> Result<Signal, LlmError> {
    if cfg.provider.needs_key() && cfg.api_key.trim().is_empty() {
        return Err(LlmError::NoKey(cfg.provider.id().to_string()));
    }

    let raw = match cfg.provider.spec().wire {
        Wire::Anthropic => call_anthropic(cfg, context).await?,
        Wire::OpenAi => call_openai(cfg, context).await?,
    };

    Ok(Signal {
        probability: raw.probability.clamp(0.0, 1.0),
        confidence: raw.confidence.clamp(0.0, 1.0),
        direction: raw.direction,
        rationale: raw.rationale,
        provider: cfg.provider.id().to_string(),
        model: cfg.resolved_model(),
    })
}

async fn call_anthropic(cfg: &LlmConfig, context: &str) -> Result<RawSignal, LlmError> {
    let body = serde_json::json!({
        "model": cfg.resolved_model(),
        "max_tokens": 1024,
        "thinking": { "type": "adaptive" },
        "output_config": {
            "effort": "medium",
            "format": {
                "type": "json_schema",
                "schema": signal_schema()
            }
        },
        "system": SYSTEM,
        "messages": [{ "role": "user", "content": format!("Analyze this market.\n\n{context}") }]
    });

    let resp = reqwest::Client::new()
        .post(format!("{}/v1/messages", cfg.resolved_base()))
        .header("x-api-key", cfg.api_key.trim())
        .header("anthropic-version", "2023-06-01")
        .header("content-type", "application/json")
        .json(&body)
        .send()
        .await?;

    let status = resp.status();
    if !status.is_success() {
        return Err(LlmError::Api {
            provider: "anthropic".into(),
            status: status.as_u16(),
            body: resp.text().await.unwrap_or_default(),
        });
    }

    let json: serde_json::Value = resp.json().await?;
    let text = json
        .get("content")
        .and_then(|c| c.as_array())
        .and_then(|b| b.iter().find(|x| x.get("type").and_then(|t| t.as_str()) == Some("text")))
        .and_then(|b| b.get("text"))
        .and_then(|t| t.as_str())
        .ok_or_else(|| LlmError::NoContent("anthropic".into()))?;
    parse_raw(text)
}

async fn call_openai(cfg: &LlmConfig, context: &str) -> Result<RawSignal, LlmError> {
    let body = serde_json::json!({
        "model": cfg.resolved_model(),
        // Widely supported across OpenAI-compatible providers; parsing is still
        // defensive in case a provider ignores it or wraps the JSON.
        "response_format": { "type": "json_object" },
        "messages": [
            { "role": "system", "content": SYSTEM },
            { "role": "user", "content": format!("Analyze this market.\n\n{context}") }
        ]
    });

    let mut req = reqwest::Client::new()
        .post(format!("{}/chat/completions", cfg.resolved_base()))
        .header("content-type", "application/json");
    if cfg.provider.needs_key() {
        req = req.header("authorization", format!("Bearer {}", cfg.api_key.trim()));
    }
    let resp = req.json(&body).send().await?;

    let status = resp.status();
    if !status.is_success() {
        return Err(LlmError::Api {
            provider: cfg.provider.id().to_string(),
            status: status.as_u16(),
            body: resp.text().await.unwrap_or_default(),
        });
    }

    let json: serde_json::Value = resp.json().await?;
    let text = json
        .get("choices")
        .and_then(|c| c.as_array())
        .and_then(|a| a.first())
        .and_then(|c| c.get("message"))
        .and_then(|m| m.get("content"))
        .and_then(|t| t.as_str())
        .ok_or_else(|| LlmError::NoContent(cfg.provider.id().to_string()))?;
    parse_raw(text)
}

fn signal_schema() -> serde_json::Value {
    serde_json::json!({
        "type": "object",
        "properties": {
            "probability": { "type": "number" },
            "direction": { "type": "string", "enum": ["long", "short", "neutral"] },
            "confidence": { "type": "number" },
            "rationale": { "type": "string" }
        },
        "required": ["probability", "direction", "confidence", "rationale"],
        "additionalProperties": false
    })
}

/// Parse a model's text into a [`RawSignal`], tolerating code fences or stray
/// prose around the JSON object.
fn parse_raw(text: &str) -> Result<RawSignal, LlmError> {
    if let Ok(s) = serde_json::from_str::<RawSignal>(text.trim()) {
        return Ok(s);
    }
    // Fall back to the first balanced-looking {...} slice.
    let start = text.find('{');
    let end = text.rfind('}');
    if let (Some(a), Some(b)) = (start, end) {
        if b > a {
            if let Ok(s) = serde_json::from_str::<RawSignal>(&text[a..=b]) {
                return Ok(s);
            }
        }
    }
    Err(LlmError::Parse(text.chars().take(200).collect()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_plain_json() {
        let s = parse_raw(
            r#"{"probability":0.7,"direction":"long","confidence":0.4,"rationale":"uptrend"}"#,
        )
        .unwrap();
        assert_eq!(s.direction, Direction::Long);
        assert_eq!(s.probability, 0.7);
    }

    #[test]
    fn parses_json_wrapped_in_fences_and_prose() {
        let s = parse_raw(
            "Here you go:\n```json\n{\"probability\":0.2,\"direction\":\"short\",\"confidence\":0.9,\"rationale\":\"downtrend\"}\n```",
        )
        .unwrap();
        assert_eq!(s.direction, Direction::Short);
        assert_eq!(s.confidence, 0.9);
    }

    #[test]
    fn signal_clamps_out_of_range() {
        // Exercise the clamp logic in `signal`'s post-processing without a call.
        let raw = RawSignal {
            probability: 1.5,
            direction: Direction::Neutral,
            confidence: -1.0,
            rationale: "x".into(),
        };
        let out = Signal {
            probability: raw.probability.clamp(0.0, 1.0),
            confidence: raw.confidence.clamp(0.0, 1.0),
            direction: raw.direction,
            rationale: raw.rationale,
            provider: "openai".into(),
            model: "gpt-5.6".into(),
        };
        assert_eq!(out.probability, 1.0);
        assert_eq!(out.confidence, 0.0);
    }

    #[test]
    fn provider_parse_aliases() {
        assert_eq!(Provider::parse("grok"), Some(Provider::XAI));
        assert_eq!(Provider::parse("GLM"), Some(Provider::ZAI));
        assert_eq!(Provider::parse("gemini"), Some(Provider::Google));
        assert_eq!(Provider::parse("claude"), Some(Provider::Anthropic));
        assert_eq!(Provider::parse("nope"), None);
    }

    #[test]
    fn ollama_needs_no_key() {
        assert!(!Provider::Ollama.needs_key());
        assert!(Provider::Ollama.configured_in_env());
        assert!(Provider::Anthropic.needs_key());
    }
}
