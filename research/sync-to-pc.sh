#!/usr/bin/env bash
# Pulls everything finished from the VPS data store to this PC. Safe to run any
# time the PC is on: it only copies files that are missing or changed locally,
# and skips today's partitions because the recorder is still writing them.
#
#   bash research/sync-to-pc.sh            # default target F:/PythiaData
#   PYTHIA_LOCAL=D:/data bash research/sync-to-pc.sh
#
# Then the newest backup archive (/srv/pythia-backup) lands in <PYTHIA_LOCAL>/_backup, checked by its
# sha256 (a copy whose checksum differs is fetched again), the newest 7 kept (PYTHIA_BACKUP_KEEP); a
# receipt goes back to the server as /srv/pythia-backup/offsite.json, which the health check reads.
#
# Windows Task Scheduler runs it at logon and every two hours (see README).
set -euo pipefail

main() {
  # An ssh alias from ~/.ssh/config, so no host or user lives in the repo
  local host="${PYTHIA_VPS:-pythia-vps}"
  local remote="${PYTHIA_VPS_DATA:-/srv/pythia-data}"
  local local_root="${PYTHIA_LOCAL:-F:/PythiaData}"
  local today
  today="$(date -u +%Y-%m-%d)"
  mkdir -p "$local_root"
  local log="$local_root/sync.log"
  # One run at a time: the first pull of several GB outlasts the 2-hour schedule.
  local lock="$local_root/.sync.lock"
  # A sync killed mid-way (PC shut down, task stopped) never releases its lock.
  # No pull takes three hours, so an older lock is taken over.
  if [ -d "$lock" ] && [ -n "$(find "$lock" -maxdepth 0 -mmin +180 2>/dev/null)" ]; then
    echo "$(date -u +%FT%TZ) stale lock from $(date -r "$lock" -u +%FT%TZ) taken over" >> "$log"
    rmdir "$lock"
  fi
  if ! mkdir "$lock" 2>/dev/null; then
    echo "$(date -u +%FT%TZ) another sync is running, skipped" >> "$log"
    return 0
  fi
  # Expanded now: at EXIT the function's locals are gone (set -u would abort the cleanup)
  trap "rmdir '$lock'" EXIT

  # path<TAB>size for every file the VPS has finished writing
  local remote_list local_list want
  remote_list="$(mktemp)"; local_list="$(mktemp)"; want="$(mktemp)"
  trap 'rm -f "$remote_list" "$local_list" "$want"' RETURN

  ssh -o BatchMode=yes -o ConnectTimeout=15 "$host" \
    "cd $remote && find . -type f ! -name '*.tmp' ! -path './_health/status.json' ! -path '*/date=$today/*' -printf '%P\t%s\n'" \
    | sort > "$remote_list"

  (cd "$local_root" && find . -type f ! -name sync.log -printf '%P\t%s\n' 2>/dev/null | sort) > "$local_list"

  # Files missing locally or with a different size (a day file that got compacted, a report rewritten)
  comm -23 "$remote_list" "$local_list" | cut -f1 > "$want"
  local n
  n="$(wc -l < "$want")"
  if [ "$n" -eq 0 ]; then
    echo "$(date -u +%FT%TZ) up to date" >> "$log"
  else
    # tar over ssh keeps it to one connection; -T reads the file list from stdin
    ssh -o BatchMode=yes "$host" "cd $remote && tar -cf - -T -" < "$want" | tar --force-local -xf - -C "$local_root"

    # Day partitions on the VPS are first parts, then one day.parquet. Remove local
    # parts that the VPS has already folded away, or readers would count rows twice.
    (cd "$local_root" && find . -type f -name 'part-*.parquet' -printf '%P\n') | while read -r p; do
      if ! grep -qF "$p	" "$remote_list"; then rm -f "$local_root/$p"; fi
    done

    echo "$(date -u +%FT%TZ) pulled $n files" >> "$log"
  fi

  pull_backup "$host" "${PYTHIA_LOCAL_BACKUP:-$local_root/_backup}" "$log"
}

# The newest backup archive off the server, by checksum: the server's .sha256 names it, a local copy
# counts only if its sha256 matches, a fresh copy is checked before it replaces anything.
pull_backup() {
  local host="$1" dir="$2" log="$3"
  local rdir="${PYTHIA_VPS_BACKUP:-/srv/pythia-backup}" keep="${PYTHIA_BACKUP_KEEP:-7}"
  local line sha name got
  line="$(ssh -o BatchMode=yes -o ConnectTimeout=15 "$host" \
    "cd $rdir && f=\$(ls -1 pythia-state-*.tar.gz 2>/dev/null | sort | tail -1) && [ -n \"\$f\" ] && cat \"\$f.sha256\"")" || line=""
  sha="${line%% *}"; name="${line##* }"
  if ! [[ "$sha" =~ ^[0-9a-f]{64}$ && "$name" =~ ^pythia-state-[0-9]{8}T[0-9]{6}Z\.tar\.gz$ ]]; then
    echo "$(date -u +%FT%TZ) backup: no archive with a checksum found in $rdir" >> "$log"
    return 1
  fi
  mkdir -p "$dir"
  got=""
  [ -f "$dir/$name" ] && got="$(sha256sum < "$dir/$name" | cut -d' ' -f1)"
  if [ "$got" != "$sha" ]; then
    ssh -o BatchMode=yes "$host" "cat $rdir/$name" > "$dir/.$name.part"
    got="$(sha256sum < "$dir/.$name.part" | cut -d' ' -f1)"
    if [ "$got" != "$sha" ]; then
      rm -f "$dir/.$name.part"
      echo "$(date -u +%FT%TZ) backup: $name arrived with a different checksum, not kept" >> "$log"
      return 1
    fi
    mv -f "$dir/.$name.part" "$dir/$name"
    echo "$sha  $name" > "$dir/$name.sha256"
    echo "$(date -u +%FT%TZ) backup: copied $name" >> "$log"
  fi
  # the newest $keep archives stay (the names sort by time)
  ls -1 "$dir" | grep -E '^pythia-state-[0-9]{8}T[0-9]{6}Z\.tar\.gz$' | sort | head -n "-$keep" | while read -r old; do
    rm -f "$dir/$old" "$dir/$old.sha256"
  done || true
  printf '{"at":"%s","archive":"%s","sha256":"%s"}\n' "$(date -u +%FT%TZ)" "$name" "$sha" \
    | ssh -o BatchMode=yes "$host" "cat > $rdir/.offsite.json.tmp && mv -f $rdir/.offsite.json.tmp $rdir/offsite.json"
}

main "$@"
