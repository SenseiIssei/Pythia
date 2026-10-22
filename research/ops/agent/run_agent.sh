#!/usr/bin/env bash
# The research agent on the server: one run of Claude Code in its own container,
# then the checks, then push, merge and deploy. The jobs agent-research (weekly)
# and agent-care (daily) call it; nothing here needs the owner's PC.
#
#   /opt/pythia-ops/agent/run_agent.sh research|care
#
#   1. builds the image pythia-agent when its Dockerfile or the lab image changed;
#   2. brings the host's own clone (/opt/pythia-agent/trusted) to origin/main and
#      makes a fresh copy of it for the agent (/opt/pythia-agent/work);
#   3. writes a snapshot of the host for the agent (failed jobs, containers, the
#      autopilots, the live pump.fun bot) into a root-only folder, mounted read only;
#   4. runs Claude Code headless with the mode's prompt (research.md, care.md) as an
#      unprivileged user: /work its clone, /data the data folder READ ONLY, /out its
#      one writable output folder (/srv/pythia-agent-out), a fresh empty home that
#      is gone after the run, its own Docker network. The agent commits on main in
#      its clone, writes /out/<mode>.md and may list jobs to rerun in /out/rerun.txt.
#      It has no git key and cannot push;
#   5. takes the agent's commits as one mbox made inside a container without network
#      (no git runs on the host in a folder the agent could have rigged), applies it
#      in the trusted clone and checks it: main has not moved, guard.py (allow list,
#      private lines, authorship, size, the job rules), gitleaks with the base's
#      config. Only when every check passed: pushed to main, merged into
#      /opt/pythia-src, deployed (deploy_lab.sh, then deploy_ops.sh when the job
#      table changed, each checked). Otherwise the round is HELD: its patches stay
#      root-only in /root/pythia-agent-held/<mode>-<stamp>/ and nothing is pushed;
#   6. reruns the listed jobs (only after a clean deploy) and posts a notice.
#
# Every file this script writes as root lies outside the folders the agent can
# write (/opt/pythia-agent/work, /srv/pythia-agent-out); what it reads from them it
# reads without following a symlink and capped in size.
#
# Setup once (research/ops/README.md, "Research agent"): /root/pythia-agent-secrets/
# (mode 700) with agent.env (ANTHROPIC_API_KEY, PYTHIA_AGENT_GIT_EMAIL), agent-deploy-key
# (a deploy key with write access to this repository only, used here on the host and
# never mounted into a container) and private-patterns.txt (the owner's own private
# strings, which never appear in this public repository).
set -uo pipefail
umask 077

mode=${1:?usage: run_agent.sh research|care}
secrets=/root/pythia-agent-secrets
envf=$secrets/agent.env
key=$secrets/agent-deploy-key
patterns=$secrets/private-patterns.txt
# Models, turn limits and the commit identity may be set in the env file; nothing else is read from it here.
if [ -r "$envf" ]; then
  while IFS='=' read -r k v; do
    case $k in PYTHIA_AGENT_MODEL_RESEARCH|PYTHIA_AGENT_MODEL_CARE|PYTHIA_AGENT_TURNS_RESEARCH|PYTHIA_AGENT_TURNS_CARE|PYTHIA_AGENT_GIT_EMAIL|PYTHIA_AGENT_GIT_NAME) export "$k=$v" ;; esac
  done < "$envf"
fi
case $mode in
  research) model=${PYTHIA_AGENT_MODEL_RESEARCH:-claude-opus-5-5}; turns=${PYTHIA_AGENT_TURNS_RESEARCH:-400}; limit=6h ;;
  care) model=${PYTHIA_AGENT_MODEL_CARE:-claude-sonnet-5-5}; turns=${PYTHIA_AGENT_TURNS_CARE:-120}; limit=90m ;;
  *) echo "run_agent: mode must be research or care" >&2; exit 2 ;;
