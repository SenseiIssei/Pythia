"""Discord's REST API with the standard library, as the bot.

The token goes into the Authorization header and nowhere else: an error names the HTTP
status, the method and the route, never the token. A 429 is waited out (Discord says how
long) up to three times. `transport(method, url, headers, data) -> (status, bytes)` replaces
the network in the tests.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://discord.com/api/v10"
UA = "DiscordBot (https://github.com/SenseiIssei/Pythia, 1.0)"


class DiscordError(Exception):
    def __init__(self, status: int, method: str, path: str):
        super().__init__(f"HTTP {status} on {method} {path}")
        self.status = status


def urllib_transport(method: str, url: str, headers: dict, data: bytes | None, timeout: float = 20):
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b""
    except (urllib.error.URLError, OSError, ValueError):
        return 0, b""


class Rest:
    def __init__(self, token: str, transport=None, sleep=time.sleep):
        self._token = token
        self.transport = transport or urllib_transport
        self.sleep = sleep

    def __repr__(self) -> str:                               # never the token, not even in a traceback
        return "Rest(<token>)"

    def request(self, method: str, path: str, body=None, reason: str | None = None):
        headers = {"Authorization": f"Bot {self._token}", "User-Agent": UA}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if reason:
            headers["X-Audit-Log-Reason"] = urllib.parse.quote(reason)
        for _ in range(4):
            status, raw = self.transport(method, API + path, headers, data)
            if status == 429:
                try:
                    wait = float(json.loads(raw or b"{}").get("retry_after") or 1)
                except (ValueError, AttributeError):
                    wait = 1.0
                self.sleep(min(max(wait, 0.1), 30.0))
                continue
            if not 200 <= status < 300:
                raise DiscordError(status, method, path)
            return json.loads(raw) if raw else None
        raise DiscordError(429, method, path)

    def get(self, path: str):
        return self.request("GET", path)

    def post(self, path: str, body=None, reason: str | None = None):
        return self.request("POST", path, body if body is not None else {}, reason)

    def put(self, path: str, body=None, reason: str | None = None):
        return self.request("PUT", path, body, reason)

    def patch(self, path: str, body=None, reason: str | None = None):
        return self.request("PATCH", path, body, reason)
