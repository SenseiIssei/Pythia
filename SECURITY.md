# Security policy

Pythia handles exchange and broker API keys and can place real orders. Security
reports are welcome and are treated with priority.

## Supported versions

| Version | Supported |
| --- | --- |
| 0.5.x (the latest release) | yes |
| older releases | no, please update |

Security fixes land on the newest release line only. There is no long-term
support branch.

## Reporting a vulnerability

Please report privately, never in a public issue, discussion or pull request.

1. Open the repository on GitHub, go to **Security**, then **Report a
   vulnerability** (GitHub's private vulnerability reporting). The report is
   visible only to the maintainer.
2. Describe what is affected (component, version or commit), how to reproduce
   it, and what an attacker gains. A proof of concept helps; please do not use
   real third-party accounts or money to demonstrate it.
3. If you found a leaked credential in the repository or its history, say where
   (commit and path), but do not paste the secret itself.

### What happens next

| Step | Target time |
| --- | --- |
| Acknowledgement of the report | within 7 days |
| First assessment (valid or not, severity) | within 14 days |
| Fix or mitigation for a confirmed high or critical issue | within 30 days |
| Fix for other confirmed issues | within 90 days |

### Coordinated disclosure

We ask you to keep the issue confidential until a fix is released, or until 90
days after the report, whichever comes first. Once fixed, the issue is published
as a GitHub security advisory with credit to the reporter (unless you prefer to
stay anonymous). If a fix needs longer, we agree a new date with you.

This is a non-commercial open source project maintained in spare time; there is
no bug bounty.

## Security model

What Pythia protects, and what it relies on you to do.

### Secrets

- **Desktop app:** API keys are kept in the operating system's keychain
  (Windows Credential Manager, macOS Keychain, Secret Service on Linux), never in
  files, the frontend bundle or logs. Settings can remove each key again.
- **Server and research lab:** keys come from environment variables, usually a
  `.env` file or a root-only env file on the server. `.env` files, key files and
  wallet files are gitignored, and the pre-commit hook refuses them.
- Grant exchange keys **trade permission only, never withdrawal**. A leaked key
  then costs trades, not coins.
- Keys are never written to logs. Startup lines name which providers and venues
  are configured, at most with the last four characters of a key id. Webhook
  URLs and the Telegram bot token are scrubbed from every error the alert sender
  records or returns, and the lab's HTTP clients report only the kind of a
  network failure, never the URL (which holds the token).
- The pump.fun wallet tool is the only code that creates a key. It writes the
  key file with mode 600 outside the code folder, shows the secret once at an
  interactive terminal after a typed confirmation, and never logs it. Only the
  live executor reads the file, at runtime, after all of its gates hold.

### The HTTP server (`server/`)

The standalone server has **no login of its own**. That is a deliberate design
decision: it is a single-user engine, and authentication belongs in front of it.

- It listens on **127.0.0.1:8787** unless `PYTHIA_BIND` says otherwise, and
  warns at startup when bound to a non-loopback address. In a container, bind
  `0.0.0.0` inside and publish the port on the host's loopback only
  (`-p 127.0.0.1:8787:8787`), as `server/Dockerfile` shows.
- To reach it from another machine, put it behind a reverse proxy that
  authenticates every request (for example an SSO proxy, mutual TLS, or at the
  very least HTTP basic auth over TLS), or use an SSH tunnel. Never expose the
  port directly to the internet.
- **Cross-site requests:** state-changing requests (every `POST`) and the
  WebSocket stream are refused when the browser sends an `Origin` that is not
  allowed. Allowed are `http://localhost`, `http://127.0.0.1` and `http://[::1]`
  on any port, the desktop app's own origins, and what `PYTHIA_ALLOWED_ORIGINS`
  lists. CORS answers the same origins only. Requests without an `Origin`
  (scripts, the lab's jobs, `curl`) are not affected.
- **DNS rebinding:** the server answers only requests whose `Host` is a loopback
  name, an IP address, `host.docker.internal`, or a name in
  `PYTHIA_ALLOWED_HOSTS` (or the host of an allowed origin). Set
  `PYTHIA_ALLOWED_HOSTS` to the name your reverse proxy forwards, or make the
  proxy forward to `127.0.0.1`.
- **Local-only endpoints:** `POST /api/alerts/event` and `POST /api/ai/complete`
  are taken from this machine (or the addresses in `PYTHIA_ALERT_EVENT_FROM`)
  only, and never when the request carries proxy headers (`Forwarded`,
  `X-Forwarded-For`, `X-Forwarded-Host`, `X-Real-IP`), because behind a local
  proxy every caller looks like 127.0.0.1. The AI endpoint additionally requires
  a token derived from the server's Anthropic key (a SHA-256 of it, compared in
  constant time), so a caller must hold the key itself, and every call goes
  through the spending caps.
- **Input checks:** requests are typed JSON with bounds on every number that
  matters (alert mute at most seven days, AI caps, token limits, prompt size,
  event sizes). An event image must be a PNG or JPEG inside the data folder
  (resolved with symlinks, so `..` and links cannot leave it), at most 10 MB.
  Error messages name no file system paths and no secrets.
- Real money stays behind the same gates as in the desktop app: typed
  confirmations, the risk manager, a read-only credential check before arming,
  the kill switch.

### The desktop app (`src-tauri/`)

- A strict content security policy: scripts only from the app itself, no
  `eval`, no plugins (`object-src 'none'`), and network access only to the
  market data and broker endpoints it uses.
- The frontend can call only the app's own commands plus window controls,
  notifications, dialogs and opening `https://` links in the system browser.
  There is no shell execute or spawn permission and no file system access from
  the frontend.
- Only `VITE_` and `TAURI_ENV_` variables are exposed to the bundle, so build
  secrets such as a signing key can never be inlined into it.

### The research lab (`research/`)

- Jobs read their keys from the environment and send them in headers, except
  the Telegram Bot API, which requires the token in the URL; that URL is never
  printed or logged.
- The pump.fun live executor sends only to `https` RPC endpoints and refuses
  bundle, relay and MEV services unless the owner switches one on explicitly.

## Known issues without a fix yet

Checked with `scripts/security-scan.sh`. None of these is exploitable through
Pythia as far as we know; each is re-checked on every scan.

| Component | Advisory | Why it stays for now |
| --- | --- | --- |
| `glib` 0.18 (Rust, Linux only) | RUSTSEC-2024-0429, unsound `VariantStrIter` | Pulled in by Tauri's GTK 0.18 stack on Linux. The fix is in glib 0.20, which Tauri 2 does not use yet. Pythia ships for Windows and never calls this iterator. Goes away with Tauri's move to newer gtk-rs. |
| `proc-macro-error`, `unic-*`, `zbus_names`, `zvariant*` (Rust) | unmaintained (RUSTSEC-2024-0370, -2025-0075/0080/0081/0098/0100, -2026-0370/0371/0372) | Transitive dependencies of Tauri (build-time macros, URL pattern parsing, Linux D-Bus notifications). No known vulnerability; replaced when Tauri replaces them. |
| `braces` via `tailwindcss` 3 (npm, build tooling only) | GHSA-vfj7-8cjw-p6xm, stack exhaustion on deeply nested patterns | No fixed version exists. It only parses the glob patterns in `tailwind.config.js`, which are ours; nothing from users or the network reaches it, and it is not part of the shipped app (`npm audit --omit=dev` is clean). Removed with the move to Tailwind 4. |

## Tooling

- `npm run hooks:install` (or `git config core.hooksPath scripts/hooks`) once
  per clone: the pre-commit hook runs gitleaks on the staged changes and a fast
  pattern check for tokens, keys, wallet arrays, personal paths, public IP
  addresses and e-mail addresses.
- `npm run security:scan` (`sh scripts/security-scan.sh`): gitleaks over the
  whole history, `cargo audit`, `npm audit`, `pip-audit` for the lab, and the
  CycloneDX SBOMs. Run it before every release.

See also [docs/security/practices.md](docs/security/practices.md) for the
project's security practices (inspired by the essential requirements of the EU
Cyber Resilience Act, without any claim of compliance or certification), and
[SAFETY.md](SAFETY.md) for the financial risks.