esac

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ops=/opt/pythia-ops
root=/opt/pythia-agent          # root only
trusted=$root/trusted           # root only, the clone that pushes
work=$root/work                 # the agent's clone (its user owns it)
run=$root/run                   # root only, this run's snapshot, settings and mbox
logs=$root/logs                 # root only, the agents' run logs
heldroot=/root/pythia-agent-held
out=/srv/pythia-agent-out       # the agent's own writable folder, /out in its container
data=/srv/pythia-data           # read only for the agent
src=/opt/pythia-src
uid=10001                       # the user "agent" of research/ops/agent/Dockerfile
net=pythia-agent                # the agent's own Docker network
remote=git@github.com:SenseiIssei/Pythia.git
# The secret scanner every agent round has to pass before anything is pushed (pinned).
gitleaks=ghcr.io/gitleaks/gitleaks:v8.28.0
max_mbox=$((20 * 1024 * 1024))
stamp=$(date -u +%Y%m%d-%H%M%S)
export GIT_SSH_COMMAND="ssh -i $key -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

log() { echo "$(date -u '+%F %T') agent $mode: $*"; }
post() { python3 "$ops/notify.py" --event studies "$1" "${2:-}" >/dev/null 2>&1 || true; }
tgit() { git -C "$trusted" -c core.hooksPath=/dev/null -c core.fsmonitor=false "$@"; }
title=$([ "$mode" = research ] && echo "Forschungsrunde" || echo "Tägliche Pflege")
fail() { log "$1"; post "$title: abgebrochen" "$1"; exit 1; }

