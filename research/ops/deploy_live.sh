#!/usr/bin/env bash
# Deploy the lab code that real money runs to /opt/pythia-live, the owner's own copy.
#
#   research/ops/deploy_live.sh [--dry-run] [--force] [--src DIR] [--dest DIR]
#
# Who runs what: the jobs paper-families (writes breakout_top10, the book whose live
# twin trades real money), paper-live-copy (writes the twin), pumpfun-live-simulate
# and the live service pythia-pumpfun-live mount this copy read only at /app. The
# research agent's rounds deploy /opt/pythia-lab (deploy_lab.sh) and never this
# one; only the owner runs this script, by hand, as root. It
#   1. refuses a source with uncommitted changes, and, unless --force, while one of
#      those jobs or the live service runs from this copy (Python imports lazily, so
#      a running service would mix old and new code: stop it, deploy, start it);
#   2. lists the commits since the deployed one that touched research/lab, so the
#      owner sees what goes live (the agent's research commits included);
#   3. rsyncs research/lab with --delete (tests, proposals and every cache left out),
#      owned by root, folders 755, files 644;
#   4. writes a sha256 manifest of the code sent (.deploy-manifest) and checks every
#      file on the destination against it, and that nothing else is there.
# Exit 0 only when all of that holds. .deploy-info says which commit is live.
set -euo pipefail

usage() { sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; }

src=/opt/pythia-src/research/lab
dest=/opt/pythia-live
dry=false
force=false
while [ $# -gt 0 ]; do
  case $1 in
    --dry-run) dry=true ;;
    --force) force=true ;;
    --src) src=${2:?--src needs the research/lab folder of a checkout}; shift ;;
    --dest) dest=${2:?--dest needs a folder}; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

die() { echo "deploy_live: $*" >&2; exit 1; }

for tool in rsync sha256sum find sort git; do
  command -v "$tool" >/dev/null || die "$tool is not installed"
done
[ -f "$src/lab/__init__.py" ] || die "no lab code in $src (expected lab/__init__.py)"
src=$(cd "$src" && pwd)
case "$dest" in /|""|/opt|/opt/pythia-lab|/opt/pythia-lab/*) die "refusing destination '$dest'" ;; esac
[ "$(id -u)" -eq 0 ] || [ "$dry" = true ] || die "run it as root (the copy is root's)"

# 1. a committed source, nothing running from the copy
[ -z "$(git -C "$src" status --porcelain -- . 2>/dev/null)" ] || die "uncommitted changes in $src; deploy a commit"
commit=$(git -C "$src" rev-parse HEAD)
if [ "$force" = false ] && command -v docker >/dev/null; then
  using=""
  for c in $(docker ps --format '{{.Names}}'); do
    if docker inspect -f '{{range .Mounts}}{{.Source}} {{end}}' "$c" 2>/dev/null | tr ' ' '\n' | grep -qx "$dest"; then
      using="$using $c"
    fi
  done
  [ -z "$using" ] || die "running from $dest:$using; stop it first (pythia-pumpfun-live: kill switch, wait until nothing is open, docker stop), or --force"
fi

# 2. what goes live
deployed=$(sed -n 's/.*"commit":"\([0-9a-f]*\)".*/\1/p' "$dest/.deploy-info" 2>/dev/null || true)
if [ -n "$deployed" ] && git -C "$src" cat-file -e "$deployed^{commit}" 2>/dev/null; then
  echo "deploy_live: commits since the live copy ($deployed) that touch research/lab:"
  git -C "$src" log --format='  %h %an %s' "$deployed..$commit" -- . | head -60
else
  echo "deploy_live: no earlier live deploy known; deploying $commit"
fi

excludes=(/tests/ /proposals/ /.deploy-manifest /.deploy-info .git/ __pycache__/ '*.pyc' .pytest_cache/
          .mypy_cache/ .ruff_cache/ .cache/ /cache/ '*.egg-info/' .venv/)
rsync_ex=()
for e in "${excludes[@]}"; do rsync_ex+=(--exclude "$e"); done

manifest_of() {
  (cd "$1" && rsync -a --dry-run --out-format='%n' "${rsync_ex[@]}" ./ /nonexistent-pythia-target/ 2>/dev/null \
    | grep -v '/$' | grep -v '^\./$' | LC_ALL=C sort | tr '\n' '\0' | xargs -0 -r sha256sum)
}

if [ "$dry" = true ]; then
  echo "deploy_live: dry run, $src -> $dest"
  rsync -a --delete --dry-run --itemize-changes "${rsync_ex[@]}" "$src/" "$dest/"
  exit 0
fi

# 3. copy
install -d -m 755 -o root -g root "$dest"
manifest=$(mktemp)
trap 'rm -f "$manifest"' EXIT
manifest_of "$src" > "$manifest"
[ -s "$manifest" ] || die "empty manifest, nothing to deploy"
rsync -a --checksum --delete --no-links --chown=0:0 --chmod=D755,F644 "${rsync_ex[@]}" "$src/" "$dest/"
install -m 644 -o root -g root "$manifest" "$dest/.deploy-manifest"

# 4. check
(cd "$dest" && sha256sum --check --quiet --strict .deploy-manifest) || die "manifest check failed on $dest"
extra=$(comm -13 <(cut -c67- "$manifest" | LC_ALL=C sort) <(manifest_of "$dest" | cut -c67- | LC_ALL=C sort))
[ -z "$extra" ] || die "files on $dest that are not in the source: $extra"
links=$(find "$dest" -type l | head -5)
[ -z "$links" ] || die "symlinks on $dest: $links"
files=$(wc -l < "$manifest" | tr -d ' ')
printf '{"at":"%s","commit":"%s","files":%s,"manifestSha256":"%s"}\n' \
  "$(date -u +%FT%TZ)" "$commit" "$files" "$(sha256sum "$dest/.deploy-manifest" | cut -d' ' -f1)" \
  > "$dest/.deploy-info"
chmod 644 "$dest/.deploy-info"
echo "deploy_live: $files files at ${commit:0:7} deployed to $dest, manifest ok. Restart pythia-pumpfun-live to run it."
