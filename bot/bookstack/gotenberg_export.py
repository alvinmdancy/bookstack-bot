"""
gotenberg_export.py

Exports a BookStack book to a single PDF by rendering each live page
through Gotenberg (headless Chromium). Because Gotenberg actually executes
JavaScript, Mermaid diagrams render correctly -- unlike BookStack's built-in
PDF export, which uses dompdf and never runs the page's JavaScript.

Two separate auth layers sit in front of BookStack, and both need to be
satisfied for Chromium's requests to reach real content instead of a login
screen:

1. Cloudflare Access (edge-level). Fixed via a Service Token sent as
   extraHttpHeaders on every request Chromium makes.
2. BookStack's own login (app-level). Since the book/shelf content is
   private, Chromium also needs a real BookStack session cookie, or it
   hits BookStack's native login page instead of the content. Fixed by
   logging in as a dedicated service account once per export and handing
   the resulting session cookie to Gotenberg.

Setup (one-time):
    Cloudflare Access:
        1. Cloudflare Zero Trust dashboard -> Access -> Service Auth ->
           Service Tokens -> create one (e.g. "gotenberg-bookstack-export").
        2. Edit the Access policy protecting your BookStack hostname -> add
           a rule: Include -> Service Auth -> select the token above.
        3. Set CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET in .env.

    BookStack session:
        1. In BookStack admin, create a dedicated low-privilege user
           (e.g. export-bot@yourdomain) with view access to the content
           you want exportable. Don't reuse your own admin login.
        2. Set BOOKSTACK_SERVICE_EMAIL and BOOKSTACK_SERVICE_PASSWORD
           in .env.

Requires:
    pip install aiohttp pypdf
"""

import io
import json
import logging
import os
import re

import aiohttp
from pypdf import PdfWriter

log = logging.getLogger("bookstack-bot.gotenberg_export")

GOTENBERG_URL = os.getenv("GOTENBERG_URL", "http://gotenberg:3000").rstrip("/")
BOOKSTACK_URL = os.getenv("BOOKSTACK_URL", "").rstrip("/")

CF_ACCESS_CLIENT_ID = os.getenv("CF_ACCESS_CLIENT_ID", "")
CF_ACCESS_CLIENT_SECRET = os.getenv("CF_ACCESS_CLIENT_SECRET", "")

BOOKSTACK_SERVICE_EMAIL = os.getenv("BOOKSTACK_SERVICE_EMAIL", "")
BOOKSTACK_SERVICE_PASSWORD = os.getenv("BOOKSTACK_SERVICE_PASSWORD", "")

# Gotenberg waits this many seconds after page load before printing, to give
# the Mermaid hack's JS time to finish rendering diagrams. Bump this up if
# your diagrams are large/complex and not consistently appearing.
RENDER_DELAY_SECONDS = 3

# BookStack's default session cookie name. Laravel apps sometimes derive
# this from APP_NAME instead (e.g. "your_app_name_session") -- if login
# fails to produce a usable cookie, check the actual cookie name your
# instance sets via browser dev tools (Application/Storage -> Cookies)
# and update this.
BOOKSTACK_SESSION_COOKIE_NAME = "bookstack_session"

_CSRF_TOKEN_RE = re.compile(r'name="_token"\s+value="([^"]+)"')


class GotenbergExportError(Exception):
    pass


def _build_extra_headers() -> str:
    """
    Cloudflare Access headers. These get attached to the initial page
    request AND every subsequent resource request Chromium makes (CSS, JS,
    images), authenticating past the Cloudflare edge.
    """
    if not CF_ACCESS_CLIENT_ID or not CF_ACCESS_CLIENT_SECRET:
        log.warning(
            "CF_ACCESS_CLIENT_ID / CF_ACCESS_CLIENT_SECRET are not set. "
            "If BookStack is behind Cloudflare Access, exports will fail "
            "or return the Access login page instead of real content."
        )
        return "{}"

    return json.dumps(
        {
            "CF-Access-Client-Id": CF_ACCESS_CLIENT_ID,
            "CF-Access-Client-Secret": CF_ACCESS_CLIENT_SECRET,
        }
    )


async def _get_bookstack_session_cookie(session: aiohttp.ClientSession) -> str:
    """
    Logs into BookStack as the dedicated service account and returns the
    resulting session cookie value. Needed because the content is private:
    Cloudflare Access gets Chromium past the edge, but BookStack's own
    login wall still blocks unauthenticated requests to private content.

    BookStack's login form is CSRF-protected (Laravel), so this does a
    two-step dance: GET the login page to grab the CSRF token, then POST
    credentials along with that token.
    """
    if not BOOKSTACK_SERVICE_EMAIL or not BOOKSTACK_SERVICE_PASSWORD:
        raise GotenbergExportError(
            "BOOKSTACK_SERVICE_EMAIL / BOOKSTACK_SERVICE_PASSWORD are not "
            "set. Required because this content is private, not public."
        )

    login_headers = {}
    if CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET:
        login_headers = {
            "CF-Access-Client-Id": CF_ACCESS_CLIENT_ID,
            "CF-Access-Client-Secret": CF_ACCESS_CLIENT_SECRET,
        }

    # Step 1: GET the login page to grab the CSRF token and initial cookies.
    async with session.get(f"{BOOKSTACK_URL}/login", headers=login_headers) as resp:
        if resp.status != 200:
            raise GotenbergExportError(
                f"Failed to load BookStack login page: {resp.status}"
            )
        html = await resp.text()

    match = _CSRF_TOKEN_RE.search(html)
    if not match:
        raise GotenbergExportError(
            "Could not find CSRF token on BookStack login page. "
            "The login page's HTML structure may have changed."
        )
    csrf_token = match.group(1)

    # Step 2: POST credentials + CSRF token. aiohttp's cookie jar carries
    # forward the cookies from step 1 automatically.
    async with session.post(
        f"{BOOKSTACK_URL}/login",
        headers=login_headers,
        data={
            "_token": csrf_token,
            "email": BOOKSTACK_SERVICE_EMAIL,
            "password": BOOKSTACK_SERVICE_PASSWORD,
        },
        allow_redirects=True,
    ) as resp:
        if resp.status >= 400:
            raise GotenbergExportError(f"BookStack login failed: {resp.status}")

    # Pull the session cookie back out of the jar.
    cookie_jar = session.cookie_jar
    for cookie in cookie_jar:
        if cookie.key == BOOKSTACK_SESSION_COOKIE_NAME:
            return cookie.value

    raise GotenbergExportError(
        f"Logged into BookStack, but no '{BOOKSTACK_SESSION_COOKIE_NAME}' "
        "cookie was returned. Check BOOKSTACK_SESSION_COOKIE_NAME matches "
        "your instance's actual session cookie name (check browser dev "
        "tools -> Application/Storage -> Cookies while logged in)."
    )