# A regular file's first bytes, never through a symlink (a file in a folder the agent can write).
read_capped() { # path max-bytes
  python3 -I - "$1" "$2" <<'PY'
import os, stat, sys
try:
    fd = os.open(sys.argv[1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY)
except OSError:
    sys.exit(1)
try:
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        sys.exit(1)
    left, buf = int(sys.argv[2]), b""
    while left > 0:
        b = os.read(fd, left)
        if not b:
            break
        buf += b
        left -= len(b)
    sys.stdout.write(buf.decode("utf-8", "replace"))
finally:
    os.close(fd)
PY
}

# Job runs that did not end ok, oldest first, at most 30: only the runner's own end lines
# ("[<time>] pythia-jobs <job>: end, <status>, exit <n>"), never a job's output that says "end, ".
failed_runs() { # log files...
  grep -hE '^\[[^]]+\] pythia-jobs [a-z0-9-]+: end, ' "$@" 2>/dev/null | grep -vE ': end, ok(,|$)' \
    | LC_ALL=C sort | tail -30
}

# ---------------------------------------------------------------- 0. setup checks
for f in "$envf" "$key" "$patterns"; do
  [ -r "$f" ] || fail "missing $f (see research/ops/README.md, Research agent)"
done
[ "$(stat -c '%u %a' "$secrets")" = "0 700" ] || fail "$secrets must be root's, mode 700"
git_email=${PYTHIA_AGENT_GIT_EMAIL:-}
git_name=${PYTHIA_AGENT_GIT_NAME:-SenseiIssei}
[ -n "$git_email" ] || fail "set PYTHIA_AGENT_GIT_EMAIL in $envf"
command -v docker >/dev/null && command -v python3 >/dev/null || fail "docker and python3 are needed"
install -d -m 700 "$root" "$logs" "$heldroot"
rm -rf "$root/home" "$root/patches"                                  # left by older versions of this script
rm -rf "$run" && install -d -m 700 "$run" || fail "cannot make $run"
install -d -m 700 -o "$uid" -g "$uid" "$out" || fail "cannot make $out"
[ ! -L "$out" ] && [ "$(stat -c %u "$out")" = "$uid" ] || fail "$out is not the agent's folder"
rm -f "$out/$mode.md" "$out/rerun.txt"                                # unlinks a symlink, never follows it
ls -1t "$logs"/*.log 2>/dev/null | tail -n +41 | xargs -r rm -f       # keep the last 40 run logs

# 1. image
want="$(sha256sum "$here/Dockerfile" | cut -c1-16)-$(docker image inspect -f '{{.Id}}' pythia-lab | cut -c8-19)"
have="$(docker image inspect -f '{{index .Config.Labels "pythia.agent"}}' pythia-agent 2>/dev/null || true)"
if [ "$want" != "$have" ]; then
  log "building the image"
  docker build -q --label "pythia.agent=$want" -t pythia-agent -f "$here/Dockerfile" "$here" >/dev/null \
    || fail "the image pythia-agent did not build"
fi
docker network inspect "$net" >/dev/null 2>&1 || docker network create --driver bridge "$net" >/dev/null \
  || fail "cannot make the Docker network $net"

# 2. the trusted clone (host only) and a fresh copy for the agent
[ -d "$trusted/.git" ] || git clone -q "$remote" "$trusted" || fail "cannot clone the repository"
tgit fetch -q --prune origin && tgit checkout -q -B main origin/main && tgit reset -q --hard origin/main \
  && tgit clean -qfdx || fail "cannot bring the trusted clone to origin/main"
tgit config user.name "$git_name"
tgit config user.email "$git_email"
base=$(tgit rev-parse HEAD)
rm -rf "$work"
git clone -q --no-hardlinks "$trusted" "$work" || fail "cannot copy the clone for the agent"
git -C "$work" config user.name "$git_name"
git -C "$work" config user.email "$git_email"
git -C "$work" remote remove origin
chown -R "$uid:$uid" "$work"
# Commits carry the owner's name and no attribution lines (the repository's rule). Managed
# settings: the agent cannot override them, and its home is empty on every run.
cat > "$run/managed-settings.json" <<'EOF'
{"includeCoAuthoredBy": false, "attribution": {"commit": "", "pr": ""}, "permissions": {"defaultMode": "bypassPermissions"}}
EOF
grep -E '^ANTHROPIC_API_KEY=' "$envf" > "$run/claude.env" || fail "no ANTHROPIC_API_KEY in $envf"
# The scanner's config from the base, so a round cannot loosen the scan of itself.
install -d -m 755 "$run/gitleaks"
git -C "$trusted" show "$base:.gitleaks.toml" > "$run/gitleaks/gitleaks.toml" || fail "no .gitleaks.toml on main"
git -C "$trusted" show "$base:.gitleaksignore" > "$run/gitleaks/gitleaksignore" 2>/dev/null || : > "$run/gitleaks/gitleaksignore"
chmod 644 "$run/managed-settings.json" "$run/gitleaks/gitleaks.toml" "$run/gitleaks/gitleaksignore"

# 3. what the agent cannot see from its container (root-only file, mounted read only)
{
  echo "# Host snapshot $(date -u '+%F %T') UTC"
  echo; echo "## Job runs that did not end ok (oldest first, at most 30)"
  failed=$(failed_runs /var/log/pythia/*.log)
  printf '%s\n' "$failed" | cut -c1-200
  for j in $(printf '%s\n' "$failed" | sed -nE 's/^\[[^]]+\] pythia-jobs ([a-z0-9-]+): end, .*/\1/p' | sort -u); do
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
} > "$run/snapshot.md" 2>&1
chmod 644 "$run/snapshot.md"

