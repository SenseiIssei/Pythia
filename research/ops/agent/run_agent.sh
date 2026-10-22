#!/usr/bin/env bash
# The research agent on the server: one run of Claude Code in its own container,
# then the guard, then merge and deploy. The jobs agent-research (weekly) and
# agent-care (daily) call it; nothing here needs the owner's PC.
#
#   /opt/pythia-ops/agent/run_agent.sh research|care
#
#   1. builds the image pythia-agent when its Dockerfile or the lab image changed;
#   2. brings the host's own clone (/opt/pythia-agent/trusted) to origin/main and
#      makes a fresh copy of it for the agent (/opt/pythia-agent/work);
#   3. writes a snapshot of the host for the agent (failed jobs, containers, the
#      autopilots, the live pump.fun bot), which it cannot see from its container;
#   4. runs Claude Code headless with the mode's prompt (research.md, care.md). The
#      agent commits on main in its copy, writes reports/agent/<mode>.md and may list
#      jobs to rerun in reports/agent/rerun.txt. It has no key and cannot push;
#   5. takes the agent's commits as patch files (made inside the container, so no git
#      runs on the host in a folder the agent could have rigged), applies them in the
#      trusted clone and checks them with guard.py. Clean: pushed to main, pulled into
#      /opt/pythia-src and deployed (deploy_lab.sh, deploy_ops.sh when the job table
#      changed). Not clean: pushed to a branch agent/<mode>-<date> for the owner;
#   6. reruns the listed jobs and posts the report to Telegram.
#
# Setup once (research/ops/README.md, "Research agent"): /etc/pythia/agent.env with
# ANTHROPIC_API_KEY (mode 600) and /etc/pythia/agent-deploy-key, a deploy key with
# write access to this repository only, used here on the host and never mounted
# into the agent's container.
set -euo pipefail

mode=${1:?usage: run_agent.sh research|care}
envf=/etc/pythia/agent.env
# Models and turn limits may be set in the env file; nothing else is read from it here.
if [ -r "$envf" ]; then
  while IFS='=' read -r k v; do
    case $k in PYTHIA_AGENT_MODEL_RESEARCH|PYTHIA_AGENT_MODEL_CARE|PYTHIA_AGENT_TURNS_RESEARCH|PYTHIA_AGENT_TURNS_CARE|PYTHIA_AGENT_GIT_EMAIL) export "$k=$v" ;; esac
  done < "$envf"
fi
# The commit identity's address lives in the env file only, never in this public repository.
git_email=${PYTHIA_AGENT_GIT_EMAIL:?set PYTHIA_AGENT_GIT_EMAIL in /etc/pythia/agent.env}
case $mode in
  research) model=${PYTHIA_AGENT_MODEL_RESEARCH:-claude-opus-5-5}; turns=${PYTHIA_AGENT_TURNS_RESEARCH:-400}; limit=6h ;;
  care) model=${PYTHIA_AGENT_MODEL_CARE:-claude-sonnet-5-5}; turns=${PYTHIA_AGENT_TURNS_CARE:-120}; limit=90m ;;
  *) echo "run_agent: mode must be research or care" >&2; exit 2 ;;
esac

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ops=/opt/pythia-ops
root=/opt/pythia-agent
trusted=$root/trusted
work=$root/work
home=$root/home
data=/srv/pythia-data
out=$data/reports/agent
patches=$root/patches
src=/opt/pythia-src
key=/etc/pythia/agent-deploy-key
remote=git@github.com:SenseiIssei/Pythia.git
# The secret scanner every agent round has to pass before anything is pushed (pinned).
gitleaks=ghcr.io/gitleaks/gitleaks:v8.28.0
stamp=$(date -u +%Y%m%d-%H%M)
export GIT_SSH_COMMAND="ssh -i $key -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