def _build_gotenberg_cookies(session_cookie_value: str) -> str:
    """
    Builds the cookies JSON value Gotenberg expects: an array of cookie
    objects. This is what gives Chromium a real logged-in BookStack
    session, separate from the Cloudflare Access headers.
    """
    # Strip protocol for the domain field.
    domain = BOOKSTACK_URL.replace("https://", "").replace("http://", "")
    return json.dumps(
        [
            {
                "name": BOOKSTACK_SESSION_COOKIE_NAME,
                "value": session_cookie_value,
                "domain": domain,
                "path": "/",
            }
        ]
    )


async def _render_page_to_pdf(
    session: aiohttp.ClientSession, page_url: str, session_cookie_value: str
) -> bytes:
    """Render a single live page URL to PDF via Gotenberg's Chromium route."""
    # aiohttp's FormData defaults to application/x-www-form-urlencoded when
    # every field is a plain string (no file-like objects). Gotenberg only
    # accepts multipart/form-data. Setting an explicit content_type on a
    # field forces FormData into multipart mode, regardless of aiohttp
    # version.
    form = aiohttp.FormData()
    form.add_field("url", page_url, content_type="text/plain")
    # Gives Mermaid's JS time to finish drawing before Chromium prints.
    form.add_field("waitDelay", f"{RENDER_DELAY_SECONDS}s")
    form.add_field("emulatedMediaType", "screen")
    form.add_field(
        "extraHttpHeaders", _build_extra_headers(), content_type="text/plain"
    )
    form.add_field(
        "cookies",
        _build_gotenberg_cookies(session_cookie_value),
        content_type="text/plain",
    )

    async with session.post(
        f"{GOTENBERG_URL}/forms/chromium/convert/url",
        data=form,
        timeout=aiohttp.ClientTimeout(total=60),
    ) as resp:
        if resp.status != 200:
            text = await resp.text()
            log.error(
                f"Gotenberg returned {resp.status} for {page_url}. "
                f"Response headers: {dict(resp.headers)}. Body: {text}"
            )
            raise GotenbergExportError(
                f"Gotenberg returned {resp.status} for {page_url}: {text[:300]}"
            )
        return await resp.read()


def _flatten_book_pages(book: dict) -> list[dict]:
    """
    BookStack's GET /api/books/{id} response includes a "contents" array
    that mixes flat pages with chapters. Chapters nest their own "pages"
    list inside them. This walks that structure and returns a flat list
    of page dicts in reading order.
    """
    pages = []
    for item in book.get("contents", []):
        if item.get("type") == "chapter":
            pages.extend(item.get("pages", []))
        else:
            # type == "page" (or missing type on some BookStack versions)
            pages.append(item)
    return pages


async def export_book_to_pdf(book: dict) -> bytes:
    """
    Renders every page in a book via Gotenberg and merges them into one PDF.

    `book` should be the full dict returned by BookStackClient.get_book(),
    which includes "slug" and a "contents" array of pages/chapters.
    """
    if not BOOKSTACK_URL:
        raise GotenbergExportError("BOOKSTACK_URL is not set in the environment.")

    book_slug = book.get("slug")
    if not book_slug:
        raise GotenbergExportError("Book response is missing a slug.")

    pages = _flatten_book_pages(book)
    if not pages:
        raise GotenbergExportError("Book has no pages to export.")

    page_urls = [
        f"{BOOKSTACK_URL}/books/{book_slug}/page/{page['slug']}" for page in pages
    ]

    async with aiohttp.ClientSession() as session:
        session_cookie_value = await _get_bookstack_session_cookie(session)

        # Render sequentially to avoid hammering Gotenberg/Chromium with
        # too many concurrent tabs on a small homelab box. Bump up
        # concurrency later if Gotenberg has headroom.
        page_pdfs = []
        for url in page_urls:
            log.info(f"Rendering page: {url}")
            pdf_bytes = await _render_page_to_pdf(session, url, session_cookie_value)
            page_pdfs.append(pdf_bytes)

    writer = PdfWriter()
    for pdf_bytes in page_pdfs:
        writer.append(io.BytesIO(pdf_bytes))

    output = io.BytesIO()
    writer.write(output)
    output.seek(0)
    return output.read()
