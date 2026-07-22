//! Optional Discord (or generic) webhook alerts. Native-only — a browser can't
//! POST cross-origin to Discord. One batched message per tick keeps well under
//! rate limits. The webhook URL is stored in the vault under "alerts".

use std::time::Duration;

/// Char-safe truncation to keep within Discord's 2000-char content limit.
fn truncate(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        s.to_string()
    } else {
        let head: String = s.chars().take(max).collect();
        format!("{head}…")
    }
}

/// POST a message to the webhook. Best-effort, time-boxed, never panics.
pub async fn post(webhook: &str, content: &str) {
    if webhook.is_empty() || content.is_empty() {
        return;
    }
    let body = serde_json::json!({ "content": truncate(content, 1900) });
    let _ = tokio::time::timeout(Duration::from_secs(5), async {
        reqwest::Client::new().post(webhook).json(&body).send().await
    })
    .await;
}
