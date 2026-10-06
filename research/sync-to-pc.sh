#!/usr/bin/env bash
# Pulls everything finished from the VPS data store to this PC. Safe to run any
# time the PC is on: it only copies files that are missing or changed locally,
# and skips today's partitions because the recorder is still writing them.
#
#   bash research/sync-to-pc.sh            # default target F:/PythiaData
#   PYTHIA_LOCAL=D:/data bash research/sync-to-pc.sh
#
# Windows Task Scheduler runs it at logon and every two hours (see README).
set -euo pipefail

main() {
  local host="${PYTHIA_VPS:-root@82.165.118.241}"
  local remote="/srv/pythia-data"
  local local_root="${PYTHIA_LOCAL:-F:/PythiaData}"
  local today
  today="$(date -u +%Y-%m-%d)"
  mkdir -p "$local_root"
  local log="$local_root/sync.log"
  # One run at a time: the first pull of several GB outlasts the 2-hour schedule.
  local lock="$local_root/.sync.lock"
  if ! mkdir "$lock" 2>/dev/null; then
    echo "$(date -u +%FT%TZ) another sync is running, skipped" >> "$log"
    return 0
  fi
  trap 'rmdir "$lock"' EXIT

  # path<TAB>size for every file the VPS has finished writing
  local remote_list local_list want
  remote_list="$(mktemp)"; local_list="$(mktemp)"; want="$(mktemp)"
  trap 'rm -f "$remote_list" "$local_list" "$want"' RETURN

  ssh -o BatchMode=yes -o ConnectTimeout=15 "$host" \
    "cd $remote && find . -type f ! -name '*.tmp' ! -path './_health/*' ! -path '*/date=$today/*' -printf '%P\t%s\n'" \
    | sort > "$remote_list"

  (cd "$local_root" && find . -type f ! -name sync.log -printf '%P\t%s\n' 2>/dev/null | sort) > "$local_list"

  # Files missing locally or with a different size (a day file that got compacted, a report rewritten)
  comm -23 "$remote_list" "$local_list" | cut -f1 > "$want"
  local n
  n="$(wc -l < "$want")"
  if [ "$n" -eq 0 ]; then
    echo "$(date -u +%FT%TZ) up to date" >> "$log"
    return 0
  fi

  # tar over ssh keeps it to one connection; -T reads the file list from stdin
  ssh -o BatchMode=yes "$host" "cd $remote && tar -cf - -T -" < "$want" | tar --force-local -xf - -C "$local_root"

  # Day partitions on the VPS are first parts, then one day.parquet. Remove local
  # parts that the VPS has already folded away, or readers would count rows twice.
  (cd "$local_root" && find . -type f -name 'part-*.parquet' -printf '%P\n') | while read -r p; do
    if ! grep -qF "$p	" "$remote_list"; then rm -f "$local_root/$p"; fi
  done

  echo "$(date -u +%FT%TZ) pulled $n files" >> "$log"
}

main "$@"
