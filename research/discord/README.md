# Pythia's Discord bot

A small long-running service for the owner's private Discord server. It runs in the container
`pythia-discord-bot` (`research/ops/discord-bot.sh`, installed by `deploy_ops.sh`; see "Discord
bot" in `research/ops/README.md`).

| File | What |
|---|---|
| `pythia_discord/layout.py` | the server's layout (categories, channels, topics, the role Pythia, private overwrites, the pinned welcome post), idempotent and additive; writes the channel map `channels.json` |
| `pythia_discord/commands.py` | the slash commands `/status`, `/trades`, `/konten`, `/lab`: owner only, read only, from the reports folder |
| `pythia_discord/rest.py` | Discord's REST API with the standard library; the token only in the header |
| `pythia_discord/bot.py` | the gateway (discord.py, no privileged intents) for the slash commands; the layout at start and every six hours |

The lab's messages are not sent from here: `lab.ops.notify` posts them through the REST API
with the same token and this bot's channel map (`DISCORD_ROUTES`).

Environment: `PYTHIA_DISCORD_BOT_TOKEN`, `PYTHIA_DISCORD_GUILD_ID`, `PYTHIA_DISCORD_OWNER_ID`
(from `/etc/pythia/discord.env`), `PYTHIA_DATA` (default `/data`), `PYTHIA_DISCORD_STATE`
(default `/state`). Tests: `research/lab/tests/test_discord_bot.py` (a fake Discord, no network).
