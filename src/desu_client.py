from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests


@dataclass
class MangaSummary:
    id: int
    title: str
    cover: str | None
    genres: list[str]


@dataclass
class MangaDetail:
    id: int
    title: str
    year: int | None
    description: str
    genres: list[str]
    cover: str | None
    chapters_count: int | None
    rating: float | None


class DesuClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = urljoin(f"{self.base_url}/", path.lstrip("/"))
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        return response.json()

    def search_manga(
        self,
        *,
        genres: list[str] | None = None,
        keywords: str | None = None,
        popularity: bool = False,
        is_new: bool = False,
        page: int = 1,
    ) -> list[MangaSummary]:
        params: dict[str, Any] = {"page": page}
        if genres:
            # Try both 'genres' (comma-sep) and 'genre' (single) params
            params["genres"] = ",".join(genres)
        if keywords:
            params["search"] = keywords
        if popularity:
            params["order"] = "popular"
        if is_new:
            params["order"] = "updated"
        params["limit"] = 20
        data = self._request("/manga/api", params=params)
        # Debug: log response structure and params
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Search params: {params}")
        logger.info(f"API response type: {type(data)}, keys: {data.keys() if isinstance(data, dict) else 'N/A'}")
        # API returns {"response": [...]} or could be a list directly
        if isinstance(data, dict):
            items = data.get("response", [])
            # If response is also a dict with a list inside
            if isinstance(items, dict):
                items = items.get("list", [])
            logger.info(f"Items count: {len(items) if isinstance(items, list) else 'N/A'}")
        else:
            items = data if isinstance(data, list) else []
        return [
            MangaSummary(
                id=item.get("id"),
                title=item.get("russian") or item.get("title") or "Untitled",
                cover=(item.get("image") or {}).get("original"),
                genres=[self._parse_genre(g) for g in item.get("genres", [])],
            )
            for item in items
        ]

    @staticmethod
    def _parse_genre(genre: Any) -> str:
        if isinstance(genre, str):
            return genre
        if isinstance(genre, dict):
            return genre.get("russian") or genre.get("name") or "Unknown"
        return str(genre)

    def get_manga_detail(self, manga_id: int) -> MangaDetail:
        raw = self._request(f"/manga/api/{manga_id}")
        data = raw.get("response", raw) if isinstance(raw, dict) else raw
        return MangaDetail(
            id=data.get("id"),
            title=data.get("russian") or data.get("title") or "Untitled",
            year=data.get("year"),
            description=data.get("description", ""),
            genres=[self._parse_genre(g) for g in data.get("genres", [])],
            cover=(data.get("image") or {}).get("original"),
            chapters_count=data.get("chapters", {}).get("count") if isinstance(data.get("chapters"), dict) else data.get("chapters"),
            rating=data.get("score"),
        )

    def get_manga_chapters(self, manga_id: int) -> list[dict[str, Any]]:
        raw = self._request(f"/manga/api/{manga_id}")
        data = raw.get("response", raw) if isinstance(raw, dict) else raw
        chapters = data.get("chapters", {})
        return chapters.get("list", []) if isinstance(chapters, dict) else []

    def get_chapter_pages(self, manga_id: int, chapter_id: int) -> list[dict[str, Any]]:
        raw = self._request(f"/manga/api/{manga_id}/chapter/{chapter_id}")
        data = raw.get("response", raw) if isinstance(raw, dict) else raw
        pages = data.get("pages", {})
        return pages.get("list", pages) if isinstance(pages, dict) else pages
