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
    ///
    /// Note this is **not** used as a weight anywhere. Self-reported confidence
    /// is uncorrelated with being right; weight comes from a scored track
    /// record (`forecast::calibration`). It is displayed, and that is all.
    pub confidence: f64,
    /// One or two sentences of reasoning (kept for the journal).
    pub rationale: String,
    /// The outside-view starting point: how often things in this reference class
    /// happen. Present only for the deeper [`forecast`] protocol.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub base_rate: Option<f64>,
    /// What the model says the question actually hinges on.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub key_drivers: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub evidence_for: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub evidence_against: Vec<String>,
    #[serde(default)]
    pub provider: String,
    #[serde(default)]
    pub model: String,
}

/// Only the model-produced fields; `provider`/`model` are stamped on afterward.
///
/// camelCase because that is what the schema asks the model for; the four
/// single-word fields are unaffected, so the older quick-signal format still
/// parses through the same struct.
#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RawSignal {
    probability: f64,
    direction: Direction,
    confidence: f64,
    rationale: String,
    #[serde(default)]
    base_rate: Option<f64>,
    #[serde(default)]
    key_drivers: Vec<String>,
    #[serde(default)]
    evidence_for: Vec<String>,
    #[serde(default)]
    evidence_against: Vec<String>,
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

/// The forecasting protocol.
///
/// The difference between this and the quick [`SYSTEM`] prompt is the *order of
/// operations*, and it is not cosmetic. Asking a model "will X happen?" gets an
/// inside-view narrative with a number attached to the end of it — a story,
/// scored as a probability. Forcing the base rate out **first**, before any
/// case-specific reasoning, anchors the answer to a reference class the way
/// human forecasting research says it should be. The evidence lists then have
/// to be produced symmetrically, so the model cannot quietly stop looking once
/// it has enough for the side it already picked.
///
/// The market price is given as an explicit anchor, with instructions to treat
/// deviation from it as a claim that needs justifying. A model that answers "the
/// market says 0.60 and I have nothing to add" is doing its job correctly.
const SYSTEM_FORECAST: &str = "You are a calibrated forecaster contributing ONE opinion to an \
ensemble. Your output is scored against reality with a Brier score and compared against the \
market price; a confident wrong answer is punished far harder than an honest uncertain one, and \
eloquence earns nothing.\n\n\
Work in this order and do not skip a step:\n\
1. REFERENCE CLASS. What class of events does this belong to, and how often do events in that \
class happen? State that as `baseRate`. This is the outside view and it comes FIRST.\n\
2. KEY DRIVERS. What does the outcome actually hinge on? At most three.\n\
3. EVIDENCE. List concrete evidence for AND against, symmetrically. If you can only find \
evidence for one side, you have not looked at the other.\n\
4. ADJUST. Move from the base rate only as far as the evidence in step 3 justifies.\n\n\
The market price is given to you. It aggregates the money-weighted opinion of everyone who \
traded, and it is hard to beat. Deviating from it is a CLAIM that you know something the market \
does not — make it only when step 3 supports it. Agreeing with the market is a valid, common, \
and correct answer.\n\n\
Do not invent facts, figures, or news. If the context does not contain what you would need, say \
so in the rationale and stay near the base rate. Never claim you can reliably predict prices.\n\n\
Respond with ONLY a JSON object:\n\
{\"baseRate\": <0..1>, \"probability\": <0..1>, \"direction\": \"long\"|\"short\"|\"neutral\", \
\"confidence\": <0..1>, \"keyDrivers\": [\"...\"], \"evidenceFor\": [\"...\"], \
\"evidenceAgainst\": [\"...\"], \"rationale\": \"<two or three sentences>\"}";

/// Ask the configured provider for a signal on one market. `context` is a
/// compact, caller-built description (question/symbol, price or odds, recent
/// moves, any news). Non-fatal to the engine — treat any `Err` as "no opinion".
pub async fn signal(cfg: &LlmConfig, context: &str) -> Result<Signal, LlmError> {
    ask(cfg, context, SYSTEM, signal_schema()).await
}

