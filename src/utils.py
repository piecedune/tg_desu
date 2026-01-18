"""Utility functions for the bot."""
from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile
import zipfile
from typing import Callable, Awaitable

import requests
from PIL import Image
from aiogram.types import CallbackQuery

from desu_client import MangaDetail

logger = logging.getLogger(__name__)

# Type for progress callback: async function(current, total, status_text)
ProgressCallback = Callable[[int, int, str], Awaitable[None]]


async def safe_callback_answer(callback: CallbackQuery, text: str | None = None, show_alert: bool = False) -> None:
    """Safely answer callback query, ignoring timeout errors."""
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except Exception:
        pass  # Query expired or already answered


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


def resize_image_for_telegram(img: Image.Image, max_dimension: int = 4096) -> Image.Image:
    """Resize image if it exceeds Telegram's limits (max 4096px on any side)."""
    width, height = img.size
    
    if width <= max_dimension and height <= max_dimension:
        return img
    
    # Calculate new size keeping aspect ratio
    if width > height:
        new_width = max_dimension
        new_height = int(height * max_dimension / width)
    else:
        new_height = max_dimension
        new_width = int(width * max_dimension / height)
    
    return img.resize((new_width, new_height), Image.Resampling.LANCZOS)


def compress_image_for_volume(img: Image.Image, max_dimension: int = 1800, quality: int = 75) -> Image.Image:
    """Compress image for volume downloads to reduce file size.
    
    Args:
        img: PIL Image
        max_dimension: Max width/height (default 1800px - good for reading)
        quality: Not used directly here, but indicates target quality level
    """
    width, height = img.size
    
    # Only resize if larger than max_dimension
    if width > max_dimension or height > max_dimension:
        if width > height:
            new_width = max_dimension
            new_height = int(height * max_dimension / width)
        else:
            new_height = max_dimension
            new_width = int(width * max_dimension / height)
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    return img


def create_pdf_from_images(images: list[Image.Image], output_path: str, quality: int = 85) -> None:
    """Create PDF from list of PIL Images."""
    if not images:
        return
    # Convert to RGB if needed and save
    rgb_images = [img.convert("RGB") if img.mode != "RGB" else img for img in images]
    rgb_images[0].save(output_path, save_all=True, append_images=rgb_images[1:], format="PDF", quality=quality)


def create_cbz_from_images(images: list[Image.Image], output_path: str, quality: int = 85) -> None:
    """Create CBZ (Comic Book ZIP) archive from list of PIL Images."""
    if not images:
        return
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i, img in enumerate(images, 1):
            img_buffer = io.BytesIO()
            img.save(img_buffer, format="JPEG", quality=quality)
            img_buffer.seek(0)
            zf.writestr(f"page_{i:03d}.jpg", img_buffer.read())


async def download_chapter_as_pdf(
    pages: list[dict], 
    chapter_name: str,
    progress_callback: ProgressCallback | None = None
) -> str | None:
    """Download all pages and create PDF. Returns path to PDF file."""
    images: list[Image.Image] = []
    failed_pages = 0
    total = len(pages)
    
    for i, page in enumerate(pages):
        url = page.get("img") or page.get("image") or page.get("url")
        if not url:
            continue
        
        # Report progress
        if progress_callback and i % 3 == 0:  # Update every 3 pages to avoid spam
            percent = int((i / total) * 100)
            logger.info(f"[{chapter_name}] Downloading: {percent}% ({i}/{total})")
            try:
                await progress_callback(i, total, f"⏳ Скачивание: {percent}% ({i}/{total})")
            except Exception:
                pass
        
        img = await run_sync(download_image, url)
        if img:
            images.append(img)
        else:
            failed_pages += 1
    
    if progress_callback:
        logger.info(f"[{chapter_name}] Creating PDF...")
        try:
            await progress_callback(total, total, "📄 Создаю PDF...")
        except Exception:
            pass
    
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
    
    logger.info(f"[{chapter_name}] PDF created: {os.path.getsize(pdf_path) / (1024*1024):.1f} MB")
    return pdf_path


