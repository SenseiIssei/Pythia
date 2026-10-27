#!/usr/bin/env bash
# The task lanes on the server: one paid Claude Code run per task file, then the checks, then
# push, merge and deploy of what passed. The rules are in lanes.py (its docstring); this shell
# only moves files, runs containers and git, as run_agent.sh does for the research agent.
#
#   /opt/pythia-ops/lanes/run_lane.sh queue FILE    check a task file and put it in the queue
#   /opt/pythia-ops/lanes/run_lane.sh run           run the next queued task (one per call)
#   /opt/pythia-ops/lanes/run_lane.sh report        rewrite reports/research/latest.json
#
#   queue: lanes.py queue-check against main; a refused file costs nothing and says why;
#   run:   1. the next task in /root/pythia-lanes/queue (sorted, a HOLD file skips it), checked
#             again against main (refused: recorded as stopped, nothing spent);
#          2. the budget gate: starts only if what is left exceeds the reserve plus the task's
#             max_usd, which also caps the run (--max-budget-usd);
#          3. the trusted clone at origin/main, a fresh copy for the agent; a retry gets the held
#             run's commits applied first (in a container without network);
#          4. Claude Code in the agent's image, the prompt from lanes.py (lane.md, the allowed list,
#             docs, tests, the never list, the brief), the check at /lane (lanes.py, guard.py and
#             jobs.py from main, read only), AGENT_BASE the base;
#          5. the commits as one mbox (a container without network), applied in the trusted clone:
#             main moved? lanes.py verdict; files off the list dropped (lanes.py prune) and the rest
#             judged again; the task's tests in a container from the result; gitleaks;
#          6. passed: pushed, merged into /opt/pythia-src, deploy_lab.sh, deploy_ops.sh when the
#             job table changed; held: the round root-only in /root/pythia-lanes/done/<id>/ and
#             one retry queued on the next cheaper model with the reasons (lanes.py retry);
#          7. the record reports/lanes/<id>.json, latest.json, a notice with what was dropped.
#
# Every file this script writes as root lies outside the folders the agent can write; what it
# reads from them (the report) it reads without following a symlink and capped in size.
set -uo pipefail
umask 077

cmd=${1:?usage: run_lane.sh queue FILE | run | report}
secrets=/root/pythia-agent-secrets
envf=$secrets/agent.env
key=$secrets/agent-deploy-key
patterns=$secrets/private-patterns.txt
lanes=/root/pythia-lanes          # root only: queue/, done/, budget.json, spent.jsonl
queue=$lanes/queue
donedir=$lanes/done
budget=$lanes/budget.json         # {"balance_usd": 40, "reserve_usd": 10, "since": "2026-10-28T00:00:00"}
spent=$lanes/spent.jsonl          # one line a run: {"at": ..., "task": ..., "usd": ...}
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ops=/opt/pythia-ops
root=/opt/pythia-agent
trusted=$root/trusted
work=$root/lane-work              # the agent's clone (its user owns it)
run=$root/lane-run                # root only, this run's prompt, mbox, verdicts
logs=$root/logs
out=/srv/pythia-agent-out
data=/srv/pythia-data
records=$data/reports/lanes
latest=$data/reports/research/latest.json
src=/opt/pythia-src
uid=10001
net=pythia-agent
remote=git@github.com:SenseiIssei/Pythia.git
gitleaks=ghcr.io/gitleaks/gitleaks:v8.28.0
max_mbox=$((20 * 1024 * 1024))
stamp=$(date -u +%Y%m%d-%H%M%S)
turns=400
limit=6h
test_net=$net                     # npm ci needs the registry; set PYTHIA_LANE_TEST_NET=none to cut it
if [ -r "$envf" ]; then
  while IFS='=' read -r k v; do
    case $k in PYTHIA_AGENT_GIT_EMAIL|PYTHIA_AGENT_GIT_NAME) export "$k=$v" ;;
      PYTHIA_LANE_TURNS) turns=$v ;; PYTHIA_LANE_LIMIT) limit=$v ;; PYTHIA_LANE_TEST_NET) test_net=$v ;; esac
  done < "$envf"
