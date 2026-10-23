# Pythia's Discord bot

A small long-running service for the owner's private Discord server. It runs in the container
`pythia-discord-bot` (`research/ops/discord-bot.sh`, installed by `deploy_ops.sh`; see "Discord
bot" in `research/ops/README.md`).

| File | What |
|---|---|
| `pythia_discord/layout.py` | the server's layout in a German and an English block (categories, channels, topics in their language, the role Pythia, private overwrites, a pinned welcome post in both #status, the order), idempotent and additive, keeps known channel ids; writes the channel map `channels.json` (`de`, `en`, and `channels` for older readers) |
| `pythia_discord/commands.py` | the slash commands `/status`, `/trades`, `/konten`, `/lab`: owner only, read only, from the reports folder, answered in the channel's language |
| `pythia_discord/rest.py` | Discord's REST API with the standard library; the token only in the header |
| `pythia_discord/bot.py` | the gateway (discord.py, no privileged intents) for the slash commands; the layout at start and every six hours |

The lab's messages are not sent from here: `lab.ops.notify` posts them through the REST API
with the same token and this bot's channel map (`DISCORD_ROUTES`, `DISCORD_EN`), each post in German
to the German channel and in English to its English twin.

Environment: `PYTHIA_DISCORD_BOT_TOKEN`, `PYTHIA_DISCORD_GUILD_ID`, `PYTHIA_DISCORD_OWNER_ID`
(from `/etc/pythia/discord.env`), `PYTHIA_DATA` (default `/data`), `PYTHIA_DISCORD_STATE`
(default `/state`). Tests: `research/lab/tests/test_discord_bot.py` (a fake Discord, no network).