# 4. the agent
log "running ($model)"
runlog="$logs/$mode-$stamp.log"
rc=0
extra=()
[ -d /opt/pythia-lab/proposals ] && extra+=(-v /opt/pythia-lab/proposals:/proposals:ro)
timeout --kill-after=2m "$limit" docker run --rm --name "pythia-agent-$mode" \
  --user "$uid:$uid" --cap-drop ALL --security-opt no-new-privileges --pids-limit 2048 \
  --cpus 3 --memory 7g --network "$net" \
  --env-file "$run/claude.env" -e AGENT_MODE="$mode" -e AGENT_BASE="$base" -e HOME=/home/agent \
  -e PYTHIA_DATA=/data -e PYTHIA_WRITE_ROOT=/out/data -e PYTHIA_REPORTS=/out/reports \
  -e PYTHIA_AGENT_OUT=/out/agent -e PYTHIA_CACHE=/out/cache \
  --tmpfs "/home/agent:rw,exec,nosuid,size=2g,uid=$uid,gid=$uid,mode=700" \
  -v "$work:/work" -v "$data:/data:ro" -v "$out:/out" -v /run/lock/pythia:/run/lock/pythia:ro \
  -v "$run/snapshot.md:/snapshot/snapshot.md:ro" \
  -v "$run/managed-settings.json:/etc/claude-code/managed-settings.json:ro" "${extra[@]}" \
  pythia-agent claude -p "$(cat "$here/$mode.md")" --model "$model" --max-turns "$turns" \
  --dangerously-skip-permissions --output-format text > "$runlog" 2>&1 || rc=$?
docker rm -f "pythia-agent-$mode" >/dev/null 2>&1 || true
[ "$rc" -eq 0 ] || log "the agent ended with $rc (see $runlog)"

# 5. the agent's commits as one mbox, made in a container without network, written by this
#    shell into the root-only run folder (the container only prints it)
docker run --rm --network none --user "$uid:$uid" --cap-drop ALL --security-opt no-new-privileges \
  -v "$work:/work:ro" pythia-agent \
  git -c core.fsmonitor=false -c core.hooksPath=/dev/null -c safe.directory=/work -C /work \
  format-patch --stdout --binary --no-renames --no-ext-diff "$base..main" 2>"$run/format-patch.err" \
  | head -c $((max_mbox + 1)) > "$run/round.mbox"
mbox_size=$(stat -c %s "$run/round.mbox")

hold() { # reason lines: keep the round root-only on the server, push nothing
  local dir="$heldroot/$mode-$stamp" n
  install -d -m 700 "$dir"
  printf '%s\n' "$1" > "$dir/reasons.txt"
  cp "$run/round.mbox" "$dir/round.mbox" 2>/dev/null || true
  cp "$runlog" "$dir/run.log" 2>/dev/null || true
  read_capped "$out/$mode.md" 20000 > "$dir/report.md" 2>/dev/null || true
  n=$(grep -c '^From [0-9a-f]\{40\} ' "$run/round.mbox" 2>/dev/null)
  status="zurückgehalten, ${n:-0} Commit(s) liegen nur auf dem Server ($dir)"
  why=$(printf '%s\n' "$1" | head -5 | cut -c1-160)
}

status="no change"
[ "$mbox_size" -gt 0 ] || [ ! -s "$run/format-patch.err" ] \
  || status="no change (format-patch: $(head -1 "$run/format-patch.err" | cut -c1-120))"
why=""
failed_step=""
deployed=false
if [ "$mbox_size" -gt "$max_mbox" ]; then
  hold "the agent's commits are larger than $max_mbox bytes"