fi
export GIT_SSH_COMMAND="ssh -i $key -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
L() { python3 -I "$here/lanes.py" "$@"; }
log() { echo "$(date -u '+%F %T') lane: $*"; }
post() { python3 "$ops/notify.py" --event studies "$1" "${2:-}" >/dev/null 2>&1 || true; }
tgit() { git -C "$trusted" -c core.hooksPath=/dev/null -c core.fsmonitor=false "$@"; }
report() { install -d -m 755 "$records" "$(dirname "$latest")"
  L report --records "$records" --queue "$queue" --state "$budget" --spent "$spent" --out "$latest" --running "${1:-}" \
    && chmod 644 "$latest" || log "latest.json not written"; }

read_capped() { # path max-bytes: a regular file's first bytes, never through a symlink
  python3 -I - "$1" "$2" <<'PY'
import os, stat, sys
try:
    fd = os.open(sys.argv[1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY)
except OSError:
    sys.exit(1)
try:
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        sys.exit(1)
    sys.stdout.write(os.read(fd, int(sys.argv[2])).decode("utf-8", "replace"))
finally:
    os.close(fd)
PY
}

trusted_main() { # the host's clone at origin/main; prints the base
  [ -d "$trusted/.git" ] || git clone -q "$remote" "$trusted" || return 1
  tgit fetch -q --prune origin && tgit checkout -q -B main origin/main && tgit reset -q --hard origin/main \
    && tgit clean -qfdx && tgit rev-parse HEAD
}

install -d -m 700 "$lanes" "$queue" "$donedir" "$root" "$logs"
case $cmd in
  report) report; exit 0 ;;
  queue)
    file=${2:?usage: run_lane.sh queue FILE}
    trusted_main >/dev/null || { echo "cannot bring the trusted clone to origin/main" >&2; exit 1; }
    L queue-check "$file" --repo "$trusted" || exit 1
    id=$(L field --task "$file" id)
    [ ! -e "$queue/$id" ] || { echo "already queued: $id" >&2; exit 1; }
    install -d -m 700 "$queue/$id" && install -m 600 "$file" "$queue/$id/task.md" && echo "queued: $id"
    report; exit 0 ;;
  run) ;;
  *) echo "usage: run_lane.sh queue FILE | run | report" >&2; exit 2 ;;
esac

# ---------------------------------------------------------------- run: 0. setup
fail() { log "$1"; post "Forschungsaufgabe: abgebrochen" "$1"; report; exit 1; }
for f in "$envf" "$key" "$patterns"; do [ -r "$f" ] || fail "missing $f (see research/ops/README.md, Task lanes)"; done
git_email=${PYTHIA_AGENT_GIT_EMAIL:-}
git_name=${PYTHIA_AGENT_GIT_NAME:-SenseiIssei}
[ -n "$git_email" ] || fail "set PYTHIA_AGENT_GIT_EMAIL in $envf"
exec 9>"$lanes/.lock"
flock -n 9 || { log "another lane runs"; exit 0; }

# 1. the next task, checked again against main
qd=""
for d in $(ls -1 "$queue" 2>/dev/null | LC_ALL=C sort); do
  [ -f "$queue/$d/task.md" ] && [ ! -e "$queue/$d/HOLD" ] && { qd=$queue/$d; break; }
done
[ -n "$qd" ] || { log "nothing queued"; report; exit 0; }
task=$qd/task.md
id=$(L field --task "$task" id); title=$(L field --task "$task" title)
model=$(L field --task "$task" model); max_usd=$(L field --task "$task" max_usd)
[ -n "$id" ] || id=$(basename "$qd")
keep=$donedir/$id-$stamp
install -d -m 700 "$keep"
cp "$task" "$keep/task.md"
base=$(trusted_main) || fail "cannot bring the trusted clone to origin/main"
if ! q=$(L queue-check "$task" --repo "$trusted" 2>&1); then
  printf '%s\n' "$q" > "$keep/reasons.txt"
  L record --task "$task" --status stopped --out "$records" --reason "Nicht gestartet (Aufgabe unvollständig): $(printf '%s' "$q" | head -3 | tr '\n' ' ')" --usd 0
  rm -rf "$qd"; post "Forschungsaufgabe nicht gestartet: $title" "$(printf '%s' "$q" | head -5)"; report; exit 0
fi

# 2. the budget gate
if ! g=$(L budget --state "$budget" --spent "$spent" --max-usd "$max_usd"); then
  log "$id waits: $g"; report; exit 0
