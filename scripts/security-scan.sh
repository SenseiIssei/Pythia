#!/bin/sh
# Pythia security scan: secrets in the whole history, known vulnerabilities in
# every dependency set, and the SBOMs for a release.
#
#   sh scripts/security-scan.sh            (or: npm run security:scan)
#   SCAN_OUT=/some/dir sh scripts/security-scan.sh
#
# Runs, each only when its tool is installed (a missing tool is reported as
# SKIPPED, never as a pass):
#   gitleaks        whole git history (every local and remote ref), .gitleaks.toml
#   pytest          the research agent's guard tests (research/ops/agent/test_guard.py)
#   cargo audit    Cargo.lock against the RustSec advisory database
#   npm audit       the shipped npm dependencies (--omit=dev), then all of them
#   pip-audit       research/lab and research/recorder requirements
#   SBOM            CycloneDX for the Rust crates (cargo-cyclonedx) and npm (npm sbom)
#
# Reports and SBOMs go to security-reports/ (gitignored). Attach the SBOMs to a
# GitHub release; they are not committed because they change with every lockfile
# update. Exit status: 0 when nothing failed, 1 otherwise.
#
# Tools:
#   gitleaks        https://github.com/gitleaks/gitleaks/releases (official binary)
#   cargo-audit     cargo install cargo-audit --locked
#   cargo-cyclonedx cargo install cargo-cyclonedx --locked
#   pip-audit       pipx install pip-audit   (or uvx pip-audit)

set -u
root=$(git rev-parse --show-toplevel) || exit 1
cd "$root" || exit 1
out=${SCAN_OUT:-security-reports}
mkdir -p "$out/sbom"
summary=""
failed=0

note() { summary="$summary$(printf '%-34s %s' "$1" "$2")
"; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------- secrets
if have gitleaks; then
  if gitleaks git --log-opts="--all" --config .gitleaks.toml --redact --no-banner \
      --report-format json --report-path "$out/gitleaks-history.json" . >"$out/gitleaks.log" 2>&1; then
    note "gitleaks (all history)" "PASS"
  else
    note "gitleaks (all history)" "FAIL, see $out/gitleaks-history.json (redacted)"
    failed=1
  fi
else
  note "gitleaks (all history)" "SKIPPED (gitleaks not installed)"
fi

# ---------------------------------------------------------------- the research agent's guard
# Its patterns and rules against every case of the 2026-10-22 audit (research/ops/README.md).
if have python3 && python3 -c "import pytest, fcntl" >/dev/null 2>&1; then
  if python3 -m pytest -q -p no:cacheprovider research/ops/agent/test_guard.py >"$out/guard-tests.txt" 2>&1; then
    note "agent guard tests" "PASS"
  else
    note "agent guard tests" "FAIL, see $out/guard-tests.txt"
    failed=1
  fi
else
  note "agent guard tests" "SKIPPED (needs python3 with pytest, Linux or macOS)"
fi

# ---------------------------------------------------------------- Rust
if cargo audit --version >/dev/null 2>&1; then
  if cargo audit >"$out/cargo-audit.txt" 2>&1; then
    warn=$(grep -c '^Warning:' "$out/cargo-audit.txt" || true)
    note "cargo audit" "PASS ($warn warnings: unmaintained or unsound, see SECURITY.md)"
  else
    note "cargo audit" "FAIL, see $out/cargo-audit.txt"
    failed=1
  fi
else
  note "cargo audit" "SKIPPED (cargo-audit not installed)"
fi

# ---------------------------------------------------------------- npm
if have npm; then
  if npm audit --omit=dev >"$out/npm-audit-prod.txt" 2>&1; then
    note "npm audit --omit=dev" "PASS"
  else
    note "npm audit --omit=dev" "FAIL, see $out/npm-audit-prod.txt"
    failed=1
  fi
  # Build tooling: reported, not a failure on its own (see SECURITY.md for
  # what has no fix yet). Read the file before a release.
  if npm audit >"$out/npm-audit-all.txt" 2>&1; then
    note "npm audit (with dev tooling)" "PASS"
  else
    note "npm audit (with dev tooling)" "REVIEW, $(grep -Eo '[0-9]+ (low|moderate|high|critical)[^,]*vulnerabilit[a-z]*' "$out/npm-audit-all.txt" | head -1)"
  fi
else
  note "npm audit" "SKIPPED (npm not installed)"
fi

# ---------------------------------------------------------------- Python
pip_audit=""
if have pip-audit; then
  pip_audit="pip-audit"
elif have uvx; then
  pip_audit="uvx pip-audit"
fi
for req in research/lab/requirements.txt research/recorder/requirements.txt; do
  [ -f "$req" ] || continue
  name=$(echo "$req" | cut -d/ -f2)
  if [ -z "$pip_audit" ]; then
    note "pip-audit ($name)" "SKIPPED (pip-audit not installed)"
  elif $pip_audit -r "$req" --progress-spinner off >"$out/pip-audit-$name.txt" 2>&1; then
    note "pip-audit ($name)" "PASS"
  else
    note "pip-audit ($name)" "FAIL, see $out/pip-audit-$name.txt"
    failed=1
  fi
done

# ---------------------------------------------------------------- SBOM
if cargo cyclonedx --version >/dev/null 2>&1; then
  if cargo cyclonedx --format json --spec-version 1.5 >"$out/cyclonedx.log" 2>&1; then
    for f in crates/pythia-core server src-tauri crates/pythia-ml cli; do
      for s in "$f"/*.cdx.json; do
        [ -f "$s" ] && mv "$s" "$out/sbom/$(basename "$f")-rust.cdx.json"
      done
    done
    note "SBOM (Rust, CycloneDX)" "written to $out/sbom/"
  else
    note "SBOM (Rust, CycloneDX)" "FAIL, see $out/cyclonedx.log"
    failed=1
  fi
else
  note "SBOM (Rust, CycloneDX)" "SKIPPED (cargo-cyclonedx not installed)"
fi
if have npm && npm sbom --sbom-format cyclonedx --omit dev >"$out/sbom/pythia-ui-npm.cdx.json" 2>"$out/npm-sbom.log"; then
  note "SBOM (npm, CycloneDX)" "written to $out/sbom/"
else
  note "SBOM (npm, CycloneDX)" "SKIPPED or FAILED, see $out/npm-sbom.log"
fi

# The SBOMs are meant to be published: they must not carry this machine's
# checkout path (cargo-cyclonedx writes file:/// URLs of the workspace members).
for s in "$out"/sbom/*.json; do
  [ -f "$s" ] || continue
  sed -e "s|file:///$root/|file:///pythia/|g" -e "s|$root/|pythia/|g" "$s" >"$s.tmp" && mv "$s.tmp" "$s"
  if grep -q "$root" "$s"; then
    note "SBOM path scrub ($(basename "$s"))" "FAIL, the checkout path is still inside"
    failed=1
  fi
done

stamp=$(date -u +%Y-%m-%dT%H:%MZ)
printf '\nPythia security scan, %s\n\n%s\n' "$stamp" "$summary" | tee "$out/summary.txt"
exit "$failed"
