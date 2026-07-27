//! The async side of forecasting: asking models, and feeding the answers back.
//!
//! [`crate::forecast`] is deliberately pure and synchronous — it computes, it
//! never calls anything. This module is the counterpart that talks to providers,
//! and like [`crate::execution`] it is shared by both hosts so the desktop app
//! and the server behave identically.
//!
//! ## Cost is the design constraint
//!
//! An ensemble run is one API call per provider per market. Eight markets across
//! five providers is forty calls, and doing that every tick would be both
//! expensive and pointless: the models are answering questions whose answers
//! move on the scale of hours, not seconds.
//!
//! So model opinions are fetched **rarely and on purpose** — manually from the
//! Predictions page, or on a slow sweep — cached in the engine with a TTL, and
//! folded into a forecast that is recomputed continuously from cheap sources.
//! The expensive input refreshes slowly; the cheap ones refresh constantly.

use crate::engine::Engine;
use crate::llm::{LlmConfig, Provider, PromptContext, Signal};
use std::sync::Mutex;

/// One provider the operator has enabled, with its key and optional model override.
#[derive(Clone)]
pub struct ProviderKey {
    pub provider: Provider,
    pub api_key: String,
    /// Empty → the provider's default model.
    pub model: String,
}

/// Every provider available for ensemble runs in this runtime.
#[derive(Clone, Default)]
pub struct EnsembleKeys {
    pub providers: Vec<ProviderKey>,
}

impl EnsembleKeys {
    /// Collect whatever is configured in the process environment (server side).
    pub fn from_env() -> Self {
        let providers = Provider::ALL
            .into_iter()
            .filter_map(|provider| {
                let model = std::env::var(format!("PYTHIA_MODEL_{}", provider.id().to_uppercase()))
                    .unwrap_or_default();
                if !provider.needs_key() {
                    // Ollama needs no key, so `configured_in_env` reports it as
                    // ready on every machine. Without an explicit model it would
                    // silently join every ensemble and fail against a local
                    // server that is not running.
                    return (!model.trim().is_empty()).then(|| ProviderKey {
                        provider,
                        api_key: String::new(),
                        model,
                    });
                }
                let key = std::env::var(provider.env_key()).ok()?;
                (!key.trim().is_empty()).then(|| ProviderKey { provider, api_key: key, model })
            })
            .collect();
        Self { providers }
    }

    /// Build from a `provider id → key` map (the desktop's vault blob).
    pub fn from_map(get: impl Fn(&str) -> Option<String>) -> Self {
        let providers = Provider::ALL
            .into_iter()
            .filter_map(|provider| {
                if !provider.needs_key() {
                    // Local Ollama needs no key, but only include it if the
                    // operator has actually opted in by naming a model.
                    let model = get(&format!("model:{}", provider.id())).unwrap_or_default();
                    return (!model.is_empty()).then_some(ProviderKey {
                        provider,
                        api_key: String::new(),
                        model,
                    });
                }
                let key = get(provider.id())?;
                (!key.trim().is_empty()).then(|| ProviderKey {
                    provider,
                    api_key: key,
                    model: get(&format!("model:{}", provider.id())).unwrap_or_default(),
                })
            })
            .collect();
        Self { providers }
    }

    pub fn is_empty(&self) -> bool {
        self.providers.is_empty()
    }

    fn configs(&self) -> Vec<LlmConfig> {
        self.providers
            .iter()
            .map(|p| LlmConfig::new(p.provider, p.model.clone(), p.api_key.clone()))
            .collect()
    }
}

/// What one ensemble run produced, for the caller to report.
#[derive(Debug, Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EnsembleRun {
    pub market_id: String,
    pub asked: usize,
    pub answered: usize,
    /// One line per provider that failed, so a missing key or a rate limit is
    /// visible rather than silently reducing the ensemble to one model.
    pub errors: Vec<String>,
}

/// Ask every configured provider about one market, independently, and hand the
/// answers to the engine.
///
/// The engine lock is taken twice — once to read the market, once to write the
/// answers back — and never held across a network call.
pub async fn ensemble_for_market(
    engine: &Mutex<Engine>,
    keys: &EnsembleKeys,
    market_id: &str,
    notes: &str,
) -> Result<EnsembleRun, String> {
    if keys.is_empty() {
        return Err("no AI providers are configured — add a key in Settings".into());
    }

    // Snapshot everything the prompt needs, then let go of the lock.
    let (question, is_prediction, price, change, liquidity, days, history, horizon) = {
        let e = engine.lock().map_err(|_| "engine lock poisoned")?;
        let state = e.state();
        let m = state
            .markets
            .iter()
            .find(|m| m.id == market_id)
            .ok_or_else(|| format!("unknown market {market_id}"))?;
        let cfg = e.forecast_config();
        let days = m
            .resolves_at
            .map(|end| ((end - chrono::Utc::now().timestamp_millis()) as f64 / 86_400_000.0).max(0.0));
        (
            m.symbol.clone(),
            m.kind == crate::engine::MarketKind::Prediction,
            m.price,
            m.change24h,
            m.liquidity,
            days,
            state.history.get(market_id).cloned().unwrap_or_default(),
            cfg.horizon_bars,
        )
    };

    let context = PromptContext {
        question: &question,
        is_prediction,
        price,
        change_24h: change,
        liquidity,
        days_to_resolution: days,
        history: &history,
        horizon_bars: horizon,
        notes,
    }
    .render();

    let cfgs = keys.configs();
    let asked = cfgs.len();
    let results = crate::llm::ensemble(cfgs, &context).await;

    let mut signals: Vec<Signal> = Vec::new();
    let mut errors: Vec<String> = Vec::new();
    for (id, r) in results {
        match r {
            Ok(s) => signals.push(s),
            Err(e) => errors.push(format!("{id}: {e}")),
        }
    }

    let answered = signals.len();
    if answered > 0 {
        engine
            .lock()
            .map_err(|_| "engine lock poisoned")?
            .apply_llm_opinions(market_id, signals);
    }

    Ok(EnsembleRun { market_id: market_id.to_string(), asked, answered, errors })
}

