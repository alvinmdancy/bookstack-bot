import io
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

from bot.bookstack.client import BookStackClient, BookStackError
from bot.bookstack.gotenberg_export import export_book_to_pdf, GotenbergExportError

log = logging.getLogger("bookstack-bot.bookstack")

ALLOWED_CHANNEL_ID = [
    int(cid.strip()) for cid in os.getenv("ALLOWED_CHANNEL_ID", "0").split(",")
]

# Used to build "Open in Browser" links. Adjust the env var name here if your
# .env uses something other than BOOKSTACK_URL (check bot/bookstack/client.py).
BOOKSTACK_URL = os.getenv("BOOKSTACK_URL", "").rstrip("/")


def in_allowed_channel(interaction: discord.Interaction) -> bool:
    return ALLOWED_CHANNEL_ID == [0] or interaction.channel_id in ALLOWED_CHANNEL_ID


# =========================================================
# COG
# =========================================================
class bookstack(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bs = BookStackClient()

        # lightweight per-user session store
        self.sessions = {}

    def get_session(self, user_id: int):
        if user_id not in self.sessions:
            self.sessions[user_id] = {
                "shelf_id": None,
                "book_id": None,
            }
        return self.sessions[user_id]

    # =========================================================
    # ENTRY COMMAND (ONLY COMMAND YOU NEED)
    # =========================================================
    @app_commands.command(name="bookstack", description="Open BookStack UI")
    async def bookstack_menu(self, interaction: discord.Interaction):
        if not in_allowed_channel(interaction):
            await interaction.response.send_message(
                "Not allowed in this channel.",
                ephemeral=True,
                delete_after=3,
            )
            return

        try:
            await interaction.response.defer(ephemeral=True)
            shelves = await self.bs.list_shelves(count=25)
        except BookStackError as e:
            await interaction.followup.send(f"BookStack error: {e}", ephemeral=True)
            return

        await interaction.followup.send(
            "📚 BookStack Menu",
            view=MainMenuView(self, shelves),
            ephemeral=True,
        )


# =========================================================
# MAIN MENU
# =========================================================
class MainMenuView(discord.ui.View):
    def __init__(self, cog, shelves):
        super().__init__(timeout=120)
        self.cog = cog
        self.shelves = shelves

    @discord.ui.button(label="Browse Shelves", style=discord.ButtonStyle.primary)
    async def browse(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="Select a shelf:",
            view=ShelfView(self.cog, self.shelves),
        )

    @discord.ui.button(label="Search (basic)", style=discord.ButtonStyle.secondary)
    async def search(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Use `/bookstack search <query>` for now.",
            ephemeral=True,
        )

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="Closed.",
            view=None,
        )


# =========================================================
# SHELF VIEW
# =========================================================
class ShelfView(discord.ui.View):
    def __init__(self, cog, shelves):
        super().__init__(timeout=120)
        self.cog = cog

        options = [
            discord.SelectOption(label=s["name"], value=str(s["id"]))
            for s in shelves.get("data", [])
        ]

        self.select = discord.ui.Select(
            placeholder="Choose a shelf...",
            options=options,
        )
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        shelf_id = int(self.select.values[0])

        session = self.cog.get_session(interaction.user.id)
        session["shelf_id"] = shelf_id

        await interaction.response.defer()

        try:
            shelf = await self.cog.bs.get_shelf(shelf_id)
        except BookStackError as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)
            return

        books = shelf.get("books", [])

        if not books:
            await interaction.followup.send(
                "No books found.",
                ephemeral=True,
            )
            return

        await interaction.edit_original_response(
            content="Select a book:",
            view=BookView(self.cog, books),
        )


# =========================================================
# BOOK VIEW
# =========================================================
class BookView(discord.ui.View):
    def __init__(self, cog, books):
        super().__init__(timeout=120)
        self.cog = cog
        self.books = books

        options = [
            discord.SelectOption(label=b["name"], value=str(b["id"])) for b in books
        ]

        self.select = discord.ui.Select(
            placeholder="Choose a book...",
            options=options,
        )
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        book_id = int(self.select.values[0])

        session = self.cog.get_session(interaction.user.id)
        session["book_id"] = book_id

        book = next((b for b in self.books if str(b["id"]) == str(book_id)), None)
        book_name = book.get("name", "Book") if book else "Book"
        book_slug = book.get("slug") if book else None

        await interaction.response.edit_message(
            content=f"📘 {book_name}",
            view=BookActionView(self.cog, book_id, book_slug),
        )


# =========================================================
# BOOK ACTIONS: EXPORT + OPEN IN BROWSER
# =========================================================
class BookActionView(discord.ui.View):
    def __init__(self, cog, book_id, book_slug=None):
        super().__init__(timeout=120)
        self.cog = cog
        self.book_id = book_id
        self.book_slug = book_slug

        if book_slug and BOOKSTACK_URL:
            url = f"{BOOKSTACK_URL}/books/{book_slug}"
            self.add_item(
                discord.ui.Button(
                    label="Open in Browser",
                    style=discord.ButtonStyle.link,
                    url=url,
                )
            )
        elif not BOOKSTACK_URL:
            log.warning(
                "BOOKSTACK_URL is not set, skipping 'Open in Browser' button. "
                "Set it in .env to enable this."
            )

    @discord.ui.button(label="Export PDF", style=discord.ButtonStyle.success)
    async def export(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        try:
            book = await self.cog.bs.get_book(self.book_id)
        except BookStackError as e:
            await interaction.followup.send(f"Error fetching book: {e}", ephemeral=True)
            return

        try:
            pdf_bytes = await export_book_to_pdf(book)
        except GotenbergExportError as e:
            await interaction.followup.send(f"Export failed: {e}", ephemeral=True)
            return

        file = discord.File(io.BytesIO(pdf_bytes), filename="book.pdf")

        await interaction.followup.send(
            "📦 Export complete (with diagrams):",
            file=file,
            ephemeral=True,
        )


# =========================================================
# REQUIRED SETUP
# =========================================================
async def setup(bot: commands.Bot):
    await bot.add_cog(bookstack(bot))