log() { echo "$(date -u '+%F %T') agent $mode: $*"; }
post() { python3 "$ops/notify.py" --event studies "$1" "${2:-}" >/dev/null 2>&1 || true; }
tgit() { git -C "$trusted" "$@"; }

for f in "$envf" "$key"; do
  [ -r "$f" ] || { log "missing $f (see research/ops/README.md, Research agent)"; exit 1; }
done
install -d -m 700 "$root" "$home" "$home/.claude"
install -d -m 755 "$out"

# 1. image
want="$(sha256sum "$here/Dockerfile" | cut -c1-16)-$(docker image inspect -f '{{.Id}}' pythia-lab | cut -c8-19)"
have="$(docker image inspect -f '{{index .Config.Labels "pythia.agent"}}' pythia-agent 2>/dev/null || true)"
if [ "$want" != "$have" ]; then
  log "building the image"
  docker build -q --label "pythia.agent=$want" -t pythia-agent -f "$here/Dockerfile" "$here" >/dev/null
fi

# 2. the trusted clone (host only) and a fresh copy for the agent
[ -d "$trusted/.git" ] || git clone -q "$remote" "$trusted"
tgit fetch -q --prune origin
tgit checkout -q -B main origin/main
tgit reset -q --hard origin/main
tgit clean -qfdx
tgit config user.name SenseiIssei
tgit config user.email "$git_email"
base=$(tgit rev-parse HEAD)
rm -rf "$work" "$patches"
git clone -q --no-hardlinks "$trusted" "$work"
git -C "$work" config user.name SenseiIssei
git -C "$work" config user.email "$git_email"
# Commits carry the owner's name and no attribution lines (the repository's rule).
cat > "$home/.claude/settings.json" <<'EOF'
{"includeCoAuthoredBy": false, "attribution": {"commit": "", "pr": ""}, "permissions": {"defaultMode": "bypassPermissions"}}
EOF
rm -f "$out/$mode.md" "$out/rerun.txt"

# 3. what the agent cannot see from its container
{
  echo "# Host snapshot $(date -u '+%F %T') UTC"
  echo; echo "## Job runs that did not end ok (newest last)"
  grep -h "end, " /var/log/pythia/*.log 2>/dev/null | grep -v "end, ok" | tail -30 || true
  for j in $(grep -h "end, " /var/log/pythia/*.log 2>/dev/null | grep -v "end, ok" | tail -30 \
             | sed -n 's/.*pythia-jobs \([a-z0-9-]*\): end.*/\1/p' | sort -u); do
    echo; echo "### tail of $j.log"; tail -40 "/var/log/pythia/$j.log" | cut -c1-300
  done
  echo; echo "## Containers"; docker ps --format '{{.Names}}  {{.Status}}'
  echo; echo "## Autopilots (id, state, equity, paused because)"
  for p in 8788 8789; do
    curl -s -m 10 "http://127.0.0.1:$p/api/state" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except ValueError:
    sys.exit()
for a in d.get("autopilots", []):
    if a.get("state") != "stopped":
        c = a.get("config", {})
        print(c.get("id"), a.get("state"), round(a.get("equity") or 0, 2), a.get("pausedReason") or "")
' || true
  done
  echo; echo "## pump.fun live bot (log tail)"; docker logs --tail 30 pythia-pumpfun-live 2>&1 | cut -c1-250 || true
  echo; echo "## Cockpit build"; echo "built $(cut -c1-7 "$ops/cockpit/.built" 2>/dev/null), source $(git -C "$src" rev-parse --short HEAD)"
  echo; echo "## Machine"; df -h /srv | tail -1; free -g | sed -n 2p; uptime
} > "$out/snapshot.md" 2>&1