elif [ "$mbox_size" -gt 0 ]; then
  sed -i '/^Co-Authored-By:/Id' "$run/round.mbox"
  if ! tgit am -q --keep-cr --no-3way "$run/round.mbox" >/dev/null 2>&1; then
    tgit am --abort >/dev/null 2>&1 || true
    hold "the agent's commits do not apply to main"
  else
    head=$(tgit rev-parse HEAD)
    n=$(tgit rev-list --count "$base..$head")
    reasons=""
    if ! tgit fetch -q origin main || [ "$(tgit rev-parse origin/main)" != "$base" ]; then
      reasons="main moved during the run (or could not be fetched)"
    fi
    if [ -z "$reasons" ]; then
      g=$(python3 -I "$here/guard.py" "$trusted" "$base" "$head" --owner-name "$git_name" \
            --owner-email "$git_email" --patterns "$patterns" 2>&1); grc=$?
      [ "$grc" -eq 0 ] || reasons=${g:-"guard.py failed (exit $grc)"}
    fi
    if [ -z "$reasons" ]; then
      if ! docker image inspect "$gitleaks" >/dev/null 2>&1 && ! docker pull -q "$gitleaks" >/dev/null 2>&1; then
        reasons="the secret scanner $gitleaks could not be pulled"
      elif ! gl=$(docker run --rm --network none -v "$trusted:/repo:ro" -v "$run/gitleaks:/cfg:ro" \
                   -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0='*' \
                   "$gitleaks" git /repo --config /cfg/gitleaks.toml --gitleaks-ignore-path /cfg/gitleaksignore \
                   --log-opts="$base..$head" --redact --no-banner 2>&1); then
        reasons="gitleaks found something in the agent's commits (or could not run)"
        printf '%s\n' "$gl" > "$run/gitleaks.out"
      fi
    fi
    if [ -n "$reasons" ]; then
      hold "$reasons"
      cp "$run/gitleaks.out" "$heldroot/$mode-$stamp/" 2>/dev/null || true
    elif ! tgit push -q origin "HEAD:refs/heads/main"; then
      hold "every check passed, but the push to main was refused"
    else
      # Pushed: from here every step reports its own failure; nothing is retried blindly.
      short=$(tgit rev-parse --short HEAD)
      if ! { git -C "$src" fetch -q && git -C "$src" merge -q --ff-only '@{u}'; }; then
        failed_step="auf main ($short, $n Commit(s)), aber /opt/pythia-src ließ sich nicht vorspulen: nichts deployt"
      else
        ok=false
        for _ in $(seq 1 30); do
          if bash "$src/research/ops/deploy_lab.sh" > "$run/deploy_lab.out" 2>&1; then ok=true; break; fi
          sleep 30
        done
        if [ "$ok" != true ]; then
          failed_step="auf main ($short), aber deploy_lab.sh schlug fehl, deploy_ops.sh lief nicht: $(tail -1 "$run/deploy_lab.out" | cut -c1-200)"
        elif tgit diff --name-only "$base" "$head" | grep -qx research/ops/jobs.yaml \
             && ! bash "$src/research/ops/deploy_ops.sh" > "$run/deploy_ops.out" 2>&1; then
          failed_step="auf main ($short), Lab deployt, aber deploy_ops.sh schlug fehl: $(tail -1 "$run/deploy_ops.out" | cut -c1-200)"
        else
          deployed=true
          status="gemergt und deployt: $short ($n Commit(s))"
        fi
      fi
    fi
    tgit reset -q --hard origin/main
  fi
fi

# 6. reruns the agent asked for, plain lab jobs only (no env file, network or volumes), at most
#    five, only after a clean deploy
if [ "$deployed" = true ]; then
  read_capped "$out/rerun.txt" 2000 2>/dev/null | head -5 | while read -r job; do
    case $job in *[!a-z0-9-]*|"") continue ;; esac
    plain=$(python3 -I -c "import sys; sys.path.insert(0, '$ops'); import jobs; t = jobs.load_table('$ops/jobs.yaml'); print(jobs.plain_lab_job(t.jobs[sys.argv[1]]))" "$job" 2>/dev/null || echo False)
    if [ "$plain" = True ]; then python3 -I "$ops/jobs.py" --table "$ops/jobs.yaml" run "$job" --force >/dev/null 2>&1 || true; fi
  done
fi

if [ -n "$failed_step" ]; then
  log "$failed_step"
  post "$title: Deploy fehlgeschlagen" "$failed_step"
elif [ -n "$why" ]; then
  # A held round: the reasons, never the patches or the agent's text.
  log "$status: $why"
  post "$title: $status" "Gründe: $why"
else
  log "$status"
  report=$(read_capped "$out/$mode.md" 3000 2>/dev/null || true)
  post "$title: $status" "${report:-Kein Bericht geschrieben (Exit $rc).}"
fi
# A held round is the guard working (exit 0); a pushed round that did not deploy is a failure.
[ -z "$failed_step" ]