async def download_chapter_as_cbz(
    pages: list[dict], 
    chapter_name: str,
    progress_callback: ProgressCallback | None = None
) -> str | None:
    """Download all pages and create CBZ (Comic Book ZIP). Returns path to CBZ file."""
    images: list[Image.Image] = []
    failed_pages = 0
    total = len(pages)
    
    for i, page in enumerate(pages):
        url = page.get("img") or page.get("image") or page.get("url")
        if not url:
            continue
        
        # Report progress
        if progress_callback and i % 3 == 0:
            percent = int((i / total) * 100)
            logger.info(f"[{chapter_name}] Downloading: {percent}% ({i}/{total})")
            try:
                await progress_callback(i, total, f"⏳ Скачивание: {percent}% ({i}/{total})")
            except Exception:
                pass
        
        img = await run_sync(download_image, url)
        if img:
            images.append(img)
        else:
            failed_pages += 1
    
    if progress_callback:
        logger.info(f"[{chapter_name}] Creating CBZ...")
        try:
            await progress_callback(total, total, "📦 Создаю CBZ...")
        except Exception:
            pass
    
    if failed_pages > 0:
        log_error("cbz_download", f"Failed to download {failed_pages} pages", f"chapter={chapter_name}")
    
    if not images:
        log_error("cbz_create", "No images downloaded", f"chapter={chapter_name}")
        return None
    
    temp_dir = tempfile.gettempdir()
    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in chapter_name)
    cbz_path = os.path.join(temp_dir, f"{safe_name}.cbz")
    
    try:
        await run_sync(create_cbz_from_images, images, cbz_path)
    except Exception as e:
        log_error("cbz_create", str(e), f"chapter={chapter_name}")
        return None
    
    return cbz_path


# ============== Volume Download Functions ==============

# Telegram file size limit for bots (50 MB)
MAX_TELEGRAM_FILE_SIZE = 50 * 1024 * 1024


async def download_volume_as_pdf(
    pages: list[dict], 
    volume_name: str, 
    compress: bool = False,
    max_dimension: int = 1800,
    quality: int = 75,
    progress_callback: ProgressCallback | None = None
) -> str | None:
    """Download all pages from volume and create PDF. Returns path to PDF file.
    
    Args:
        pages: List of page dicts (with 'img'/'image'/'url' keys) from all chapters in volume
        volume_name: Name for the volume file
        compress: If True, compress images to reduce file size
        max_dimension: Max image dimension when compressing
        quality: JPEG quality when compressing (1-100)
        progress_callback: Async callback for progress updates
    """
    images: list[Image.Image] = []
    failed_pages = 0
    total = len(pages)
    
    for i, page in enumerate(pages):
        # Handle both dict and string page formats
        if isinstance(page, dict):
            url = page.get("img") or page.get("image") or page.get("url")
        else:
            url = page
        
        if not url:
            continue
        
        # Report progress
        if progress_callback and i % 5 == 0:  # Update every 5 pages for volumes
            percent = int((i / total) * 100)
            logger.info(f"[{volume_name}] Downloading: {percent}% ({i}/{total})")
            try:
                await progress_callback(i, total, f"⏳ Скачивание: {percent}% ({i}/{total})")
            except Exception:
                pass
            
        img = await run_sync(download_image, url)
        if img:
            if compress:
                img = compress_image_for_volume(img, max_dimension)
            images.append(img)
        else:
            failed_pages += 1
    
    if progress_callback:
        logger.info(f"[{volume_name}] Creating PDF...")
        try:
            await progress_callback(total, total, "📄 Создаю PDF...")
        except Exception:
            pass
    
    if failed_pages > 0:
        log_error("volume_pdf_download", f"Failed to download {failed_pages} pages", f"volume={volume_name}")
    
    if not images:
        log_error("volume_pdf_create", "No images downloaded", f"volume={volume_name}")
        return None
    
    temp_dir = tempfile.gettempdir()
    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in volume_name)
    pdf_path = os.path.join(temp_dir, f"{safe_name}.pdf")
    
    img_quality = quality if compress else 85
    
    try:
        await run_sync(create_pdf_from_images, images, pdf_path, img_quality)
    except Exception as e:
        log_error("volume_pdf_create", str(e), f"volume={volume_name}")
        return None
    
    return pdf_path


