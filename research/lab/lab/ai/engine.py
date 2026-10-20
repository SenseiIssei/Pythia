"""The engine's metered Claude call, from the lab: POST /api/ai/complete.

The engine checks its budget before anything is sent and writes every call
to its ledger. This module only builds the request and reads the answer.

Environment: ANTHROPIC_API_KEY (from /etc/pythia/alerts.env; only its hash
is sent, as proof this job holds the same key as the engine), PYTHIA_AI_URL
(default: the autopilot engine on 127.0.0.1:8788). Standard library only.

The key is a secret: never printed, logged, written or sent.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8788/api/ai/complete"
ROUTINE = "claude-haiku-5-5"
REVIEW = "claude-sonnet-5-5"
DEEP = "claude-opus-5-5"
MODELS = (ROUTINE, REVIEW, DEEP)
EFFORTS = ("low", "medium", "high", "xhigh", "max")


def model_for(job: str, default: str) -> str:
    """The model a job calls: PYTHIA_AI_MODEL_<JOB> (brief, director, critic,
    ask, weekly) when it names haiku, sonnet, opus or a full model id the
    engine prices, else the job's default. The engine refuses an unpriced
    model, so a typo fails loudly instead of costing more."""
    v = (os.environ.get(f"PYTHIA_AI_MODEL_{job.upper().replace('-', '_')}") or "").strip().lower()
    return {"haiku": ROUTINE, "sonnet": REVIEW, "opus": DEEP}.get(v, v if v.startswith("claude-") else default)


def effort_for(job: str, default: str) -> str:
    """PYTHIA_AI_EFFORT_<JOB> when it is one of low to max, else the default."""
    v = (os.environ.get(f"PYTHIA_AI_EFFORT_{job.upper().replace('-', '_')}") or "").strip().lower()
    return v if v in EFFORTS else default


class AiError(Exception):
    """A call that did not produce an answer. `kind`: nokey, budget, down,
    timeout, failed, unreadable."""

    def __init__(self, kind: str, message: str, cost_usd: float = 0.0):
        super().__init__(message)
        self.kind = kind
        self.cost_usd = cost_usd


def token(key: str | None = None) -> str:
    """Hex SHA-256 of pythia-ai:<key>, the same as the engine's caller_token."""
    k = (key if key is not None else os.environ.get("ANTHROPIC_API_KEY", "")).strip()
    return hashlib.sha256(f"pythia-ai:{k}".encode("utf-8")).hexdigest() if k else ""


def url() -> str:
    return (os.environ.get("PYTHIA_AI_URL") or DEFAULT_URL).strip()


def _post(target: str, body: dict, tok: str, timeout: float) -> tuple[int, dict]:
    req = urllib.request.Request(target, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "x-pythia-ai-token": tok,
                                          "User-Agent": "pythia-lab-ai"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        raw = e.read() if hasattr(e, "read") else b""
        code = e.code
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        data = {"error": raw[:300].decode("utf-8", "replace")}
    return code, data if isinstance(data, dict) else {"error": str(data)[:300]}


def complete(job: str, system: str, user: str, max_tokens: int, model: str = ROUTINE,
             schema: dict | None = None, effort: str = "low", batch: bool = False,
             batch_wait_sec: int = 1200, timeout: float | None = None, poster=None) -> dict:
    """One call. Returns the engine's answer: {text, json, parseError, model,
    servedBy, usage, costUsd, batchId, latencyMs}. Raises AiError when there
    was no answer, and when the answer did not parse against `schema` (kind
    unreadable; the call was billed and is in the ledger all the same).

    `poster(url, body, token, timeout) -> (status, dict)` replaces the network
    (tests)."""
    tok = token()
    if not tok:
        raise AiError("nokey", "no ANTHROPIC_API_KEY in this job's environment: nothing called")
    body = {"job": job, "model": model, "system": system, "user": user, "maxTokens": int(max_tokens),
            "effort": effort, "batch": bool(batch)}
    if schema is not None:
        body["schema"] = schema
    if batch:
        body["batchWaitSec"] = int(batch_wait_sec)
    wait = timeout if timeout is not None else (batch_wait_sec + 120 if batch else 300)
    send = poster or _post
    try:
        code, data = send(url(), body, tok, wait)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        reason = getattr(e, "reason", None)
        raise AiError("down", f"the engine did not answer ({type(reason).__name__ if isinstance(reason, BaseException) else type(e).__name__})")
    err = str(data.get("error") or "")[:400]
    if code == 402:
        raise AiError("budget", err or "the AI budget refused the call")
    if code == 503:
        raise AiError("nokey", err or "the engine has no Claude API key")
    if code == 504:
        raise AiError("timeout", err or "no answer in time")
    if code != 200:
        raise AiError("failed", f"HTTP {code}: {err}")
    cost = float(data.get("costUsd") or 0.0)
    if schema is not None and not isinstance(data.get("json"), dict):
        raise AiError("unreadable", f"the answer was not the JSON asked for: {data.get('parseError') or 'no object'}", cost)
    return data
