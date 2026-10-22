#!/usr/bin/env bash
# Install the host side of the ops (job runner, job table, health check,
# notify) into /opt/pythia-ops and render /etc/cron.d/pythia-jobs from the table.
#
#   research/ops/deploy_ops.sh [--prune-legacy] [--no-cron] [--dest DIR]
#
# The table is validated with the new runner before anything is installed; a
# broken table changes nothing. A job whose old hand-written cron file
# (`replaces` in the table) is still in /etc/cron.d stays commented out, so
# nothing runs twice; --prune-legacy moves those files to
# /etc/pythia/cron-legacy/ and hands their jobs to the table (once, when
# switching). Safe to run again after every pull.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lab="$here/../lab/lab/ops"
dest=/opt/pythia-ops
render_args=()
cron=true
while [ $# -gt 0 ]; do
  case $1 in
    --prune-legacy) render_args+=(--prune-legacy) ;;
    --no-cron) cron=false ;;
    --dest) dest=${2:?--dest needs a folder}; shift ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

command -v python3 >/dev/null || { echo "deploy_ops: python3 is not installed" >&2; exit 1; }

# 1. the new table must load with the new runner
python3 -I "$lab/jobs.py" --table "$here/jobs.yaml" validate

# 2. install
install -d -m 755 "$dest"
install -m 755 "$lab/jobs.py" "$dest/jobs.py"
install -m 644 "$lab/notify.py" "$dest/notify.py"
install -m 644 "$lab/i18n.py" "$dest/i18n.py"
install -m 644 "$here/jobs.yaml" "$dest/jobs.yaml"
install -m 755 "$here/system_health.sh" "$dest/system_health.sh"
install -m 755 "$here/deploy_lab.sh" "$dest/deploy_lab.sh"
install -d -m 755 "$dest/agent"
install -m 755 "$here/agent/run_agent.sh" "$dest/agent/run_agent.sh"
install -m 644 "$here/agent/guard.py" "$here/agent/Dockerfile" "$here/agent/research.md" "$here/agent/care.md" "$dest/agent/"

# 3. cron
if [ "$cron" = true ]; then
  python3 -I "$dest/jobs.py" --table "$dest/jobs.yaml" render "${render_args[@]}"
fi
python3 -I "$dest/jobs.py" --table "$dest/jobs.yaml" status --write > /dev/null
echo "deploy_ops: installed to $dest"
