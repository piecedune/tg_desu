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
            params["genres"] = ",".join(genres)
        if keywords:
            params["search"] = keywords
        if popularity:
            params["sort"] = "popular"
        if is_new:
            params["sort"] = "new"
        data = self._request("/manga/api", params=params)
        return [
            MangaSummary(
                id=item.get("id"),
                title=item.get("russian") or item.get("title") or "Untitled",
                cover=(item.get("image") or {}).get("original"),
                genres=[genre.get("russian") or genre.get("name") for genre in item.get("genres", [])],
            )
            for item in data
        ]

    def get_manga_detail(self, manga_id: int) -> MangaDetail:
        data = self._request(f"/manga/api/{manga_id}")
        return MangaDetail(
            id=data.get("id"),
            title=data.get("russian") or data.get("title") or "Untitled",
            year=data.get("year"),
            description=data.get("description", ""),
            genres=[genre.get("russian") or genre.get("name") for genre in data.get("genres", [])],
            cover=(data.get("image") or {}).get("original"),
            chapters_count=data.get("chapters"),
            rating=data.get("score"),
        )

    def get_manga_chapters(self, manga_id: int) -> list[dict[str, Any]]:
        data = self._request(f"/manga/api/{manga_id}")
        return data.get("chapters_list", [])

    def get_chapter_pages(self, manga_id: int, chapter_id: int) -> list[dict[str, Any]]:
        data = self._request(f"/manga/api/{manga_id}/chapter/{chapter_id}")
        return data.get("pages", [])