/// Refresh model opinions across the most interesting markets.
///
/// "Interesting" means prediction markets first: they are the questions a
/// language model can actually reason about, as opposed to guessing the next
/// tick of BTC. `limit` bounds the spend — this is the knob that decides whether
/// a sweep costs cents or dollars.
pub async fn sweep(engine: &Mutex<Engine>, keys: &EnsembleKeys, limit: usize) -> Vec<EnsembleRun> {
    if keys.is_empty() || limit == 0 {
        return vec![];
    }
    let targets: Vec<String> = {
        let Ok(e) = engine.lock() else { return vec![] };
        let state = e.state();
        let mut ids: Vec<(bool, f64, String)> = state
            .markets
            .iter()
            .map(|m| {
                (
                    m.kind == crate::engine::MarketKind::Prediction,
                    m.liquidity.unwrap_or(0.0),
                    m.id.clone(),
                )
            })
            .collect();
        // Prediction markets first, then by liquidity: a market nobody trades is
        // not worth an API call.
        ids.sort_by(|a, b| b.0.cmp(&a.0).then(b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal)));
        ids.into_iter().take(limit).map(|(_, _, id)| id).collect()
    };

    let mut out = Vec::new();
    for id in targets {
        match ensemble_for_market(engine, keys, &id, "").await {
            Ok(run) => out.push(run),
            Err(e) => tracing::warn!("ensemble sweep failed for {id}: {e}"),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_provider_with_a_blank_key_is_not_included() {
        let keys = EnsembleKeys::from_map(|id| match id {
            "anthropic" => Some("sk-real".into()),
            "openai" => Some("   ".into()),
            _ => None,
        });
        assert_eq!(keys.providers.len(), 1);
        assert_eq!(keys.providers[0].provider, Provider::Anthropic);
    }

    #[test]
    fn a_model_override_is_carried_through() {
        let keys = EnsembleKeys::from_map(|id| match id {
            "anthropic" => Some("sk-real".into()),
            "model:anthropic" => Some("claude-sonnet-5".into()),
            _ => None,
        });
        assert_eq!(keys.providers[0].model, "claude-sonnet-5");
    }

    #[test]
    fn a_bare_environment_configures_nothing_including_ollama() {
        // `Provider::configured_in_env` reports Ollama as ready everywhere
        // because it needs no key. An ensemble must not inherit that.
        let keys = EnsembleKeys::from_env();
        assert!(
            !keys.providers.iter().any(|p| p.provider == Provider::Ollama),
            "a local model nobody asked for must not join the ensemble"
        );
    }

    #[test]
    fn ollama_is_only_included_when_the_operator_names_a_model() {
        // It needs no key, so without this it would silently join every ensemble
        // and fail on a machine with no local server running.
        let without = EnsembleKeys::from_map(|_| None);
        assert!(without.providers.is_empty());

        let with = EnsembleKeys::from_map(|id| (id == "model:ollama").then(|| "llama3.3".into()));
        assert_eq!(with.providers.len(), 1);
        assert_eq!(with.providers[0].provider, Provider::Ollama);
    }

    #[tokio::test]
    async fn a_run_with_no_providers_says_so_instead_of_pretending() {
        let engine = Mutex::new(Engine::new());
        let err = ensemble_for_market(&engine, &EnsembleKeys::default(), "polymarket:fed-cut-2026", "")
            .await
            .unwrap_err();
        assert!(err.contains("no AI providers"), "{err}");
    }

    #[tokio::test]
    async fn an_unknown_market_is_an_error_not_a_forecast() {
        let engine = Mutex::new(Engine::new());
        let keys = EnsembleKeys {
            providers: vec![ProviderKey {
                provider: Provider::Anthropic,
                api_key: "x".into(),
                model: String::new(),
            }],
        };
        let err = ensemble_for_market(&engine, &keys, "nope:nothing", "").await.unwrap_err();
        assert!(err.contains("unknown market"), "{err}");
    }

    #[tokio::test]
    async fn every_provider_failing_reports_the_reasons_and_records_nothing() {
        let engine = Mutex::new(Engine::new());
        // A key that is present but wrong shape → each provider errors at the
        // network layer. The run must still come back with a readable report.
        let keys = EnsembleKeys {
            providers: vec![ProviderKey {
                provider: Provider::Ollama, // no key needed, but nothing is listening
                api_key: String::new(),
                model: "llama3.3".into(),
            }],
        };
        let run = ensemble_for_market(&engine, &keys, "polymarket:fed-cut-2026", "").await.unwrap();
        assert_eq!(run.asked, 1);
        assert_eq!(run.answered, 0);
        assert_eq!(run.errors.len(), 1, "the reason must be visible: {:?}", run.errors);
    }

    #[tokio::test]
    async fn a_sweep_with_no_keys_is_a_no_op_rather_than_an_error() {
        let engine = Mutex::new(Engine::new());
        assert!(sweep(&engine, &EnsembleKeys::default(), 5).await.is_empty());
    }
}
