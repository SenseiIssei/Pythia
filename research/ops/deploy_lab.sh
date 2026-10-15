#!/usr/bin/env bash
# Deploy the lab code (research/lab) to the folder the lab image mounts at /app,
# without ever touching what the studies wrote there.
#
#   research/ops/deploy_lab.sh [--dry-run] [--force] [--src DIR] [--dest DIR]
#
# Run it on the server from a checkout of the repo (default: the lab folder
# next to this script, to /opt/pythia-lab). It
#   1. refuses while a job container (pythia-job-*) is running, unless --force,
#      so no job sees half old, half new code;
#   2. rsyncs with --delete, excluding results/ and every cache (excluded paths
#      are neither copied nor deleted on the destination);
#   3. writes a sha256 manifest of what was sent (.deploy-manifest) and checks
#      every file on the destination against it;
#   4. checks that results/ on the destination is exactly as it was before
#      (same files, sizes and times), and fails loudly if not.
# Exit 0 only when all of that holds. .deploy-info says what is deployed.
set -euo pipefail

usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; }

src="$(cd "$(dirname "${BASH_SOURCE[0]}")/../lab" 2>/dev/null && pwd || true)"
dest=/opt/pythia-lab
dry=false
force=false
while [ $# -gt 0 ]; do
  case $1 in
    --dry-run) dry=true ;;
    --force) force=true ;;
    --src) src=${2:?--src needs a folder}; shift ;;
    --dest) dest=${2:?--dest needs a folder}; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

die() { echo "deploy_lab: $*" >&2; exit 1; }

for tool in rsync sha256sum find sort; do
  command -v "$tool" >/dev/null || die "$tool is not installed"
done
[ -n "$src" ] && [ -f "$src/lab/__init__.py" ] || die "no lab code in ${src:-?} (expected lab/__init__.py)"
src=$(cd "$src" && pwd)
case "$dest" in /|"") die "refusing destination '$dest'" ;; esac
[ "$src" != "$(cd "$dest" 2>/dev/null && pwd || echo "$dest")" ] || die "source and destination are the same folder"

# Paths never copied and never deleted on the destination. results/ holds what
# studies wrote on the server; the rest are caches.
excludes=(
  /results/
  /.deploy-manifest
  /.deploy-info
  .git/
  __pycache__/
  '*.pyc'
  .pytest_cache/
  .mypy_cache/
  .ruff_cache/
  .cache/
  /cache/
  '*.egg-info/'
  .venv/
)
rsync_ex=()
for e in "${excludes[@]}"; do rsync_ex+=(--exclude "$e"); done

if [ "$force" = false ] && command -v docker >/dev/null; then
  running=$(docker ps --filter label=pythia.job --format '{{.Names}}' 2>/dev/null || true)
  [ -z "$running" ] || die "jobs are running ($(echo "$running" | tr '\n' ' ')); wait, or --force"
fi

# What results/ looks like now: path, size, modification time.
snapshot() {
  if [ -d "$dest/results" ]; then
    (cd "$dest/results" && find . -type f -printf '%p %s %T@\n' | LC_ALL=C sort)
  fi
}

# Every file the deploy is responsible for, as the receiving side will see it.
manifest_of() {
  (cd "$1" && rsync -a --dry-run --out-format='%n' "${rsync_ex[@]}" ./ /nonexistent-pythia-target/ 2>/dev/null \
    | grep -v '/$' | grep -v '^\./$' | LC_ALL=C sort | tr '\n' '\0' | xargs -0 -r sha256sum)
}

if [ "$dry" = true ]; then
  echo "deploy_lab: dry run, $src -> $dest"
  rsync -a --delete --dry-run --itemize-changes "${rsync_ex[@]}" "$src/" "$dest/"
  exit 0
fi

mkdir -p "$dest"
before=$(snapshot)
manifest=$(mktemp)
trap 'rm -f "$manifest"' EXIT
manifest_of "$src" > "$manifest"
[ -s "$manifest" ] || die "empty manifest, nothing to deploy"

rsync -a --delete "${rsync_ex[@]}" "$src/" "$dest/"
install -m 644 "$manifest" "$dest/.deploy-manifest"

# 3. every deployed file matches
if ! (cd "$dest" && sha256sum --check --quiet --strict .deploy-manifest); then
  die "manifest check failed on $dest"
fi
# and nothing deployable is on the destination that the source does not have
extra=$(comm -13 <(cut -c67- "$manifest" | LC_ALL=C sort) \
                 <(manifest_of "$dest" | cut -c67- | LC_ALL=C sort))
[ -z "$extra" ] || die "files on $dest that are not in the source: $extra"

# 4. results/ untouched
after=$(snapshot)
if [ "$before" != "$after" ]; then
  diff <(echo "$before") <(echo "$after") >&2 || true
  die "results/ on $dest changed during the deploy"
fi

commit=$(git -C "$src" rev-parse --short HEAD 2>/dev/null || echo unknown)
files=$(wc -l < "$manifest" | tr -d ' ')
printf '{"at":"%s","commit":"%s","files":%s,"manifestSha256":"%s"}\n' \
  "$(date -u +%FT%TZ)" "$commit" "$files" "$(sha256sum "$dest/.deploy-manifest" | cut -d' ' -f1)" \
  > "$dest/.deploy-info"
echo "deploy_lab: $files files at $commit deployed to $dest, manifest ok, results/ untouched"