/// Ask for a full forecast using the reference-class protocol above. Slower and
/// more expensive than [`signal`]; this is what the ensemble uses.
pub async fn forecast(cfg: &LlmConfig, context: &str) -> Result<Signal, LlmError> {
    ask(cfg, context, SYSTEM_FORECAST, forecast_schema()).await
}

async fn ask(
    cfg: &LlmConfig,
    context: &str,
    system: &str,
    schema: serde_json::Value,
) -> Result<Signal, LlmError> {
    if cfg.provider.needs_key() && cfg.api_key.trim().is_empty() {
        return Err(LlmError::NoKey(cfg.provider.id().to_string()));
    }

    let raw = match cfg.provider.spec().wire {
        Wire::Anthropic => call_anthropic(cfg, context, system, schema).await?,
        Wire::OpenAi => call_openai(cfg, context, system).await?,
    };

    Ok(Signal {
        probability: raw.probability.clamp(0.0, 1.0),
        confidence: raw.confidence.clamp(0.0, 1.0),
        direction: raw.direction,
        rationale: raw.rationale,
        base_rate: raw.base_rate.map(|b| b.clamp(0.0, 1.0)),
        key_drivers: raw.key_drivers,
        evidence_for: raw.evidence_for,
        evidence_against: raw.evidence_against,
        provider: cfg.provider.id().to_string(),
        model: cfg.resolved_model(),
    })
}

/// One provider's answer, or the reason it did not give one.
pub type EnsembleResult = (String, Result<Signal, LlmError>);

/// Ask several providers the same question **concurrently and independently**.
///
/// Independence is the point. Feeding one model's answer to the next produces
/// agreement, not accuracy — the second model anchors on the first and the
/// ensemble collapses to a single opinion wearing several hats. Every provider
/// here sees exactly the same context and none of them sees another's answer, so
/// what disagreement survives is real signal about how uncertain the question is.
///
/// One provider failing (no key, rate limit, bad JSON) never fails the batch:
/// its error is returned alongside the others' answers, and the caller pools
/// whatever came back.
pub async fn ensemble(cfgs: Vec<LlmConfig>, context: &str) -> Vec<EnsembleResult> {
    let mut set = tokio::task::JoinSet::new();
    for cfg in cfgs {
        let ctx = context.to_string();
        set.spawn(async move {
            let id = cfg.provider.id().to_string();
            (id, forecast(&cfg, &ctx).await)
        });
    }
    let mut out = Vec::new();
    while let Some(joined) = set.join_next().await {
        match joined {
            Ok(r) => out.push(r),
            // A panicked task must not take the batch down with it.
            Err(e) => tracing::warn!("forecast task failed to join: {e}"),
        }
    }
    // JoinSet completes out of order; sort so the UI is stable between refreshes.
    out.sort_by(|a, b| a.0.cmp(&b.0));
    out
}

