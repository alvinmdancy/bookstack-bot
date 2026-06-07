import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.bookstack.client import BookStackClient, BookStackError
from bot.utils.formatting import (
    build_books_embed,
    build_created_embed,
    build_page_embed,
    build_search_embed,
    build_shelves_embed,
)

log = logging.getLogger("bookstack-bot.wiki")


class Wiki(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bs = BookStackClient()

    wiki = app_commands.Group(name="wiki", description="Interact with BookStack")

    @wiki.command(name="search", description="Search BookStack content")
    @app_commands.describe(query="What to search for")
    async def search(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        try:
            results = await self.bs.search(query)
            await interaction.followup.send(embed=build_search_embed(results, query))
        except BookStackError as e:
            await interaction.followup.send(f"BookStack error: {e}", ephemeral=True)
        except Exception as e:
            log.exception("Unexpected error in /wiki search")
            await interaction.followup.send(f"Unexpected error: {e}", ephemeral=True)

    @wiki.command(name="page", description="Get a page by ID")
    @app_commands.describe(page_id="Numeric page ID")
    async def page(self, interaction: discord.Interaction, page_id: int):
        await interaction.response.defer()
        try:
            page = await self.bs.get_page(page_id)
            await interaction.followup.send(embed=build_page_embed(page))
        except BookStackError as e:
            await interaction.followup.send(f"BookStack error: {e}", ephemeral=True)
        except Exception as e:
            log.exception("Unexpected error in /wiki page")
            await interaction.followup.send(f"Unexpected error: {e}", ephemeral=True)

    @wiki.command(name="create", description="Create a page stub in a book")
    @app_commands.describe(
        book_id="Book ID to add the page to",
        title="Page title",
        content="Optional markdown content",
    )
    async def create(
        self,
        interaction: discord.Interaction,
        book_id: int,
        title: str,
        content: str = "",
    ):
        await interaction.response.defer()
        try:
            page = await self.bs.create_page(book_id, title, content)
            await interaction.followup.send(embed=build_created_embed(page, book_id))
        except BookStackError as e:
            await interaction.followup.send(f"BookStack error: {e}", ephemeral=True)
        except Exception as e:
            log.exception("Unexpected error in /wiki create")
            await interaction.followup.send(f"Unexpected error: {e}", ephemeral=True)

    @wiki.command(name="list", description="List books or shelves")
    @app_commands.describe(kind="What to list")
    @app_commands.choices(kind=[
        app_commands.Choice(name="books", value="books"),
        app_commands.Choice(name="shelves", value="shelves"),
    ])
    async def list_items(self, interaction: discord.Interaction, kind: str = "books"):
        await interaction.response.defer()
        try:
            if kind == "shelves":
                data = await self.bs.list_shelves()
                embed = build_shelves_embed(data)
            else:
                data = await self.bs.list_books()
                embed = build_books_embed(data)
            await interaction.followup.send(embed=embed)
        except BookStackError as e:
            await interaction.followup.send(f"BookStack error: {e}", ephemeral=True)
        except Exception as e:
            log.exception("Unexpected error in /wiki list")
            await interaction.followup.send(f"Unexpected error: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Wiki(bot))