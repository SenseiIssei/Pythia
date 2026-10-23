"""The long-running bot: lays out the server at start (and every six hours), answers the slash commands.

  python -m pythia_discord.bot          (the container's command; research/ops/discord-bot.sh)
  python -m pythia_discord.bot --layout lay out the server once and exit, no gateway

Environment (from /etc/pythia/discord.env through --env-file; the token is a secret and is
never printed): PYTHIA_DISCORD_BOT_TOKEN, PYTHIA_DISCORD_GUILD_ID, PYTHIA_DISCORD_OWNER_ID;
PYTHIA_DATA (the data folder, read only, default /data) and PYTHIA_DISCORD_STATE (its own
folder for channels.json, default /state).

The gateway connection carries the slash commands only: no privileged intents, no message
content, guild commands of this one server. Sending the lab's messages is not done here but
by the lab itself through the REST API (lab.ops.notify), with the channel map this bot keeps.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

import discord
from discord import app_commands

from . import commands, layout
from .rest import Rest

LAYOUT_EVERY_S = 6 * 3600
log = logging.getLogger("pythia.discord")


def env(name: str) -> str:
    v = (os.environ.get(name) or "").strip()
    if not v:
        raise SystemExit(f"{name} is not set (see /etc/pythia/discord.env)")
    return v


def state_path() -> Path:
    return Path(os.environ.get("PYTHIA_DISCORD_STATE", "/state")) / "channels.json"


def lay_out(token: str, guild_id: str, owner_id: str) -> None:
    try:
        layout.apply(Rest(token), guild_id, owner_id, state_path(), log=log.info)
    except Exception as e:  # noqa: BLE001 - the commands keep working, the next round tries again
        log.warning("layout failed: %s: %s", type(e).__name__, e)   # Rest's errors never hold the token


def make_callback(name: str, owner_id: str):
    async def callback(interaction: discord.Interaction) -> None:
        out = commands.respond(name, interaction.user.id, owner_id, int(time.time() * 1000))
        await interaction.response.send_message(content=out["content"],
                                                embeds=[discord.Embed.from_dict(e) for e in out["embeds"]],
                                                ephemeral=out["ephemeral"],
                                                allowed_mentions=discord.AllowedMentions.none())
        log.info("/%s by %s: %s", name, "owner" if commands.allowed(interaction.user.id, owner_id) else "someone else",
                 "answered" if out["embeds"] else out["content"])
    return callback


class Bot(discord.Client):
    def __init__(self, token: str, guild_id: str, owner_id: str):
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(intents=intents)
        self.token_, self.guild_id, self.owner_id = token, guild_id, owner_id
        self.tree = app_commands.CommandTree(self)
        self.guild = discord.Object(id=int(guild_id))
        for name, desc in commands.COMMANDS:
            self.tree.add_command(app_commands.Command(name=name, description=desc,
                                                       callback=make_callback(name, owner_id)), guild=self.guild)

    def __repr__(self) -> str:
        return "Bot(<token>)"

    async def setup_hook(self) -> None:
        await self.tree.sync(guild=self.guild)
        log.info("slash commands synced: %s", ", ".join("/" + n for n, _ in commands.COMMANDS))
        self.loop.create_task(self.relayout())

    async def relayout(self) -> None:
        while not self.is_closed():
            await asyncio.sleep(LAYOUT_EVERY_S)
            await asyncio.to_thread(lay_out, self.token_, self.guild_id, self.owner_id)

    async def on_ready(self) -> None:
        log.info("connected as %s", self.user)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = env("PYTHIA_DISCORD_BOT_TOKEN")
    guild_id, owner_id = env("PYTHIA_DISCORD_GUILD_ID"), env("PYTHIA_DISCORD_OWNER_ID")
    lay_out(token, guild_id, owner_id)
    if "--layout" in argv:
        return 0
    Bot(token, guild_id, owner_id).run(token, log_handler=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