async fn call_anthropic(
    cfg: &LlmConfig,
    context: &str,
    system: &str,
    schema: serde_json::Value,
) -> Result<RawSignal, LlmError> {
    let body = serde_json::json!({
        "model": cfg.resolved_model(),
        "max_tokens": 2048,
        "thinking": { "type": "adaptive" },
        "output_config": {
            "effort": "medium",
            "format": {
                "type": "json_schema",
                "schema": schema
            }
        },
        "system": system,
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

async fn call_openai(cfg: &LlmConfig, context: &str, system: &str) -> Result<RawSignal, LlmError> {
    let body = serde_json::json!({
        "model": cfg.resolved_model(),
        // Widely supported across OpenAI-compatible providers; parsing is still
        // defensive in case a provider ignores it or wraps the JSON.
        "response_format": { "type": "json_object" },
        "messages": [
            { "role": "system", "content": system },
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

/// Schema for the reference-class protocol. `baseRate` is listed before
/// `probability` deliberately: with structured decoding the model emits the
/// fields in schema order, so the outside view is committed to before the
/// final answer rather than reverse-engineered to match it.
fn forecast_schema() -> serde_json::Value {
    serde_json::json!({
        "type": "object",
        "properties": {
            "baseRate": { "type": "number" },
            "keyDrivers": { "type": "array", "items": { "type": "string" } },
            "evidenceFor": { "type": "array", "items": { "type": "string" } },
            "evidenceAgainst": { "type": "array", "items": { "type": "string" } },
            "probability": { "type": "number" },
            "direction": { "type": "string", "enum": ["long", "short", "neutral"] },
            "confidence": { "type": "number" },
            "rationale": { "type": "string" }
        },
        "required": [
            "baseRate", "keyDrivers", "evidenceFor", "evidenceAgainst",
            "probability", "direction", "confidence", "rationale"
        ],
        "additionalProperties": false
    })
}

/// Build the market description handed to every model in the ensemble.
///
/// Kept in one place so all providers see byte-identical context — if one model
/// were shown a different framing, disagreement between them would measure the
/// prompt rather than the question.
pub struct PromptContext<'a> {
    pub question: &'a str,
    pub is_prediction: bool,
    /// Implied probability (event market) or last price (directional).
    pub price: f64,
    pub change_24h: f64,
    pub liquidity: Option<f64>,
    pub days_to_resolution: Option<f64>,
    /// Recent closes/odds, oldest first.
    pub history: &'a [f64],
    /// Horizon for a directional question, in bars.
    pub horizon_bars: usize,
    /// Anything the operator wants the models to weigh (news, notes).
    pub notes: &'a str,
}

impl PromptContext<'_> {
    pub fn render(&self) -> String {
        let mut s = String::new();
        if self.is_prediction {
            s.push_str(&format!(
                "QUESTION: {}\nMARKET IMPLIED PROBABILITY: {:.1}%\n",
                self.question,
                self.price * 100.0
            ));
            match self.days_to_resolution {
                Some(d) => s.push_str(&format!("TIME TO RESOLUTION: {d:.1} days\n")),
                None => s.push_str("TIME TO RESOLUTION: unknown\n"),
            }
        } else {
            s.push_str(&format!(
                "INSTRUMENT: {}\nLAST PRICE: {:.4}\n24H CHANGE: {:+.2}%\n\
                 QUESTION: will the price be HIGHER after {} more bars?\n",
                self.question,
                self.price,
                self.change_24h * 100.0,
                self.horizon_bars
            ));
        }
        if let Some(l) = self.liquidity {
            s.push_str(&format!("LIQUIDITY: ${l:.0}\n"));
        }
        if self.history.len() >= 4 {
            let tail: Vec<String> = self
                .history
                .iter()
                .rev()
                .take(12)
                .rev()
                .map(|v| format!("{v:.4}"))
                .collect();
            s.push_str(&format!("RECENT SERIES (oldest→newest): {}\n", tail.join(", ")));
        }
        if !self.notes.trim().is_empty() {
            s.push_str(&format!("OPERATOR NOTES: {}\n", self.notes.trim()));
        }
        s.push_str(
            "\nYou have no live news feed. Do not assume events after your training data, and do \
             not invent sources. If the decisive information is missing, say so and stay near the \
             base rate.",
        );
        s
    }
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
        // Exercise the clamp logic in `ask`'s post-processing without a call.
        let raw = RawSignal {
            probability: 1.5,
            direction: Direction::Neutral,
            confidence: -1.0,
            rationale: "x".into(),
            base_rate: Some(2.0),
            key_drivers: vec![],
            evidence_for: vec![],
            evidence_against: vec![],
        };
        assert_eq!(raw.probability.clamp(0.0, 1.0), 1.0);
        assert_eq!(raw.confidence.clamp(0.0, 1.0), 0.0);
        assert_eq!(raw.base_rate.map(|b| b.clamp(0.0, 1.0)), Some(1.0));
    }

    #[test]
    fn the_forecast_protocol_parses_and_the_quick_one_still_does() {
        let full = parse_raw(
            r#"{"baseRate":0.12,"keyDrivers":["turnout"],"evidenceFor":["polls"],
                "evidenceAgainst":["history"],"probability":0.18,"direction":"long",
                "confidence":0.4,"rationale":"slightly above base rate"}"#,
        )
        .unwrap();
        assert_eq!(full.base_rate, Some(0.12));
        assert_eq!(full.evidence_for.len(), 1);
        assert_eq!(full.evidence_against.len(), 1);

        // A provider that ignores the richer schema still yields a usable signal.
        let minimal = parse_raw(
            r#"{"probability":0.5,"direction":"neutral","confidence":0.1,"rationale":"no view"}"#,
        )
        .unwrap();
        assert_eq!(minimal.base_rate, None);
        assert!(minimal.key_drivers.is_empty());
    }

    #[test]
    fn the_forecast_prompt_puts_the_base_rate_before_the_answer() {
        // Structured decoding emits fields in schema order, so this ordering is
        // what makes the outside view a commitment rather than a rationalisation.
        let schema = forecast_schema();
        let props = schema.get("properties").unwrap().as_object().unwrap();
        let keys: Vec<&String> = props.keys().collect();
        let base = keys.iter().position(|k| *k == "baseRate").unwrap();
        let prob = keys.iter().position(|k| *k == "probability").unwrap();
        assert!(base < prob, "baseRate must be committed to before probability");
    }

    #[test]
    fn an_event_prompt_states_the_market_price_and_the_time_left() {
        let ctx = PromptContext {
            question: "Will the Fed cut before September?",
            is_prediction: true,
            price: 0.62,
            change_24h: 0.03,
            liquidity: Some(320_000.0),
            days_to_resolution: Some(45.0),
            history: &[0.55, 0.57, 0.60, 0.62],
            horizon_bars: 40,
            notes: "",
        };
        let s = ctx.render();
        assert!(s.contains("62.0%"), "the market anchor must be explicit:\n{s}");
        assert!(s.contains("45.0 days"));
        assert!(s.contains("RECENT SERIES"));
        assert!(s.contains("do not invent sources") || s.contains("not invent"));
    }

    #[test]
    fn a_directional_prompt_asks_a_question_that_can_actually_be_scored() {
        let ctx = PromptContext {
            question: "BTC/USD",
            is_prediction: false,
            price: 67_250.0,
            change_24h: -0.018,
            liquidity: None,
            days_to_resolution: None,
            history: &[],
            horizon_bars: 40,
            notes: "operator thinks the ETF flow story matters",
        };
        let s = ctx.render();
        assert!(s.contains("HIGHER after 40 more bars"), "{s}");
        assert!(s.contains("-1.80%"));
        assert!(s.contains("ETF flow"), "operator notes must reach the model");
        assert!(!s.contains("LIQUIDITY"), "unknown fields are omitted, not sent as 0");
    }

    #[tokio::test]
    async fn an_ensemble_with_no_keys_returns_one_error_per_provider_not_a_failure() {
        // Every provider fails on the missing key, and none of them takes the
        // batch down: the caller pools whatever came back, which here is nothing.
        let cfgs = vec![
            LlmConfig::new(Provider::Anthropic, "", ""),
            LlmConfig::new(Provider::OpenAI, "", ""),
        ];
        let out = ensemble(cfgs, "context").await;
        assert_eq!(out.len(), 2);
        assert!(out.iter().all(|(_, r)| matches!(r, Err(LlmError::NoKey(_)))));
        // Sorted, so the UI does not reshuffle between refreshes.
        assert_eq!(out[0].0, "anthropic");
        assert_eq!(out[1].0, "openai");
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