# 4. the agent
log "running ($model)"
rc=0
extra=()
[ -d /opt/pythia-lab/proposals ] && extra+=(-v /opt/pythia-lab/proposals:/proposals:ro)
timeout "$limit" docker run --rm --name "pythia-agent-$mode" --cpus 3 --memory 7g \
  --env-file "$envf" -e AGENT_MODE="$mode" -e AGENT_BASE="$base" -e HOME=/home/agent \
  -v "$work:/work" -v "$data:/data" -v "$home:/home/agent" -v /run/lock/pythia:/run/lock/pythia "${extra[@]}" \
  pythia-agent claude -p "$(cat "$here/$mode.md")" --model "$model" --max-turns "$turns" \
  --dangerously-skip-permissions --output-format text > "$out/$mode-run.log" 2>&1 || rc=$?
docker rm -f "pythia-agent-$mode" >/dev/null 2>&1 || true
[ "$rc" -eq 0 ] || log "the agent ended with $rc (see $out/$mode-run.log)"

# 5. patches, guard, merge, deploy
install -d -m 700 "$patches"
docker run --rm -v "$work:/work:ro" -v "$patches:/out" pythia-agent \
  git -c safe.directory=/work -C /work format-patch -q -o /out "$base..main" >/dev/null 2>&1 || true
status="no change"
set -- "$patches"/*.patch
if [ -e "$1" ]; then
  sed -i '/^Co-Authored-By:/Id' "$patches"/*.patch
  if ! tgit am -q --keep-cr "$patches"/*.patch; then
    tgit am --abort >/dev/null 2>&1 || true
    status="held: the agent's $# commit(s) do not apply to main"
  else
    head=$(tgit rev-parse HEAD)
    tgit fetch -q origin main
    if [ "$(tgit rev-parse origin/main)" != "$base" ]; then
      tgit push -q origin "HEAD:refs/heads/agent/$mode-$stamp"
      status="held: main moved during the run, branch agent/$mode-$stamp is for the owner"
    elif why=$(python3 "$here/guard.py" "$trusted" "$base" "$head") \
      && why=$(docker run --rm -v "$trusted:/repo:ro" "$gitleaks" git /repo --config /repo/.gitleaks.toml \
               --gitleaks-ignore-path /repo/.gitleaksignore --log-opts="$base..$head" --redact --no-banner 2>&1 \
               || { echo "gitleaks found something in the agent's commits"; false; }); then
      tgit push -q origin "HEAD:refs/heads/main"
      git -C "$src" fetch -q && git -C "$src" merge -q --ff-only '@{u}'
      for _ in $(seq 1 30); do bash "$src/research/ops/deploy_lab.sh" >/dev/null 2>&1 && break; sleep 30; done
      if tgit diff --name-only "$base" "$head" | grep -qx research/ops/jobs.yaml; then
        bash "$src/research/ops/deploy_ops.sh" >/dev/null
      fi
      status="merged and deployed $(tgit rev-parse --short HEAD) ($# commit(s))"
      # 6. reruns the agent asked for, lab jobs only, at most five
      if [ -s "$out/rerun.txt" ]; then
        head -5 "$out/rerun.txt" | while read -r job; do
          case $job in *[!a-z0-9-]*|"") continue ;; esac
          kind=$(python3 -c "import sys; sys.path.insert(0, '$ops'); import jobs; print(jobs.load_table('$ops/jobs.yaml').jobs['$job']['kind'])" 2>/dev/null || echo none)
          if [ "$kind" = lab ]; then python3 "$ops/jobs.py" --table "$ops/jobs.yaml" run "$job" --force >/dev/null 2>&1 || true; fi
        done
      fi
    else
      tgit push -q origin "HEAD:refs/heads/agent/$mode-$stamp"
      status="held for the owner, branch agent/$mode-$stamp: $(echo "$why" | head -3 | tr '\n' ';')"
    fi
    tgit reset -q --hard origin/main
  fi
fi
log "$status"

title=$([ "$mode" = research ] && echo "Forschungsrunde" || echo "Tägliche Pflege")
report=$(head -c 3000 "$out/$mode.md" 2>/dev/null || echo "Kein Bericht geschrieben (Exit $rc).")
post "$title: $status" "$report"
