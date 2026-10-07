#!/usr/bin/env bash
# Hourly check of everything Pythia runs on the VPS, written to
# /srv/pythia-data/_health/system.json for the Lab page. Read-only: it looks,
# it never restarts anything.
#
#   install: copy to /opt/pythia-ops/ and add to cron (see research/ops/README.md)
set -uo pipefail

main() {
  local data=/srv/pythia-data
  local out="$data/_health/system.json"
  local now today
  now=$(date -u +%s)
  today=$(date -u +%F)
  local checks=()

  add() { # name ok detail
    local d=${3//\"/\'}
    checks+=("{\"name\":\"$1\",\"ok\":$2,\"detail\":\"$d\"}")
  }

  for c in pythia-recorder pythia-server; do
    if [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" = "true" ]; then
      add "$c" true "running since $(docker inspect -f '{{.State.StartedAt}}' "$c" | cut -c1-16)"
    else
      add "$c" false "not running"
    fi
  done

  # Recorder: every stream fresh, status written in the last five minutes
  local st="$data/_health/status.json"
  if [ -f "$st" ]; then
    local age=$(( now - $(stat -c %Y "$st") ))
    local ok
    ok=$(python3 -c "import json;s=json.load(open('$st'));print('true' if s['ok'] else 'false')" 2>/dev/null || echo false)
    if [ "$age" -lt 300 ] && [ "$ok" = "true" ]; then
      add "recorder streams" true "all streams fresh"
    else
      add "recorder streams" false "status $ok, written ${age}s ago"
    fi
  else
    add "recorder streams" false "no status file"
  fi

  # Nightly backfill finished within the last 30 hours
  local last_done
  last_done=$(grep "done:" /var/log/pythia-backfill.log 2>/dev/null | tail -1 | cut -c1-19)
  if [ -n "$last_done" ] && [ $(( now - $(date -u -d "$last_done" +%s) )) -lt 108000 ]; then
    add "nightly backfill" true "last finished $last_done UTC"
  else
    add "nightly backfill" false "last finished ${last_done:-never}"
  fi

  # Paper books: a row for today once their run time has passed (04:00, 04:15, 04:45 and 05:30 UTC + margin)
  local hour
  hour=$(date -u +%H)
  for b in tsmom tsmom_regime tsmom_top20 breakout_top10 m4_ls picks_ls picks_ls_v2; do
    local j="$data/paper/$b/journal.csv"
    local last
    last=$(tail -1 "$j" 2>/dev/null | cut -d, -f1)
    local due=4
    case $b in picks_ls*|m4_ls) due=6 ;; tsmom_top20|breakout_top10) due=5 ;; esac
    if [ "$last" = "$today" ] || { [ "$hour" -lt "$due" ] && [ "$last" = "$(date -u -d yesterday +%F)" ]; }; then
      add "paper $b" true "last row $last"
    else
      add "paper $b" false "last row ${last:-none}, expected $today"
    fi
  done

  # Shadow model service answers and is live
  local ml
  ml=$(curl -s -m 5 127.0.0.1:8787/api/ml/status | python3 -c "import json,sys;s=json.load(sys.stdin);print(s['state'], s['shadow']['scored'])" 2>/dev/null)
  case "$ml" in
    live*) add "volatility model" true "live, ${ml#live } coin-hours scored" ;;
    *) add "volatility model" false "state: ${ml:-no answer}" ;;
  esac

  # Engine market data: every crypto market's quotes and candles fresh, which
  # source each kind is on, and failovers in the last 24 h (dataHealth in /api/state)
  local md
  md=$(curl -s -m 10 127.0.0.1:8787/api/state | python3 -c "
import json, sys
h = json.load(sys.stdin).get('dataHealth') or {}
if not h.get('running'):
    print('false|feeds not running'); sys.exit()
parts = []
for k in h.get('kinds', []):
    if not k.get('sources'):
        continue
    parts.append('%s on %s, %ss old, %d of %d stale, %d failovers in 24h' % (
        k['kind'], k.get('active') or 'nothing', k.get('lastUpdateAgeSec'),
        len(k.get('stale', [])), k.get('markets', 0), k.get('failovers24h', 0)))
s = h.get('stream') or {}
if s.get('enabled'):
    parts.append('stream %s, %d reconnects' % ('up' if s.get('connected') else 'down', s.get('reconnects', 0)))
print('%s|%s' % ('true' if h.get('ok') else 'false', '; '.join(parts)))
" 2>/dev/null)
  case "$md" in
    true\|*) add "market data" true "${md#true|}" ;;
    false\|*) add "market data" false "${md#false|}" ;;
    *) add "market data" false "no answer from the engine" ;;
  esac

  local free
  free=$(df -BG --output=avail "$data" | tail -1 | tr -dc 0-9)
  if [ "${free:-0}" -gt 20 ]; then add "disk" true "${free} GB free"; else add "disk" false "only ${free} GB free"; fi

  local all=true
  for c in "${checks[@]}"; do case $c in *'"ok":false'*) all=false ;; esac; done
  local IFS=,
  printf '{"at":"%s","ok":%s,"checks":[%s]}\n' "$(date -u +%FT%TZ)" "$all" "${checks[*]}" > "$out.tmp" && mv "$out.tmp" "$out"
}

main "$@"
