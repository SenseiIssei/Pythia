#!/usr/bin/env bash
# Set up Discord for Pythia: the morning briefing and every real-money trade card.
#
#   sudo /opt/pythia-ops/discord-setup.sh [--env-file FILE] [--no-test]
#
# Make a private channel on your Discord server first (it is your "DM": a webhook
# can only post into a channel), then Channel settings, Integrations, Webhooks,
# New webhook, Copy webhook URL. Optionally a second channel for the trades.
# The script asks for the URL(s) without showing them, writes them into
# /etc/pythia/alerts.env (mode 600, root only) as PYTHIA_DISCORD_WEBHOOK and
# PYTHIA_DISCORD_WEBHOOK_TRADES, and posts one test message to each. The URLs
# are never printed, logged or passed on a command line. Run it again to change
# them; an empty answer keeps what is there. Nothing else in the file changes.
set -euo pipefail

env_file=/etc/pythia/alerts.env
send_test=true
while [ $# -gt 0 ]; do
  case $1 in
    --env-file) env_file=${2:?--env-file needs a file}; shift ;;
    --no-test) send_test=false ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

if [ "$env_file" = /etc/pythia/alerts.env ] && [ "$(id -u)" -ne 0 ]; then
  echo "discord-setup: run as root (it writes /etc/pythia/alerts.env)" >&2
  exit 1
fi

valid() {
  case $1 in
    https://discord.com/api/webhooks/*/*|https://discordapp.com/api/webhooks/*/*|https://ptb.discord.com/api/webhooks/*/*|https://canary.discord.com/api/webhooks/*/*)
      case $1 in *[[:space:]\"\'\\]*) return 1 ;; esac
      return 0 ;;
  esac
  return 1
}

ask() {  # ask <prompt> <var>: read without echo, until empty or valid
  local v
  while true; do
    printf '%s' "$1" >&2
    IFS= read -rs v || v=""
    echo >&2
    if [ -z "$v" ] || valid "$v"; then
      printf -v "$2" '%s' "$v"
      return 0
    fi
    echo "  that is not a Discord webhook URL (https://discord.com/api/webhooks/...), try again" >&2
  done
}

main_url=""
trades_url=""
ask "Webhook URL of your private channel (empty: keep the current one): " main_url
ask "Webhook URL for real-money trades (empty: the same channel): " trades_url

install -d -m 700 "$(dirname "$env_file")"
[ -f "$env_file" ] || install -m 600 /dev/null "$env_file"
current() { grep -E "^$1=" "$env_file" | tail -n 1 | cut -d= -f2- || true; }
[ -n "$main_url" ] || main_url=$(current PYTHIA_DISCORD_WEBHOOK)
[ -n "$trades_url" ] || trades_url=$(current PYTHIA_DISCORD_WEBHOOK_TRADES)
if [ -z "$main_url" ]; then
  echo "discord-setup: no webhook given and none set; nothing changed" >&2
  exit 1
fi

# Rewrite the file without the old Discord lines, then append the new ones; mode 600 throughout.
tmp=$(mktemp "$env_file.XXXXXX")
chmod 600 "$tmp"
grep -vE '^PYTHIA_DISCORD_WEBHOOK(_TRADES)?=' "$env_file" > "$tmp" || true
printf 'PYTHIA_DISCORD_WEBHOOK=%s\n' "$main_url" >> "$tmp"
[ -z "$trades_url" ] || printf 'PYTHIA_DISCORD_WEBHOOK_TRADES=%s\n' "$trades_url" >> "$tmp"
mv "$tmp" "$env_file"
chmod 600 "$env_file"
echo "discord-setup: written to $env_file (mode 600)"

test_post() {  # test_post <url> <label>: the URL goes to curl on stdin, never on its command line
  local code
  code=$(printf 'url = "%s"\n' "$1" | curl -sS -o /dev/null -w '%{http_code}' -K - \
    -H 'Content-Type: application/json' --max-time 15 \
    --data "{\"username\": \"Pythia\", \"content\": \"Pythia: Discord ist eingerichtet ($2). Hier kommen das Morgen-Briefing um 9:00 und jede Echtgeld-Order an.\", \"allowed_mentions\": {\"parse\": []}}" \
    2>/dev/null) || code=000
  if [ "${code:0:1}" = 2 ]; then
    echo "  test message to the $2 channel: ok"
  else
    echo "  test message to the $2 channel: failed (HTTP $code); check the webhook in Discord" >&2
    return 1
  fi
}

if [ "$send_test" = true ]; then
  command -v curl >/dev/null || { echo "discord-setup: curl is not installed, no test message" >&2; exit 0; }
  ok=0
  test_post "$main_url" "Briefing" || ok=1
  if [ -n "$trades_url" ] && [ "$trades_url" != "$main_url" ]; then
    test_post "$trades_url" "Trades" || ok=1
  fi
  exit $ok
fi
