"""Dependency injection for the bot."""
from __future__ import annotations

from desu_client import DesuClient
from favorites import FavoritesStore
from config import DESU_BASE_URL

# Global instances
_client: DesuClient | None = None
_favorites: FavoritesStore | None = None


def init_dependencies() -> None:
    """Initialize global dependencies."""
    global _client, _favorites
    _client = DesuClient(DESU_BASE_URL)
    _favorites = FavoritesStore()


def get_client() -> DesuClient:
    """Get DesuClient instance."""
    if _client is None:
        raise RuntimeError("Dependencies not initialized. Call init_dependencies() first.")
    return _client


def get_favorites() -> FavoritesStore:
    """Get FavoritesStore instance."""
    if _favorites is None:
        raise RuntimeError("Dependencies not initialized. Call init_dependencies() first.")
    return _favorites
