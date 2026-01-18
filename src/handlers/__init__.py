"""Handlers package."""
from aiogram import Router

from .base import router as base_router
from .search import router as search_router
from .manga import router as manga_router
from .admin import router as admin_router


def setup_routers() -> Router:
    """Setup and return main router with all handlers."""
    main_router = Router()
    main_router.include_router(base_router)
    main_router.include_router(search_router)
    main_router.include_router(manga_router)
    main_router.include_router(admin_router)
    return main_router
