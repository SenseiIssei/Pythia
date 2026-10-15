#!/usr/bin/env bash
# One command from a fresh Linux server to everything Pythia runs, as root:
#
#   git clone https://github.com/SenseiIssei/Pythia.git /opt/pythia-src && /opt/pythia-src/research/ops/bootstrap.sh
#
# Idempotent: run it again after a pull to bring the server up to date. It
#   1. installs what is missing (docker, rsync, python3, flock, curl) with apt
#      unless --no-install;
#   2. creates the folders: data /srv/pythia-data, backups /srv/pythia-backup,
#      logs /var/log/pythia, secrets /etc/pythia (root only, with an empty
#      alerts.env to fill in);
#   3. builds the images pythia-lab, pythia-recorder and pythia-server;
#   4. deploys the lab code (deploy_lab.sh) and the ops (deploy_ops.sh, which
#      renders /etc/cron.d/pythia-jobs from jobs.yaml);
#   5. starts the recorder, and the two engines if they do not exist yet
#      (--no-engines leaves them alone; existing containers are never replaced);
#   6. runs the health check once and prints what is red.
#
# Options: --no-install, --no-build, --no-engines, --prune-legacy (passed to
# deploy_ops.sh when switching an existing server to the job table).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
data=/srv/pythia-data
install_pkgs=true
build=true
engines=true
ops_args=()
while [ $# -gt 0 ]; do
  case $1 in
    --no-install) install_pkgs=false ;;
    --no-build) build=false ;;
    --no-engines) engines=false ;;
    --prune-legacy) ops_args+=(--prune-legacy) ;;
    -h|--help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '\n== %s\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "bootstrap: run as root" >&2; exit 1; }

say "1. tools"
missing=()
for t in docker rsync python3 flock curl sha256sum du timeout; do
  command -v "$t" >/dev/null || missing+=("$t")
done
if [ ${#missing[@]} -gt 0 ]; then
  if [ "$install_pkgs" = true ] && command -v apt-get >/dev/null; then
    pkgs=()
    for t in "${missing[@]}"; do
      case $t in
        docker) pkgs+=(docker.io docker-compose-v2) ;;
        flock) pkgs+=(util-linux) ;;
        sha256sum|du|timeout) pkgs+=(coreutils) ;;
        *) pkgs+=("$t") ;;
      esac
    done
    apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q "${pkgs[@]}"
    systemctl enable --now docker 2>/dev/null || true
  else
    echo "bootstrap: missing ${missing[*]}; install them and run again" >&2
    exit 1
  fi
fi
docker info >/dev/null 2>&1 || { echo "bootstrap: docker is not running" >&2; exit 1; }

say "2. folders"
install -d -m 755 "$data" "$data/_health" "$data/_ops" "$data/costs" /var/log/pythia /opt/pythia-lab
install -d -m 700 /srv/pythia-backup /etc/pythia
if [ ! -f /etc/pythia/alerts.env ]; then
  install -m 600 /dev/null /etc/pythia/alerts.env
  cat > /etc/pythia/alerts.env <<'ENV'
# Operator alerts (research/ops/README.md, "Alerts"). Root only; never commit this file.
# Telegram: the bot token from BotFather and the chat the bot writes to.
#PYTHIA_TELEGRAM_BOT_TOKEN=
#PYTHIA_TELEGRAM_CHAT_ID=
# Or a Discord or Slack webhook instead:
#PYTHIA_ALERT_WEBHOOK=
#PYTHIA_ALERT_FORMAT=discord
ENV
  echo "created /etc/pythia/alerts.env, fill in the Telegram bot token and chat id"
fi
[ -f "$data/costs/base.json" ] || install -m 644 "$repo/config/costs.json" "$data/costs/base.json"

if [ "$build" = true ]; then
  say "3. images"
  docker build -q -t pythia-lab "$repo/research/lab"
  docker build -q -t pythia-recorder "$repo/research/recorder"
  docker build -q -f "$repo/server/Dockerfile" -t pythia-server "$repo"
fi

say "4. lab code and ops"
"$here/deploy_lab.sh" --src "$repo/research/lab" --dest /opt/pythia-lab --force
"$here/deploy_ops.sh" "${ops_args[@]}"

say "5. services"
install -d -m 755 /opt/pythia-recorder
rsync -a --delete --exclude __pycache__/ --exclude .pytest_cache/ "$repo/research/recorder/" /opt/pythia-recorder/
(cd /opt/pythia-recorder && docker compose up -d)
exists() { docker inspect "$1" >/dev/null 2>&1; }
if [ "$engines" = true ]; then
  install -d -m 755 "$data/server" "$data/autopilot" "$data/models" "$data/reports" "$data/paper"
  # The Claude API ledger and caps (docs/AI.md), shared by both engines.
  install -d -m 700 "$data/ai"
  if ! exists pythia-server; then
    docker run -d --name pythia-server --restart unless-stopped --memory 1g \
      -p 127.0.0.1:8787:8787 \
      -e PYTHIA_MODELS=/models -e PYTHIA_DATA=/data -e PYTHIA_STATE_FILE=/state/state.json \
      -v "$data/models:/models" -v "$data/server:/state" -v "$data/ai:/data/ai" \
      -v "$data/_health:/data/_health:ro" -v "$data/paper:/data/paper:ro" -v "$data/reports:/data/reports:ro" \
      pythia-server
  fi
  if ! exists pythia-autopilot; then
    docker run -d --name pythia-autopilot --restart unless-stopped --memory 1g \
      -p 127.0.0.1:8788:8788 -e PYTHIA_BIND=0.0.0.0:8788 \
      --env-file /etc/pythia/alerts.env \
      -e PYTHIA_MODELS=/models -e PYTHIA_DATA=/data -e PYTHIA_STATE_FILE=/state/state.json \
      -v "$data/models:/models:ro" -v "$data/autopilot:/state" -v "$data/ai:/data/ai" \
      -v "$data/_health:/data/_health:ro" -v "$data/paper:/data/paper:ro" -v "$data/reports:/data/reports:ro" \
      -v "$data/reports/notify:/data/reports/notify" \
      pythia-server
  fi
fi

say "6. health"
python3 /opt/pythia-ops/jobs.py run health --force || true
python3 - "$data/_health/system.json" <<'PY'
import json, sys
try:
    s = json.load(open(sys.argv[1]))
except (OSError, ValueError):
    print("no health file yet"); sys.exit()
red = [c for c in s.get("checks", []) if not c.get("ok")]
print("all green" if not red else "red right after a bootstrap (jobs that have not run yet are fine):")
for c in red:
    print(f"  {c['name']}: {c['detail']}")
PY
echo
echo "bootstrap: done. Jobs: python3 /opt/pythia-ops/jobs.py validate; status: /srv/pythia-data/_health/jobs.json"