fi

# 3. the agent's clone (a retry starts from the held run's commits)
rm -rf "$run" "$work" && install -d -m 700 "$run" || fail "cannot make $run"
install -d -m 700 -o "$uid" -g "$uid" "$out" || fail "cannot make $out"
[ ! -L "$out" ] && [ "$(stat -c %u "$out")" = "$uid" ] || fail "$out is not the agent's folder"
rm -f "$out/report.md"
tgit config user.name "$git_name"; tgit config user.email "$git_email"
git clone -q --no-hardlinks "$trusted" "$work" || fail "cannot copy the clone for the agent"
git -C "$work" config user.name "$git_name"; git -C "$work" config user.email "$git_email"
git -C "$work" remote remove origin
chown -R "$uid:$uid" "$work"
if [ -s "$qd/retry.mbox" ]; then
  install -m 644 "$qd/retry.mbox" "$run/retry.mbox"
  docker run --rm --network none --user "$uid:$uid" --cap-drop ALL --security-opt no-new-privileges \
    -v "$work:/work" -v "$run/retry.mbox:/retry.mbox:ro" pythia-agent \
    git -c core.hooksPath=/dev/null -c safe.directory=/work -C /work am -q --keep-cr --no-3way /retry.mbox >/dev/null 2>&1 \
    || log "$id: the held commits do not apply to main any more; the retry starts from main"
fi
install -d -m 755 "$run/lane"
tgit archive "$base" research/ops/lanes research/ops/agent/guard.py research/lab/lab/ops/jobs.py | tar -x -C "$run/lane" \
  || fail "cannot export the lane's check from main"
install -m 644 "$task" "$run/lane/task.md"
chmod -R a+rX "$run/lane"
L prompt --task "$task" --rules "$run/lane/research/ops/lanes/lane.md" > "$run/prompt.md" || fail "no prompt for $id"
cat > "$run/managed-settings.json" <<'EOF'
{"includeCoAuthoredBy": false, "attribution": {"commit": "", "pr": ""}, "permissions": {"defaultMode": "bypassPermissions"}}
EOF
grep -E '^ANTHROPIC_API_KEY=' "$envf" > "$run/claude.env" || fail "no ANTHROPIC_API_KEY in $envf"
install -d -m 755 "$run/gitleaks"
tgit show "$base:.gitleaks.toml" > "$run/gitleaks/gitleaks.toml" || fail "no .gitleaks.toml on main"
tgit show "$base:.gitleaksignore" > "$run/gitleaks/gitleaksignore" 2>/dev/null || : > "$run/gitleaks/gitleaksignore"
chmod 644 "$run/managed-settings.json" "$run/gitleaks/"*

# 4. the agent
log "$id: running ($model, at most $max_usd USD)"
report "$title"
runlog="$logs/lane-$id-$stamp.log"
rc=0
timeout --kill-after=2m "$limit" docker run --rm --name "pythia-lane" \
  --user "$uid:$uid" --cap-drop ALL --security-opt no-new-privileges --pids-limit 2048 \
  --cpus 3 --memory 7g --network "$net" \
  --env-file "$run/claude.env" -e AGENT_BASE="$base" -e LANE_TASK=/lane/task.md -e HOME=/home/agent \
  -e PYTHIA_DATA=/data -e PYTHIA_WRITE_ROOT=/out/data -e PYTHIA_REPORTS=/out/reports \
  -e PYTHIA_AGENT_OUT=/out/agent -e PYTHIA_CACHE=/out/cache \
  --tmpfs "/home/agent:rw,exec,nosuid,size=2g,uid=$uid,gid=$uid,mode=700" \
  -v "$work:/work" -v "$data:/data:ro" -v "$out:/out" -v /run/lock/pythia:/run/lock/pythia:ro \
  -v "$run/lane:/lane:ro" -v "$run/managed-settings.json:/etc/claude-code/managed-settings.json:ro" \
  pythia-agent claude -p "$(cat "$run/prompt.md")" --model "$model" --max-turns "$turns" \
  --max-budget-usd "$max_usd" --dangerously-skip-permissions --output-format json > "$runlog" 2>&1 || rc=$?
