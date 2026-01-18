"""Utility functions for the bot."""
from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile
import zipfile

import requests
from PIL import Image

from desu_client import MangaDetail

logger = logging.getLogger(__name__)

# Lazy import to avoid circular imports
_favorites_store = None

def _get_store():
    """Get favorites store for error logging."""
    global _favorites_store
    if _favorites_store is None:
        from dependencies import get_favorites
        _favorites_store = get_favorites()
    return _favorites_store


def log_error(error_type: str, message: str, context: str | None = None) -> None:
    """Log error to database and logger."""
    logger.error(f"{error_type}: {message} (context: {context})")
    try:
        store = _get_store()
        if store:
            store.log_error(error_type, message, context)
    except Exception:
        pass  # Don't fail if logging fails


async def run_sync(func, *args, **kwargs):
    """Run sync function in thread pool."""
    return await asyncio.to_thread(func, *args, **kwargs)


def chapter_title(chapter: dict) -> str:
    """Format chapter title from API data."""
    number = chapter.get("ch") or chapter.get("chapter") or chapter.get("number")
    vol = chapter.get("vol")
    title = chapter.get("title")
    
    if number:
        label = f"Ch.{number}"
        if vol:
            label = f"V{vol} {label}"
        return label
    return title or "Chapter"


def format_manga_detail(detail: MangaDetail, max_length: int = 1000) -> str:
    """Format manga detail for display."""
    genres = ", ".join(detail.genres) if detail.genres else "Unknown"
    year = detail.year or "Unknown"
    rating = detail.rating or "N/A"
    chapters = detail.chapters_count or "Unknown"
    
    header = (
        f"{detail.title}\n"
        f"Year: {year}\n"
        f"Genres: {genres}\n"
        f"Chapters: {chapters}\n"
        f"Rating: {rating}\n\n"
    )
    
    # Truncate description to fit Telegram's 1024 char limit for captions
    available_length = max_length - len(header)
    description = detail.description or ""
    if len(description) > available_length:
        description = description[:available_length - 3] + "..."
    
    return header + description


def download_image(url: str) -> Image.Image | None:
    """Download image from URL and return PIL Image."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://desu.uno/",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        }
        response = requests.get(url, timeout=30, headers=headers)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content)).convert("RGB")
    except Exception as e:
        log_error("image_download", str(e), f"url={url[:100]}")
        return None


def create_pdf_from_images(images: list[Image.Image], output_path: str) -> None:
    """Create PDF from list of PIL Images."""
    if not images:
        return
    images[0].save(output_path, save_all=True, append_images=images[1:], format="PDF")


def create_zip_from_images(images: list[Image.Image], output_path: str) -> None:
    """Create ZIP archive from list of PIL Images."""
    if not images:
        return
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i, img in enumerate(images, 1):
            img_buffer = io.BytesIO()
            img.save(img_buffer, format="JPEG", quality=95)
            img_buffer.seek(0)
            zf.writestr(f"page_{i:03d}.jpg", img_buffer.read())


async def download_chapter_as_pdf(pages: list[dict], chapter_name: str) -> str | None:
    """Download all pages and create PDF. Returns path to PDF file."""
    images: list[Image.Image] = []
    failed_pages = 0
    
    for page in pages:
        url = page.get("img") or page.get("image") or page.get("url")
        if not url:
            continue
        img = await run_sync(download_image, url)
        if img:
            images.append(img)
        else:
            failed_pages += 1
    
    if failed_pages > 0:
        log_error("pdf_download", f"Failed to download {failed_pages} pages", f"chapter={chapter_name}")
    
    if not images:
        log_error("pdf_create", "No images downloaded", f"chapter={chapter_name}")
        return None
    
    temp_dir = tempfile.gettempdir()
    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in chapter_name)
    pdf_path = os.path.join(temp_dir, f"{safe_name}.pdf")
    
    try:
        await run_sync(create_pdf_from_images, images, pdf_path)
    except Exception as e:
        log_error("pdf_create", str(e), f"chapter={chapter_name}")
        return None
    
    return pdf_path


async def download_chapter_as_zip(pages: list[dict], chapter_name: str) -> str | None:
    """Download all pages and create ZIP. Returns path to ZIP file."""
    images: list[Image.Image] = []
    failed_pages = 0
    
    for page in pages:
        url = page.get("img") or page.get("image") or page.get("url")
        if not url:
            continue
        img = await run_sync(download_image, url)
        if img:
            images.append(img)
        else:
            failed_pages += 1
    
    if failed_pages > 0:
        log_error("zip_download", f"Failed to download {failed_pages} pages", f"chapter={chapter_name}")
    
    if not images:
        log_error("zip_create", "No images downloaded", f"chapter={chapter_name}")
        return None
    
    temp_dir = tempfile.gettempdir()
    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in chapter_name)
    zip_path = os.path.join(temp_dir, f"{safe_name}.zip")
    
    try:
        await run_sync(create_zip_from_images, images, zip_path)
    except Exception as e:
        log_error("zip_create", str(e), f"chapter={chapter_name}")
        return None
    
    return zip_path