def create_cbz_with_chapters(
    pages_with_info: list[dict], 
    output_path: str, 
    quality: int = 85,
    compress: bool = False,
    max_dimension: int = 1800
) -> None:
    """Create CBZ archive with chapter organization.
    
    Args:
        pages_with_info: List of dicts with 'url' and 'chapter' keys
        output_path: Path for output CBZ file
        quality: JPEG quality (1-100)
        compress: If True, resize large images
        max_dimension: Max image dimension when compressing
    """
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        page_count_per_chapter = {}
        
        for page_info in pages_with_info:
            url = page_info.get("url")
            chapter = page_info.get("chapter", "unknown")
            
            if not url:
                continue
                
            img = download_image(url)
            if not img:
                continue
            
            # Compress if needed
            if compress:
                img = compress_image_for_volume(img, max_dimension)
            
            # Track page number per chapter
            if chapter not in page_count_per_chapter:
                page_count_per_chapter[chapter] = 0
            page_count_per_chapter[chapter] += 1
            page_num = page_count_per_chapter[chapter]
            
            # Create safe chapter name for folder
            safe_chapter = "".join(c if c.isalnum() or c in "._- " else "_" for c in str(chapter))
            
            img_buffer = io.BytesIO()
            img.save(img_buffer, format="JPEG", quality=quality)
            img_buffer.seek(0)
            zf.writestr(f"{safe_chapter}/page_{page_num:03d}.jpg", img_buffer.read())


async def download_volume_as_cbz(
    pages_with_info: list[dict], 
    volume_name: str,
    compress: bool = False,
    max_dimension: int = 1800,
    quality: int = 75,
    progress_callback: ProgressCallback | None = None
) -> str | None:
    """Download all pages from volume and create CBZ with chapter folders.
    
    Args:
        pages_with_info: List of dicts with 'url' and 'chapter' keys
        volume_name: Name for the volume file
        compress: If True, compress images to reduce file size
        max_dimension: Max image dimension when compressing
        quality: JPEG quality when compressing (1-100)
        progress_callback: Async callback for progress updates
    """
    if not pages_with_info:
        log_error("volume_cbz_create", "No pages provided", f"volume={volume_name}")
        return None
    
    temp_dir = tempfile.gettempdir()
    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in volume_name)
    cbz_path = os.path.join(temp_dir, f"{safe_name}.cbz")
    
    img_quality = quality if compress else 85
    total = len(pages_with_info)
    
    try:
        # Download images with progress tracking
        downloaded_images: list[tuple[str, int, Image.Image]] = []  # (chapter, page_num, image)
        page_count_per_chapter: dict[str, int] = {}
        
        for i, page_info in enumerate(pages_with_info):
            url = page_info.get("url")
            chapter = page_info.get("chapter", "unknown")
            
            if not url:
                continue
            
            # Report progress
            if progress_callback and i % 5 == 0:
                percent = int((i / total) * 100)
                logger.info(f"[{volume_name}] Downloading: {percent}% ({i}/{total})")
                try:
                    await progress_callback(i, total, f"⏳ Скачивание: {percent}% ({i}/{total})")
                except Exception:
                    pass
            
            img = await run_sync(download_image, url)
            if not img:
                continue
            
            if compress:
                img = compress_image_for_volume(img, max_dimension)
            
            # Track page number per chapter
            if chapter not in page_count_per_chapter:
                page_count_per_chapter[chapter] = 0
            page_count_per_chapter[chapter] += 1
            page_num = page_count_per_chapter[chapter]
            
            downloaded_images.append((str(chapter), page_num, img))
        
        if progress_callback:
            logger.info(f"[{volume_name}] Creating CBZ...")
            try:
                await progress_callback(total, total, "📦 Создаю CBZ...")
            except Exception:
                pass
        
        # Create CBZ from downloaded images
        with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for chapter, page_num, img in downloaded_images:
                safe_chapter = "".join(c if c.isalnum() or c in "._- " else "_" for c in chapter)
                img_buffer = io.BytesIO()
                img.save(img_buffer, format="JPEG", quality=img_quality)
                img_buffer.seek(0)
                zf.writestr(f"{safe_chapter}/page_{page_num:03d}.jpg", img_buffer.read())
                
    except Exception as e:
        log_error("volume_cbz_create", str(e), f"volume={volume_name}")
        return None
    
    # Check if file was created and has content
    if not os.path.exists(cbz_path) or os.path.getsize(cbz_path) == 0:
        log_error("volume_cbz_create", "Empty CBZ file", f"volume={volume_name}")
        return None
    
    logger.info(f"[{volume_name}] CBZ created: {os.path.getsize(cbz_path) / (1024*1024):.1f} MB")
    return cbz_path
