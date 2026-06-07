import html
import re

import discord


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def truncate(text: str, max_len: int = 300) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"


def build_search_embed(results: dict, query: str) -> discord.Embed:
    embed = discord.Embed(title=f"🔍 Search: {query}", color=discord.Color.blue())
    items = results.get("data", [])
    if not items:
        embed.description = "No results found."
        return embed
    for item in items[:5]:
        name = item.get("name", "Untitled")
        item_type = item.get("type", "page")
        preview_raw = item.get("preview_html", "")
        preview = strip_html(preview_raw if isinstance(preview_raw, str) else "")
        preview = preview or "No preview available."
        url = item.get("url", "")
        value = truncate(preview)
        if url:
            value += f"\n[→ Open]({url})"
        embed.add_field(name=f"[{item_type.upper()}] {name}", value=value, inline=False)
    embed.set_footer(text=f"{results.get('total', len(items))} result(s)")
    return embed


def build_page_embed(page: dict) -> discord.Embed:
    embed = discord.Embed(
        title=page.get("name", "Untitled"),
        url=page.get("url", ""),
        color=discord.Color.green(),
    )
    embed.description = truncate(strip_html(page.get("html", "")), 800) or "_No content._"
    embed.add_field(name="Page ID", value=str(page.get("id", "—")), inline=True)
    embed.add_field(name="Book", value=page.get("book_slug", "—"), inline=True)
    embed.set_footer(text=f"Updated: {page.get('updated_at', 'unknown')}")
    return embed


def build_created_embed(page: dict, book_id: int) -> discord.Embed:
    embed = discord.Embed(
        title="✅ Page Created",
        url=page.get("url", ""),
        color=discord.Color.green(),
    )
    embed.description = f"**{page.get('name')}** added to book `{book_id}`."
    embed.add_field(name="Page ID", value=str(page.get("id")), inline=True)
    embed.add_field(name="Slug", value=page.get("slug", "—"), inline=True)
    return embed


def build_books_embed(books: dict) -> discord.Embed:
    embed = discord.Embed(title="📚 Books", color=discord.Color.orange())
    items = books.get("data", [])
    if not items:
        embed.description = "No books found."
        return embed
    embed.description = "\n".join(f"`{b['id']}` — **{b['name']}**" for b in items[:15])
    embed.set_footer(text=f"{books.get('total', len(items))} book(s) total")
    return embed


def build_shelves_embed(shelves: dict) -> discord.Embed:
    embed = discord.Embed(title="🗂️ Shelves", color=discord.Color.purple())
    items = shelves.get("data", [])
    if not items:
        embed.description = "No shelves found."
        return embed
    embed.description = "\n".join(f"`{s['id']}` — **{s['name']}**" for s in items[:15])
    embed.set_footer(text=f"{shelves.get('total', len(items))} shelf/shelves total")
    return embed