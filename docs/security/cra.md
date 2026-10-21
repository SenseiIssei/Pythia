# Pythia and the EU Cyber Resilience Act

This note records how Pythia relates to the Cyber Resilience Act
(Regulation (EU) 2024/2847, "CRA") and how its security work maps to the
CRA's essential requirements. It is an engineering record, not legal advice.

## Product and scope

**What Pythia is.** A trading and research cockpit: a Rust engine
(`crates/pythia-core`), a desktop app (Tauri, `src-tauri/`, with the React UI in
`src/`), an optional headless HTTP server (`server/`) and a Python research lab
(`research/`). It runs on the user's own machine or server, paper trading by
default, and can route orders to brokers and exchanges with the user's own API
keys.

**Status under the CRA.** Pythia is free and open source software developed and
published without any commercial activity: it is not sold, there is no paid
version, no paid support, no hosting service, and no personal data is collected
for monetisation. Software of this kind is not "made available on the market in
the course of a commercial activity", so the manufacturer obligations of the CRA
do not apply to it (recitals 18 and 19). Nor is there an open-source steward in
the sense of Article 24 (an organisation that systematically supports the
project's development for commercial use by others).

The obligations therefore apply **in a limited way, by choice**: the project
follows the essential requirements of Annex I as good practice, so that anyone
who integrates Pythia into a commercial product (and becomes a manufacturer
with full obligations, Article 13(5)) starts from a well documented base. If the
project ever becomes commercial (for example sold, offered as a paid service,
or monetised through personal data), this document has to be revisited first;
the reporting obligations of Article 14 apply to manufacturers since
11 September 2026 and the remaining obligations from 11 December 2027.

Pythia is published under the MIT licence (`LICENSE`), which allows free
access, use, modification and redistribution, as the CRA's definition of free
and open-source software requires (Article 3(48)).

## Essential requirements (Annex I, Part I)

| Requirement | What Pythia does | Status |
| --- | --- | --- |
| (1) Security appropriate to the risks | Real money sits behind several independent gates: paper mode by default, per-venue arming with a typed confirmation, a read-only credential check before arming, per-strategy live switch, the risk manager with kill switch and loss caps (SAFETY.md). | done |
| (2a) No known exploitable vulnerabilities at release | `scripts/security-scan.sh` runs `cargo audit`, `npm audit` and `pip-audit` before a release; known, non-exploitable leftovers are listed with reasons in SECURITY.md. | done, run before each release |
| (2b) Secure by default configuration | Paper mode by default; the server binds to 127.0.0.1; live arming, AI overlay and model sweeps are off until the owner enables them; exchange keys documented as trade-only. | done |
| (2c) Security updates | Updates are published as releases on GitHub; the app has no automatic updater, so users update by installing the new release. Security fixes are announced as GitHub security advisories. | partial (no auto update, documented) |
| (2d) Protection from unauthorised access | Desktop: commands only from the bundled frontend, strict CSP. Server: loopback by default, origin and host checks against cross-site requests and DNS rebinding, local-only endpoints refuse proxied callers, AI endpoint needs a key-derived token; remote access only through an authenticating reverse proxy (SECURITY.md). | done (server login delegated to a proxy by design) |
| (2e) Confidentiality of stored and transmitted data | API keys in the OS keychain (desktop) or root-only environment files (server); never in the repository, the bundle or logs; all venue traffic over HTTPS/TLS (rustls); wallet key file mode 600 outside the code folder. | done |
| (2f) Integrity of data, commands and configuration | Typed, validated API inputs with bounds; state files written atomically; an unreadable state file is moved aside instead of overwritten; frozen model files are checked by SHA-256. | done |
| (2g) Data minimisation | No telemetry, no accounts, no analytics. The app stores only what it needs to trade and report (positions, fills for the tax record, settings) on the user's own machine. | done |
| (2h) Availability of essential functions | Network calls never hold the engine lock; feeds fail over between venues; a failed model call is "no opinion", never a reason to stop risk checks; body size and request bounds on the server. | done |
| (2i) Minimise impact on other services | Polling rates are bounded and documented; ensemble sweeps and AI calls are off by default and capped by a spending budget. | done |
| (2j) Limit attack surfaces | Tauri capabilities limited to window controls, notifications, dialogs and `https://` links; no shell execute; only `VITE_`/`TAURI_ENV_` variables reach the bundle; the server exposes no file serving. | done |
| (2k) Reduce the impact of an incident | Trade-only keys; kill switch; daily loss brake; pump.fun live mode with its own hard limits and a one-way kill file; secrets scrubbed from errors. | done |
| (2l) Security-relevant logging | The engine journal records arming, refusals, kill switch, risk trips and every order; the server logs configuration changes (caps, mute, kill) without secrets; operator alerts for kill switch and floors. | done |
| (2m) Secure deletion of data and settings | Settings remove each stored key from the keychain; all other data lives in the app data folder and the configured data folder, which the user can delete. | done (manual) |

## Vulnerability handling (Annex I, Part II)

| Requirement | What Pythia does | Status |
| --- | --- | --- |
| (1) Identify components, SBOM | CycloneDX SBOMs for every Rust crate (`cargo-cyclonedx`) and the shipped npm packages (`npm sbom`), generated by `scripts/security-scan.sh` into `security-reports/sbom/` and attached to each GitHub release. Not committed: they change with every lockfile update and are about 1 MB. Python lab dependencies are listed in `research/lab/requirements.txt` and audited with `pip-audit`. | done |
| (2) Address vulnerabilities without delay | Dependency advisories are checked by the scan script and GitHub Dependabot; response times in SECURITY.md. | done |
| (3) Regular security testing | Unit tests for the security controls (server guards, secret scrubbing, wallet tool checks, local-only endpoints); the scan before each release; secret scanning with push protection on GitHub. | done |
| (4) Disclose fixed vulnerabilities | GitHub security advisories once a fix is released. | done (process) |
| (5) Coordinated vulnerability disclosure policy | SECURITY.md: private reporting, 90-day coordinated disclosure. | done |
| (6) Contact for reports | GitHub private vulnerability reporting (SECURITY.md). | done |
| (7) Secure distribution of updates | Releases are built from tagged commits and published on GitHub over HTTPS. Installer code signing and published checksums are not in place yet. | open: sign installers, publish SHA-256 sums |
| (8) Security updates free of charge, with advisories | All releases are free; advisories explain impact and the fix. | done |

## Preventing leaks into the public repository

- `.gitignore` covers env files, key and wallet files, local data folders and
  scan reports.
- `scripts/hooks/pre-commit` (install with `npm run hooks:install`) runs
  gitleaks on staged changes and a pattern check for bot tokens, API keys,
  private keys, wallet key arrays, personal paths, public IP addresses and
  e-mail addresses.
- `.gitleaks.toml` extends the default rules and allowlists only findings that
  were checked by hand (published API documentation examples, PEM marker text,
  hash ids), each with its reason.
- GitHub secret scanning with push protection is enabled on the repository.

## Release checklist (security part)

1. `npm run security:scan` passes; review `security-reports/npm-audit-all.txt`.
2. Every finding is fixed, or listed with its reason in SECURITY.md.
3. Attach `security-reports/sbom/*.cdx.json` to the GitHub release.
4. Tests green: `cargo test -p pythia-core -p pythia-server`, `npm test`,
   `npm run build`, the lab tests.
