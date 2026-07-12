import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bookstack-bot")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")

# Set this to "true" for exactly one deploy to wipe stale global commands,
# then set it back to "false" (or unset it) and redeploy.
CLEAR_GLOBAL_COMMANDS = os.getenv("CLEAR_GLOBAL_COMMANDS", "false").lower() == "true"


class BookStackBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Load cogs
        await self.load_extension("bot.cogs.wiki")

        # -----------------------------
        # ONE-TIME GLOBAL CLEANUP
        # -----------------------------
        # Run this once if you have stale global commands (e.g. /bookstack list)
        # left over from an older version of the bot. Set CLEAR_GLOBAL_COMMANDS=true
        # in your env/secret for one deploy, confirm the logs show 0 global commands,
        # then unset it.
        if CLEAR_GLOBAL_COMMANDS:
            log.warning("CLEAR_GLOBAL_COMMANDS is set. Wiping all global commands.")
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            log.warning("Global commands cleared. Set CLEAR_GLOBAL_COMMANDS=false now.")

        # -----------------------------
        # DEV MODE: GUILD SYNC ONLY
        # -----------------------------
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))

            log.info("Clearing old guild commands...")
            self.tree.clear_commands(guild=guild)

            log.info("Copying global commands to guild scope...")
            self.tree.copy_global_to(guild=guild)

            log.info("Syncing fresh commands to guild...")
            synced = await self.tree.sync(guild=guild)

            log.info(
                f"Guild sync complete: {len(synced)} commands registered to {GUILD_ID}"
            )
            for cmd in synced:
                log.info(f"  -> /{cmd.name}")

        # -----------------------------
        # PROD MODE: GLOBAL SYNC
        # -----------------------------
        else:
            log.info("Syncing global commands (this may take time)...")
            synced = await self.tree.sync()
            log.info(f"Global sync complete: {len(synced)} commands registered")
            for cmd in synced:
                log.info(f"  -> /{cmd.name}")

        # -----------------------------
        # DIAGNOSTIC: show what Discord actually has stored
        # -----------------------------
        try:
            global_cmds = await self.tree.fetch_commands()
            log.info(f"Discord global commands: {[c.name for c in global_cmds]}")

            if GUILD_ID:
                guild = discord.Object(id=int(GUILD_ID))
                guild_cmds = await self.tree.fetch_commands(guild=guild)
                log.info(f"Discord guild commands: {[c.name for c in guild_cmds]}")
        except discord.HTTPException as e:
            log.warning(f"Could not fetch commands for diagnostics: {e}")

    async def on_ready(self):
        log.info(f"Logged in as {self.user} (ID: {self.user.id})")


def main():
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set")

    bot = BookStackBot()
    bot.run(DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