docker rm -f pythia-lane >/dev/null 2>&1 || true
usd=$(L cost --file "$runlog" --max-usd "$max_usd")
printf '{"at": "%s", "task": "%s", "usd": %s}\n' "$(date -u +%FT%T)" "$id" "$usd" >> "$spent"
log "$id: the agent ended with $rc, $usd USD"
read_capped "$out/report.md" 20000 > "$keep/report.md" 2>/dev/null || : > "$keep/report.md"

# 5. the commits, the verdict, the drop, the tests, the scan
docker run --rm --network none --user "$uid:$uid" --cap-drop ALL --security-opt no-new-privileges \
  -v "$work:/work:ro" pythia-agent \
  git -c core.fsmonitor=false -c core.hooksPath=/dev/null -c safe.directory=/work -C /work \
  format-patch --stdout --binary --no-renames --no-ext-diff "$base..main" 2>/dev/null \
  | head -c $((max_mbox + 1)) > "$run/round.mbox"
cp "$run/round.mbox" "$keep/round.mbox"
reasons=""; dropped=""
head=$base
if [ "$(stat -c %s "$run/round.mbox")" -gt "$max_mbox" ]; then
  reasons="the commits are larger than $max_mbox bytes"
elif [ ! -s "$run/round.mbox" ]; then
  reasons="nothing committed (exit $rc)"
else
  sed -i '/^Co-Authored-By:/Id' "$run/round.mbox"
  if ! tgit am -q --keep-cr --no-3way "$run/round.mbox" >/dev/null 2>&1; then
    tgit am --abort >/dev/null 2>&1 || true
    reasons="the commits do not apply to main"
  else
    head=$(tgit rev-parse HEAD)
    if ! tgit fetch -q origin main || [ "$(tgit rev-parse origin/main)" != "$base" ]; then
      reasons="main moved during the run (or could not be fetched)"
    fi
  fi
fi
verdict() { L verdict --task "$task" --repo "$trusted" --base "$base" --head "$1" --owner-name "$git_name" \
              --owner-email "$git_email" --patterns "$patterns" > "$run/verdict.json"; }
fatal() { python3 -I -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))["fatal"]))' "$run/verdict.json"; }
if [ -z "$reasons" ]; then
  verdict "$head"
  cp "$run/verdict.json" "$keep/verdict.json"
  reasons=$(fatal)
  dropped=$(python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1]))["dropped"]; print(", ".join(d))' "$run/verdict.json")
  if [ -z "$reasons" ] && [ -n "$dropped" ]; then
    python3 -I -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))["kept"]))' "$run/verdict.json" > "$run/keep.txt"
    if ! head=$(L prune --repo "$trusted" --base "$base" --head "$head" --keep "$run/keep.txt"); then
      reasons="the commits could not be limited to the allowed files"
    else
      verdict "$head"
      reasons=$(fatal)
      python3 -I -c 'import json,sys; sys.exit(1 if json.load(open(sys.argv[1]))["dropped"] else 0)' "$run/verdict.json" \
        || reasons="${reasons:+$reasons
}files off the list are still there after the drop"
    fi
  fi
fi
if [ -z "$reasons" ]; then
  rm -rf "$run/tree" && install -d -m 700 -o "$uid" -g "$uid" "$run/tree"
  tgit archive "$head" | tar -x -C "$run/tree" && chown -R "$uid:$uid" "$run/tree"
  python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import lanes; print("\n".join(lanes.parse_task(open(sys.argv[2]).read()).tests))' \
    "$here" "$task" > "$run/tests.txt"
  while IFS= read -r t; do
    [ -n "$t" ] || continue
    if ! timeout 45m docker run --rm --network "$test_net" --user "$uid:$uid" --cap-drop ALL --security-opt no-new-privileges \
         --cpus 3 --memory 7g --tmpfs "/home/agent:rw,exec,nosuid,size=2g,uid=$uid,gid=$uid,mode=700" -e HOME=/home/agent \
         -e PYTHIA_DATA=/data -v "$data:/data:ro" -v "$run/tree:/work" -w /work pythia-agent bash -c "$t" \
         > "$run/test.out" 2>&1; then
      reasons="${reasons:+$reasons
}tests red: $t: $(tail -3 "$run/test.out" | tr '\n' ' ' | cut -c1-300)"
    fi
  done < "$run/tests.txt"
