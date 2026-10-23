#!/usr/bin/env bash
# Build and (re)start Pythia's Discord bot, the container pythia-discord-bot, 24/7.
#
#   sudo /opt/pythia-ops/discord-bot.sh [--no-build] [--src DIR] [--env-file FILE] [--data DIR]
#
# The bot (research/discord, installed to /opt/pythia-ops/discord by deploy_ops.sh) lays out
# the owner's private server at start and every six hours (categories, channels, topics, the
# role Pythia, everything private to the owner and the bot, a pinned welcome post in #status),
# keeps the channel map in <data>/discord/channels.json for the lab and answers the read-only
# slash commands /status, /trades, /konten, /lab for the owner only.
#
# It sees: /etc/pythia/discord.env through --env-file (PYTHIA_DISCORD_BOT_TOKEN,
# PYTHIA_DISCORD_GUILD_ID, PYTHIA_DISCORD_OWNER_ID; read by docker on the host, never mounted),
# <data>/reports read only, <data>/discord writable (its state). No wallet, no key but its own
# token, nothing else of /etc/pythia. Memory 256m, restart unless-stopped; a docker stop keeps
# it down. Run it again after a pull to rebuild and restart; the values are never printed.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src=""
env_file=/etc/pythia/discord.env
data=/srv/pythia-data
build=true
name=pythia-discord-bot
image=pythia-discord-bot
while [ $# -gt 0 ]; do
  case $1 in
    --no-build) build=false ;;
    --src) src=${2:?--src needs the research/discord folder}; shift ;;
    --env-file) env_file=${2:?--env-file needs a file}; shift ;;
    --data) data=${2:?--data needs a folder}; shift ;;
    -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

die() { echo "discord-bot: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run it as root (it reads $env_file through docker)"
command -v docker >/dev/null || die "docker is not installed"
if [ -z "$src" ]; then
  for d in "$here/../discord" "$here/discord"; do
    [ -f "$d/Dockerfile" ] && { src=$d; break; }
  done
fi
[ -f "$src/Dockerfile" ] && [ -d "$src/pythia_discord" ] || die "no bot source (research/discord) found; --src DIR"
[ -f "$env_file" ] || die "$env_file is missing (PYTHIA_DISCORD_BOT_TOKEN, PYTHIA_DISCORD_GUILD_ID, PYTHIA_DISCORD_OWNER_ID)"
for k in PYTHIA_DISCORD_BOT_TOKEN PYTHIA_DISCORD_GUILD_ID PYTHIA_DISCORD_OWNER_ID; do
  grep -qE "^$k=." "$env_file" || die "$k is not set in $env_file"   # only checked, never shown
done
[ -d "$data/reports" ] || die "no $data/reports"

# Its state folder, owned by the container's user (uid 10001), readable by the lab.
install -d -m 755 -o 10001 -g 10001 "$data/discord"

if [ "$build" = true ]; then
  docker build -q -t "$image" "$src" >/dev/null
  echo "discord-bot: image $image built from $src"
fi

if docker container inspect "$name" >/dev/null 2>&1; then
  docker stop "$name" >/dev/null
  docker rm "$name" >/dev/null
  echo "discord-bot: old container removed"
fi

docker run -d --name "$name" --restart unless-stopped --memory 256m --cpus 0.5 \
  --env-file "$env_file" -e PYTHIA_DATA=/data -e PYTHIA_DISCORD_STATE=/state \
  --log-opt max-size=10m --log-opt max-file=3 \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
  -v "$data/reports:/data/reports:ro" -v "$data/discord:/state" \
  "$image" >/dev/null
echo "discord-bot: $name started (docker logs -f $name)"
