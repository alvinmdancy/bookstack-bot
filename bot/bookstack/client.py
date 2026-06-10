import os

import httpx


class BookStackError(Exception):
    """Raised when BookStack returns a non-2xx response."""
    pass


class BookStackClient:
    def __init__(self):
        base_url = os.getenv("BOOKSTACK_URL", "")
        token_id = os.getenv("BOOKSTACK_TOKEN_ID", "")
        token_secret = os.getenv("BOOKSTACK_TOKEN_SECRET", "")

        if not all([base_url, token_id, token_secret]):
            raise RuntimeError(
                "Missing BookStack config. Set BOOKSTACK_URL, "
                "BOOKSTACK_TOKEN_ID, and BOOKSTACK_TOKEN_SECRET."
            )

        self.base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Token {token_id}:{token_secret}",
            "Content-Type": "application/json",
        }

    async def _get(self, path: str, params: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{self.base_url}/api{path}",
                headers=self._headers,
                params=params or {},
            )
            if r.status_code >= 400:
                raise BookStackError(
                    f"BookStack returned {r.status_code}: {r.text}"
                )
            return r.json()

    async def _post(self, path: str, body: dict) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{self.base_url}/api{path}",
                headers=self._headers,
                json=body,
            )
            if r.status_code >= 400:
                raise BookStackError(
                    f"BookStack returned {r.status_code}: {r.text}"
                )
            return r.json()

    async def search(self, query: str, count: int = 5) -> dict:
        return await self._get("/search", {"query": query, "count": count})

    async def get_page(self, page_id: int) -> dict:
        return await self._get(f"/pages/{page_id}")

    async def list_books(self, count: int = 20) -> dict:
        return await self._get("/books", {"count": count})

    async def list_shelves(self, count: int = 20) -> dict:
        return await self._get("/shelves", {"count": count})

    async def create_page(self, book_id: int, title: str, markdown: str = "") -> dict:
        return await self._post(
            "/pages",
            {
                "book_id": book_id,
                "name": title,
                "markdown": markdown or f"# {title}\n\n_Stub created via Discord._",
            },
        )
    
    async def get_shelf(self, shelf_id: int) -> dict:
        return await self._get(f"/shelves/{shelf_id}")

    async def export_book_pdf(self, book_id: int) -> bytes:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{self.base_url}/api/books/{book_id}/export/pdf",
                headers=self._headers,
            )
            if r.status_code >= 400:
                raise BookStackError(
                    f"BookStack returned {r.status_code}: {r.text}"
                )
            return r.content