fi
if [ -z "$reasons" ]; then
  if ! docker image inspect "$gitleaks" >/dev/null 2>&1 && ! docker pull -q "$gitleaks" >/dev/null 2>&1; then
    reasons="the secret scanner $gitleaks could not be pulled"
  elif ! docker run --rm --network none -v "$trusted:/repo:ro" -v "$run/gitleaks:/cfg:ro" \
         -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0='*' \
         "$gitleaks" git /repo --config /cfg/gitleaks.toml --gitleaks-ignore-path /cfg/gitleaksignore \
         --log-opts="$base..$head" --redact --no-banner > "$keep/gitleaks.out" 2>&1; then
    reasons="gitleaks found something in the commits (or could not run)"
  fi
fi

# 6. land it, or hold it and queue the one retry
tgit diff --name-only "$base" "$head" > "$run/files.txt" 2>/dev/null || : > "$run/files.txt"
if [ -z "$reasons" ] && ! tgit push -q origin "$head:refs/heads/main"; then
  reasons="every check passed, but the push to main was refused"
fi
note=${dropped:+ Verworfen (nicht auf der Liste): $dropped.}
if [ -n "$reasons" ]; then
  tgit reset -q --hard origin/main
  printf '%s\n' "$reasons" > "$keep/reasons.txt"
  retry=""
  if L retry --task "$task" --reasons "$keep/reasons.txt" --out "$run/retry.md" >/dev/null; then
    rid=$(L field --task "$run/retry.md" id)
    install -d -m 700 "$queue/$rid" && install -m 600 "$run/retry.md" "$queue/$rid/task.md" \
      && install -m 600 "$keep/round.mbox" "$queue/$rid/retry.mbox" && retry=" Zweiter Versuch eingeplant: $(L field --task "$run/retry.md" model)."
  fi
  L record --task "$task" --status stopped --out "$records" --base "$base" --usd "$usd" --report "$keep/report.md" \
    --reason "Zurückgehalten: $(printf '%s' "$reasons" | head -5 | tr '\n' ' ' | cut -c1-600)$retry" --files "$run/files.txt"
  rm -rf "$qd"
  log "$id held: $(printf '%s' "$reasons" | head -3 | tr '\n' ' ')"
  post "Forschungsaufgabe zurückgehalten: $title" "Gründe: $(printf '%s' "$reasons" | head -5 | cut -c1-160)$retry"
  report; exit 0
fi
short=$(tgit rev-parse --short "$head")
tgit reset -q --hard "$head"
L record --task "$task" --status done --out "$records" --base "$base" --commit "$short" --usd "$usd" \
  --report "$keep/report.md" --verdict "$keep/verdict.json" --files "$run/files.txt" --reason "$(printf '%s' "$note" | sed 's/^ //')"
rm -rf "$qd"
failed_step=""
if ! { git -C "$src" fetch -q && git -C "$src" merge -q --ff-only '@{u}'; }; then
  failed_step="auf main ($short), aber /opt/pythia-src ließ sich nicht vorspulen: nichts deployt"
else
  ok=false
  for _ in $(seq 1 30); do
    if bash "$src/research/ops/deploy_lab.sh" > "$run/deploy_lab.out" 2>&1; then ok=true; break; fi
    sleep 30
  done
  if [ "$ok" != true ]; then
    failed_step="auf main ($short), aber deploy_lab.sh schlug fehl: $(tail -1 "$run/deploy_lab.out" | cut -c1-200)"
  elif grep -qx research/ops/jobs.yaml "$run/files.txt" && ! bash "$src/research/ops/deploy_ops.sh" > "$run/deploy_ops.out" 2>&1; then
    failed_step="auf main ($short), Lab deployt, aber deploy_ops.sh schlug fehl: $(tail -1 "$run/deploy_ops.out" | cut -c1-200)"
  fi
fi
tgit reset -q --hard origin/main 2>/dev/null || true
if [ -n "$failed_step" ]; then
  log "$id: $failed_step"; post "Forschungsaufgabe: Deploy fehlgeschlagen ($title)" "$failed_step$note"
else
  log "$id: landed $short ($usd USD)$note"
  post "Forschungsaufgabe fertig: $title" "Commit $short, $usd USD.$note $(read_capped "$keep/report.md" 2500 2>/dev/null)"
fi
report
[ -z "$failed_step" ]
