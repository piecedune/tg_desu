"""Manga handlers: details, chapters, favorites, downloads."""
from __future__ import annotations

import os
import time
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
from keyboards import build_chapter_keyboard, build_format_keyboard, build_manga_buttons
from states import ChapterStates
from dependencies import get_client, get_favorites
from utils import (
    run_sync,
    chapter_title,
    format_manga_detail,
    download_chapter_as_pdf,
    download_chapter_as_cbz,
    safe_callback_answer,
)

router = Router()
logger = logging.getLogger(__name__)


def create_progress_callback(message):
    """Create a progress callback that edits the message with progress.
    
    Args:
        message: aiogram Message object to edit
    """
    last_update_time = [0.0]  # Use list to allow mutation in closure
    
    async def progress_callback(current: int, total: int, text: str) -> None:
        # Throttle updates to max once per 2 seconds
        now = time.time()
        if now - last_update_time[0] < 2.0 and current < total:
            return
        last_update_time[0] = now
        
        try:
            await message.edit_text(text)
        except Exception:
            pass  # Ignore if message can't be edited (deleted, etc)
    
    return progress_callback


@router.callback_query(F.data.startswith("manga:"))
async def show_manga(callback: CallbackQuery) -> None:
    """Show manga details."""
    await safe_callback_answer(callback)
    if not callback.message:
        return
    manga_id = int(callback.data.split(":")[1])
    client = get_client()
    store = get_favorites()
    user_id = callback.from_user.id
    
    try:
        await callback.message.edit_text("⏳ Загрузка...")
    except Exception:
        pass

    detail = await run_sync(client.get_manga_detail, manga_id)
    is_favorite = store.has(user_id, manga_id)
    
    # Add to viewing history
    store.add_manga_to_history(user_id, manga_id, detail.title, detail.cover)

    description = format_manga_detail(detail)
    reply_markup = build_manga_buttons(manga_id, is_favorite, config.BOT_USERNAME)

    if detail.cover:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer_photo(detail.cover, caption=description, reply_markup=reply_markup)
    else:
        try:
            await callback.message.edit_text(description, reply_markup=reply_markup)
        except Exception:
            await callback.message.answer(description, reply_markup=reply_markup)


@router.callback_query(F.data.startswith("fav:"))
async def handle_favorite(callback: CallbackQuery) -> None:
    """Add/remove manga from favorites."""
    if not callback.message:
        await safe_callback_answer(callback)
        return
    action, manga_id_text = callback.data.split(":")[1:]
    manga_id = int(manga_id_text)
    store = get_favorites()
    client = get_client()
    user_id = callback.from_user.id

    if action == "add":
        detail = await run_sync(client.get_manga_detail, manga_id)
        store.add(user_id, manga_id, detail.title, detail.cover)
        is_favorite = True
        await callback.answer("✅ Добавлено в избранное!")
    else:
        store.remove(user_id, manga_id)
        is_favorite = False
        await callback.answer("❌ Удалено из избранного!")
    
    new_markup = build_manga_buttons(manga_id, is_favorite, config.BOT_USERNAME)
    try:
        await callback.message.edit_reply_markup(reply_markup=new_markup)
    except Exception:
        pass


@router.callback_query(F.data.startswith("chapters:"))
async def show_chapters(callback: CallbackQuery) -> None:
    """Show chapter list with read chapters marked."""
    await safe_callback_answer(callback)
    if not callback.message:
        return
    _, manga_id_text, page_text = callback.data.split(":")
    manga_id = int(manga_id_text)
    page = int(page_text)

    client = get_client()
    store = get_favorites()
    
    chapters = await run_sync(client.get_manga_chapters, manga_id)
    if not chapters:
        await callback.message.edit_text("Нет доступных глав.")
        return

    # Get read chapters for this user
    read_chapters = store.get_read_chapters(callback.from_user.id, manga_id)
    read_chapter_ids = set(read_chapters)

    keyboard = build_chapter_keyboard(chapters, manga_id, page, read_chapter_ids=read_chapter_ids)
    try:
        await callback.message.edit_text("Выберите главу (✅ = прочитано):", reply_markup=keyboard)
    except Exception:
        await callback.message.answer("Выберите главу (✅ = прочитано):", reply_markup=keyboard)


@router.callback_query(F.data.startswith("goto_ch:"))
async def prompt_chapter_number(callback: CallbackQuery, state: FSMContext) -> None:
    """Prompt user to enter chapter number."""
    await safe_callback_answer(callback)
    if not callback.message:
        return
    manga_id = int(callback.data.split(":")[1])
    
    await state.set_state(ChapterStates.waiting_chapter_number)
    await state.update_data(manga_id=manga_id)
    
    client = get_client()
    chapters = await run_sync(client.get_manga_chapters, manga_id)
    
    ch_numbers = []
    for ch in chapters:
        num = ch.get("ch") or ch.get("chapter") or ch.get("number")
        if num:
            try:
                ch_numbers.append(float(num))
            except (ValueError, TypeError):
                pass
    
    hint = f"Available chapters: {min(ch_numbers)} - {max(ch_numbers)}" if ch_numbers else ""
    
    try:
        await callback.message.edit_text(
            f"🔢 Enter chapter number:\n{hint}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Cancel", callback_data=f"chapters:{manga_id}:1")]
            ])
        )
    except Exception:
        await callback.message.answer(f"🔢 Enter chapter number:\n{hint}")


@router.message(ChapterStates.waiting_chapter_number)
async def handle_chapter_number_input(message: Message, state: FSMContext) -> None:
    """Handle chapter number input."""
    data = await state.get_data()
    manga_id = data.get("manga_id")
    await state.clear()
    
    if not manga_id:
        await message.answer("Something went wrong. Please try again.")
        return
    
    chapter_input = message.text.strip()
    
    client = get_client()
    chapters = await run_sync(client.get_manga_chapters, manga_id)
    
    found_chapter = None
    for ch in chapters:
        ch_num = ch.get("ch") or ch.get("chapter") or ch.get("number")
        if ch_num and str(ch_num) == chapter_input:
            found_chapter = ch
            break
    
    if not found_chapter:
        for ch in chapters:
            ch_num = ch.get("ch") or ch.get("chapter") or ch.get("number")
            if ch_num and str(ch_num).startswith(chapter_input):
                found_chapter = ch
                break
    
    if not found_chapter:
        await message.answer(
            f"❌ Chapter {chapter_input} not found.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📚 Back to chapters", callback_data=f"chapters:{manga_id}:1")]
            ])
        )
        return
    
    chapter_id = found_chapter.get("id")
    ch_name = chapter_title(found_chapter)
    
    await message.answer(
        f"📚 {ch_name}\n\nChoose download format:",
        reply_markup=build_format_keyboard(manga_id, chapter_id)
    )


@router.callback_query(F.data.startswith("chapter:"))
async def show_chapter_options(callback: CallbackQuery) -> None:
    """Show format choice for chapter download or use default format."""
    await safe_callback_answer(callback)
    if not callback.message:
        return
    _, manga_id_text, chapter_id_text = callback.data.split(":")
    manga_id = int(manga_id_text)
    chapter_id = int(chapter_id_text)
    
    store = get_favorites()
    user_id = callback.from_user.id
    user_format = store.get_download_format(user_id)

    client = get_client()
    chapters = await run_sync(client.get_manga_chapters, manga_id)
    chapter_info = next((ch for ch in chapters if ch.get("id") == chapter_id), {})
    ch_name = chapter_title(chapter_info) or f"Chapter_{chapter_id}"
    
    try:
        await callback.message.edit_text(
            f"📚 {ch_name}\n\nChoose download format (⭐ = default):",
            reply_markup=build_format_keyboard(manga_id, chapter_id, user_format)
        )
    except Exception:
        await callback.message.answer(
            f"📚 {ch_name}\n\nChoose download format (⭐ = default):",
            reply_markup=build_format_keyboard(manga_id, chapter_id, user_format)
        )


@router.callback_query(F.data.startswith("dl_pdf:"))
async def download_pdf(callback: CallbackQuery) -> None:
    """Download chapter as PDF."""
    await safe_callback_answer(callback)
    if not callback.message:
        return
    _, manga_id_text, chapter_id_text = callback.data.split(":")
    manga_id = int(manga_id_text)
    chapter_id = int(chapter_id_text)

    store = get_favorites()
    client = get_client()
    
    chapters = await run_sync(client.get_manga_chapters, manga_id)
    chapter_info = next((ch for ch in chapters if ch.get("id") == chapter_id), {})
    ch_name = chapter_title(chapter_info) or f"Chapter_{chapter_id}"
    
    detail = await run_sync(client.get_manga_detail, manga_id)
    manga_title = detail.title if detail else "Manga"
    file_name = f"{manga_title} - {ch_name}.pdf"
    
    # Check cache
    cached_file_id = store.get_cached_file(manga_id, chapter_id, "pdf")
    if cached_file_id:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer_document(cached_file_id, caption=f"📕 {manga_title} - {ch_name}")
        store.mark_chapter_read(callback.from_user.id, manga_id, chapter_id, ch_name)
        return
    
    try:
        await callback.message.edit_text(f"⏳ Downloading {ch_name} as PDF... Please wait.")
    except Exception:
        pass
    
    pages = await run_sync(client.get_chapter_pages, manga_id, chapter_id)
    if not pages:
        try:
            await callback.message.edit_text("No pages found for this chapter.")
        except Exception:
            pass
        return
    
    # Create progress callback
    progress_cb = create_progress_callback(callback.message)
    pdf_path = await download_chapter_as_pdf(pages, f"{manga_title} - {ch_name}", progress_callback=progress_cb)
    
    if not pdf_path or not os.path.exists(pdf_path):
        try:
            await callback.message.edit_text("❌ Failed to create PDF.")
        except Exception:
            pass
        return
    
    # Check file size
    file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
    use_telethon = False
    
    if file_size_mb > 50:
        from telethon_client import is_telethon_available
        if is_telethon_available() and file_size_mb <= 2000:
            use_telethon = True
            try:
                await callback.message.edit_text(
                    f"⏳ Глава большая ({file_size_mb:.1f} MB).\n"
                    "Отправляю через Telethon..."
                )
            except Exception:
                pass
        else:
            os.remove(pdf_path)
            try:
                await callback.message.edit_text(
                    f"❌ Глава слишком большая ({file_size_mb:.1f} MB).\n"
                    "Лимит Telegram Bot API: 50 MB.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="◀ Назад", callback_data=f"chapters:{manga_id}:1")]
                    ])
                )
            except Exception:
                pass
            return
    
    try:
        if use_telethon:
            from telethon_client import send_large_file
            
            # Create a new message for upload progress (don't delete yet)
            progress_msg = await callback.message.edit_text("📤 Загрузка: 0%...")
            upload_progress_cb = create_progress_callback(progress_msg)
            
            sent, file_id = await send_large_file(
                chat_id=callback.from_user.id,
                file_path=pdf_path,
                caption=f"📕 {manga_title} - {ch_name}",
                message_callback=upload_progress_cb
            )
            
            # Delete progress message after upload
            try:
                await progress_msg.delete()
            except Exception:
                pass
            
            if not sent:
                await callback.message.answer("❌ Не удалось отправить.")
                return
            
            if file_id:
                store.cache_file(manga_id, chapter_id, "pdf", file_id, file_name)
        else:
            pdf_file = FSInputFile(pdf_path, filename=file_name)
            try:
                await callback.message.delete()
            except Exception:
                pass
            sent_msg = await callback.message.answer_document(pdf_file, caption=f"📕 {manga_title} - {ch_name}")
            
            if sent_msg.document:
                store.cache_file(manga_id, chapter_id, "pdf", sent_msg.document.file_id, file_name)
        
        store.mark_chapter_read(callback.from_user.id, manga_id, chapter_id, ch_name)
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)


@router.callback_query(F.data.startswith("dl_zip:"))
async def download_zip(callback: CallbackQuery) -> None:
    """Download chapter as CBZ (Comic Book ZIP)."""
    await safe_callback_answer(callback)
    if not callback.message:
        return
    _, manga_id_text, chapter_id_text = callback.data.split(":")
    manga_id = int(manga_id_text)
    chapter_id = int(chapter_id_text)

    store = get_favorites()
    client = get_client()
    
    chapters = await run_sync(client.get_manga_chapters, manga_id)
    chapter_info = next((ch for ch in chapters if ch.get("id") == chapter_id), {})
    ch_name = chapter_title(chapter_info) or f"Chapter_{chapter_id}"
    
    detail = await run_sync(client.get_manga_detail, manga_id)
    manga_title = detail.title if detail else "Manga"
    file_name = f"{manga_title} - {ch_name}.cbz"
    
    # Check cache
    cached_file_id = store.get_cached_file(manga_id, chapter_id, "cbz")
    if cached_file_id:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer_document(cached_file_id, caption=f"📦 {manga_title} - {ch_name}")
        store.mark_chapter_read(callback.from_user.id, manga_id, chapter_id, ch_name)
        return
    
    try:
        await callback.message.edit_text(f"⏳ Скачиваю {ch_name} как CBZ...")
    except Exception:
        pass
    
    pages = await run_sync(client.get_chapter_pages, manga_id, chapter_id)
    if not pages:
        try:
            await callback.message.edit_text("Страницы не найдены.")
        except Exception:
            pass
        return
    
    # Create progress callback
    progress_cb = create_progress_callback(callback.message)
    cbz_path = await download_chapter_as_cbz(pages, f"{manga_title} - {ch_name}", progress_callback=progress_cb)
    
    if not cbz_path or not os.path.exists(cbz_path):
        try:
            await callback.message.edit_text("❌ Не удалось создать CBZ.")
        except Exception:
            pass
        return
    
    # Check file size
    file_size_mb = os.path.getsize(cbz_path) / (1024 * 1024)
    use_telethon = False
    
    if file_size_mb > 50:
        from telethon_client import is_telethon_available
        if is_telethon_available() and file_size_mb <= 2000:
            use_telethon = True
            try:
                await callback.message.edit_text(
                    f"⏳ Глава большая ({file_size_mb:.1f} MB).\n"
                    "Отправляю через Telethon..."
                )
            except Exception:
                pass
        else:
            os.remove(cbz_path)
            try:
                await callback.message.edit_text(
                    f"❌ Глава слишком большая ({file_size_mb:.1f} MB).\n"
                    "Лимит Telegram Bot API: 50 MB.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="◀ Назад", callback_data=f"chapters:{manga_id}:1")]
                    ])
                )
            except Exception:
                pass
            return
    
    try:
        if use_telethon:
            from telethon_client import send_large_file
            
            # Create a new message for upload progress
            progress_msg = await callback.message.edit_text("📤 Загрузка: 0%...")
            upload_progress_cb = create_progress_callback(progress_msg)
            
            sent, file_id = await send_large_file(
                chat_id=callback.from_user.id,
                file_path=cbz_path,
                caption=f"📦 {manga_title} - {ch_name}",
                message_callback=upload_progress_cb
            )
            
            # Delete progress message after upload
            try:
                await progress_msg.delete()
            except Exception:
                pass
            
            if not sent:
                await callback.message.answer("❌ Не удалось отправить.")
                return
            
            if file_id:
                store.cache_file(manga_id, chapter_id, "cbz", file_id, file_name)
        else:
            cbz_file = FSInputFile(cbz_path, filename=file_name)
            try:
                await callback.message.delete()
            except Exception:
                pass
            sent_msg = await callback.message.answer_document(cbz_file, caption=f"📦 {manga_title} - {ch_name}")
            
            if sent_msg.document:
                store.cache_file(manga_id, chapter_id, "cbz", sent_msg.document.file_id, file_name)
        
        store.mark_chapter_read(callback.from_user.id, manga_id, chapter_id, ch_name)
    finally:
        if os.path.exists(cbz_path):
            os.remove(cbz_path)


@router.callback_query(F.data.startswith("read_album:"))
async def read_album(callback: CallbackQuery) -> None:
    """Read chapter as album (media group) - sends images directly to chat."""
    from aiogram.types import InputMediaPhoto
    
    await safe_callback_answer(callback)
    if not callback.message:
        return
    _, manga_id_text, chapter_id_text = callback.data.split(":")
    manga_id = int(manga_id_text)
    chapter_id = int(chapter_id_text)

    store = get_favorites()
    client = get_client()
    
    chapters = await run_sync(client.get_manga_chapters, manga_id)
    chapter_info = next((ch for ch in chapters if ch.get("id") == chapter_id), {})
    ch_name = chapter_title(chapter_info) or f"Chapter_{chapter_id}"
    
    detail = await run_sync(client.get_manga_detail, manga_id)
    manga_title = detail.title if detail else "Manga"
    
    # Check cache first
    cached_album = store.get_cached_album(manga_id, chapter_id)
    if cached_album:
        try:
            await callback.message.edit_text(f"📖 <b>{manga_title}</b>\n📚 {ch_name}\n\n⚡ Отправляю из кэша...", parse_mode="HTML")
        except Exception:
            pass
        
        try:
            await callback.message.delete()
        except Exception:
            pass
        
        # Send cached album
        for batch_file_ids in cached_album:
            media_group = [InputMediaPhoto(media=file_id) for file_id in batch_file_ids]
            try:
                await callback.message.answer_media_group(media_group)
            except Exception as e:
                store.log_error("album_cache_send", str(e), f"manga_id={manga_id}, chapter_id={chapter_id}")
        
        # Mark as read
        store.mark_chapter_read(callback.from_user.id, manga_id, chapter_id, ch_name)
        
        nav_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📖 К списку глав", callback_data=f"chapters:{manga_id}:1")]
        ])
        await callback.message.answer("✅ Глава загружена", reply_markup=nav_keyboard)
        return
    
    try:
        await callback.message.edit_text(f"⏳ Загружаю {ch_name}...")
    except Exception:
        pass
    
    try:
        pages = await run_sync(client.get_chapter_pages, manga_id, chapter_id)
    except Exception as e:
        store.log_error("album_read", str(e), f"manga_id={manga_id}, chapter_id={chapter_id}")
        await callback.message.edit_text("❌ Не удалось загрузить страницы.")
        return
    
    if not pages:
        await callback.message.edit_text("❌ Страницы не найдены.")
        return
    
    # Extract URLs from page dicts
    page_urls = []
    for page in pages:
        url = page.get("img") or page.get("image") or page.get("url")
        if url:
            page_urls.append(url)
    
    if not page_urls:
        await callback.message.edit_text("❌ Не удалось получить ссылки на страницы.")
        return
    
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    # Send pages in groups of 10 (Telegram limit for media groups)
    await callback.message.answer(f"📖 <b>{manga_title}</b>\n📚 {ch_name}\n\n📄 Страниц: {len(page_urls)}\n⏳ Загрузка...", parse_mode="HTML")
    
    # Download and send images (Telegram can't fetch from desu.uno directly due to headers)
    from utils import download_image
    from aiogram.types import BufferedInputFile
    import io
    
    all_batches_success = True  # Track if all batches sent successfully
    
    for batch_index, i in enumerate(range(0, len(page_urls), 10)):
        batch_urls = page_urls[i:i + 10]
        media_group = []
        download_failed = False
        
        for url in batch_urls:
            try:
                img = await run_sync(download_image, url)
                if img:
                    # Resize if too large for Telegram (max 4096px)
                    from utils import resize_image_for_telegram
                    img = resize_image_for_telegram(img)
                    
                    img_buffer = io.BytesIO()
                    img.save(img_buffer, format="JPEG", quality=85)
                    img_buffer.seek(0)
                    media_group.append(InputMediaPhoto(
                        media=BufferedInputFile(img_buffer.read(), filename="page.jpg")
                    ))
                else:
                    download_failed = True
            except Exception as e:
                store.log_error("album_download", str(e), f"url={url[:50]}")
                download_failed = True
                continue
        
        # Only send and cache if we have images AND all downloaded successfully
        if media_group:
            try:
                sent_messages = await callback.message.answer_media_group(media_group)
                # Only cache if ALL images in batch downloaded and sent successfully
                if not download_failed and len(sent_messages) == len(batch_urls):
                    file_ids = [msg.photo[-1].file_id for msg in sent_messages if msg.photo]
                    if len(file_ids) == len(batch_urls):
                        store.cache_album_batch(manga_id, chapter_id, batch_index, file_ids)
                    else:
                        all_batches_success = False
                else:
                    all_batches_success = False
            except Exception as e:
                store.log_error("album_send", str(e), f"batch={i}-{i+len(batch_urls)}")
                await callback.message.answer(f"⚠️ Ошибка при отправке страниц {i+1}-{i+len(batch_urls)}")
                all_batches_success = False
        else:
            # No images in batch - all downloads failed
            await callback.message.answer(f"⚠️ Ошибка при отправке страниц {i+1}-{i+len(batch_urls)}")
            all_batches_success = False
    
    # If any batch failed, clear partial cache to force re-download next time
    if not all_batches_success:
        store.clear_album_cache_for_chapter(manga_id, chapter_id)
    
    # Mark as read
    store.mark_chapter_read(callback.from_user.id, manga_id, chapter_id, ch_name)
    
    # Navigation buttons
    nav_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 К списку глав", callback_data=f"chapters:{manga_id}:1")]
    ])
    await callback.message.answer("✅ Глава загружена", reply_markup=nav_keyboard)


# ============== Volume Download Handlers ==============

@router.callback_query(F.data.startswith("volumes:"))
async def show_volumes(callback: CallbackQuery) -> None:
    """Show list of volumes available for download."""
    from keyboards import build_volume_list_keyboard
    
    await safe_callback_answer(callback)
    if not callback.message:
        return
    manga_id = int(callback.data.split(":")[1])
    
    client = get_client()
    chapters = await run_sync(client.get_manga_chapters, manga_id)
    
    if not chapters:
        try:
            await callback.message.edit_text("Нет доступных глав.")
        except Exception:
            pass
        return
    
    # Extract unique volumes
    volumes_set = set()
    for ch in chapters:
        vol = ch.get("vol")
        if vol is not None:
            volumes_set.add(vol)
    
    if not volumes_set:
        try:
            await callback.message.edit_text(
                "❌ Тома не найдены. Возможно, главы не разбиты по томам.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀ Назад", callback_data=f"chapters:{manga_id}:1")]
                ])
            )
        except Exception:
            pass
        return
    
    # Sort volumes
    try:
        volumes = sorted(volumes_set, key=lambda x: float(x) if x else 0)
    except (ValueError, TypeError):
        volumes = sorted(volumes_set, key=str)
    
    keyboard = build_volume_list_keyboard(volumes, manga_id)
    try:
        await callback.message.edit_text("📚 Выберите том для скачивания:", reply_markup=keyboard)
    except Exception:
        await callback.message.answer("📚 Выберите том для скачивания:", reply_markup=keyboard)


@router.callback_query(F.data.startswith("vol_format:"))
async def show_volume_format(callback: CallbackQuery) -> None:
    """Show format selection for volume download."""
    from keyboards import build_volume_format_keyboard
    
    await safe_callback_answer(callback)
    if not callback.message:
        return
    _, manga_id_text, volume = callback.data.split(":")
    manga_id = int(manga_id_text)
    
    client = get_client()
    chapters = await run_sync(client.get_manga_chapters, manga_id)
    
    # Count chapters in this volume
    vol_chapters = [ch for ch in chapters if str(ch.get("vol")) == volume]
    chapter_count = len(vol_chapters)
    
    keyboard = build_volume_format_keyboard(manga_id, volume)
    try:
        await callback.message.edit_text(
            f"📚 Том {volume}\n"
            f"📖 Глав: {chapter_count}\n\n"
            "Выберите формат:",
            reply_markup=keyboard
        )
    except Exception:
        await callback.message.answer(
            f"📚 Том {volume}\n📖 Глав: {chapter_count}\n\nВыберите формат:",
            reply_markup=keyboard
        )


@router.callback_query(F.data.startswith("dl_vol_pdf:"))
async def download_volume_pdf(callback: CallbackQuery) -> None:
    """Download entire volume as PDF."""
    from utils import download_volume_as_pdf
    
    await safe_callback_answer(callback)
    if not callback.message:
        return
    _, manga_id_text, volume = callback.data.split(":")
    manga_id = int(manga_id_text)
    
    client = get_client()
    store = get_favorites()
    
    detail = await run_sync(client.get_manga_detail, manga_id)
    manga_title = detail.title if detail else "Manga"
    
    chapters = await run_sync(client.get_manga_chapters, manga_id)
    vol_chapters = [ch for ch in chapters if str(ch.get("vol")) == volume]
    
    if not vol_chapters:
        try:
            await callback.message.edit_text("❌ Главы тома не найдены.")
        except Exception:
            pass
        return
    
    # Sort by chapter number
    try:
        vol_chapters.sort(key=lambda x: float(x.get("ch") or 0))
    except (ValueError, TypeError):
        pass
    
    file_name = f"{manga_title} - Том {volume}.pdf"
    
    # Check cache first
    cached_file_id = store.get_cached_volume(manga_id, volume, "pdf")
    if cached_file_id:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer_document(cached_file_id, caption=f"📕 {manga_title} - Том {volume}")
        # Mark all chapters in volume as read
        for ch in vol_chapters:
            ch_id = ch.get("id")
            ch_name = chapter_title(ch)
            store.mark_chapter_read(callback.from_user.id, manga_id, ch_id, ch_name)
        return
    
    try:
        await callback.message.edit_text(
            f"⏳ Скачиваю том {volume} ({len(vol_chapters)} глав) как PDF...\n"
            "Это может занять некоторое время."
        )
    except Exception:
        pass
    
    # Collect all pages from all chapters
    all_pages = []
    for ch in vol_chapters:
        chapter_id = ch.get("id")
        pages = await run_sync(client.get_chapter_pages, manga_id, chapter_id)
        if pages:
            all_pages.extend(pages)
    
    if not all_pages:
        try:
            await callback.message.edit_text("❌ Страницы не найдены.")
        except Exception:
            pass
        return
    
    # First try without compression
    progress_cb = create_progress_callback(callback.message)
    pdf_path = await download_volume_as_pdf(all_pages, f"{manga_title} - Том {volume}", progress_callback=progress_cb)
    
    if not pdf_path or not os.path.exists(pdf_path):
        try:
            await callback.message.edit_text("❌ Не удалось создать PDF.")
        except Exception:
            pass
        return
    
    # Check file size (Telegram limit: 50MB for bots via Bot API)
    file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
    use_telethon = False
    
    # If too large for Bot API, try Telethon first (up to 2GB)
    if file_size_mb > 50:
        from telethon_client import is_telethon_available, send_large_file
        
        if is_telethon_available() and file_size_mb <= 2000:  # Telethon limit: 2GB
            use_telethon = True
            try:
                await callback.message.edit_text(
                    f"⏳ Том большой ({file_size_mb:.1f} MB).\n"
                    "Отправляю через Telethon..."
                )
            except Exception:
                pass
        else:
            # No Telethon, try compression
            os.remove(pdf_path)
            try:
                await callback.message.edit_text(
                    f"⏳ Том слишком большой ({file_size_mb:.1f} MB).\n"
                    "Сжимаю изображения..."
                )
            except Exception:
                pass
            
            # Retry with compression
            progress_cb = create_progress_callback(callback.message)
            pdf_path = await download_volume_as_pdf(
                all_pages, 
                f"{manga_title} - Том {volume}", 
                compress=True,
                max_dimension=1600,
                quality=70,
                progress_callback=progress_cb
            )
            
            if not pdf_path or not os.path.exists(pdf_path):
                try:
                    await callback.message.edit_text("❌ Не удалось создать сжатый PDF.")
                except Exception:
                    pass
                return
            
            file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
            
            # If still too large after compression
            if file_size_mb > 50:
                os.remove(pdf_path)
                try:
                    await callback.message.edit_text(
                        f"❌ Том слишком большой даже после сжатия ({file_size_mb:.1f} MB).\n"
                        "Лимит Telegram Bot API: 50 MB.\n\n"
                        "💡 Настройте Telethon (API_ID, API_HASH) для файлов до 2 GB\n"
                        "или скачайте главы по отдельности.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="◀ Назад", callback_data=f"chapters:{manga_id}:1")]
                        ])
                    )
                except Exception:
                    pass
                return
            
            # Mark as compressed in filename
            file_name = f"{manga_title} - Том {volume} (сжатый).pdf"
    
    try:
        if use_telethon:
            # Send via Telethon for large files
            from telethon_client import send_large_file
            
            # Create a new message for upload progress
            progress_msg = await callback.message.edit_text("📤 Загрузка: 0%...")
            upload_progress_cb = create_progress_callback(progress_msg)
            
            sent, file_id = await send_large_file(
                chat_id=callback.from_user.id,
                file_path=pdf_path,
                caption=f"📕 {manga_title} - Том {volume}",
                message_callback=upload_progress_cb
            )
            
            # Delete progress message after upload
            try:
                await progress_msg.delete()
            except Exception:
                pass
            
            if not sent:
                await callback.message.answer(
                    "❌ Не удалось отправить через Telethon.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="◀ Назад", callback_data=f"chapters:{manga_id}:1")]
                    ])
                )
                return
            
            # Cache file_id from Telethon (compatible with aiogram)
            if file_id:
                store.cache_volume(manga_id, volume, "pdf", file_id, file_name)
        else:
            # Send via aiogram (Bot API)
            pdf_file = FSInputFile(pdf_path, filename=file_name)
            try:
                await callback.message.delete()
            except Exception:
                pass
            sent_msg = await callback.message.answer_document(pdf_file, caption=f"📕 {manga_title} - Том {volume}")
            
            # Cache file_id
            if sent_msg.document:
                store.cache_volume(manga_id, volume, "pdf", sent_msg.document.file_id, file_name)
        
        # Mark all chapters in volume as read
        for ch in vol_chapters:
            ch_id = ch.get("id")
            ch_name = chapter_title(ch)
            store.mark_chapter_read(callback.from_user.id, manga_id, ch_id, ch_name)
    except Exception as e:
        if "Too Large" in str(e) or "EntityTooLarge" in str(type(e).__name__):
            try:
                await callback.message.edit_text(
                    f"❌ Том слишком большой для Telegram.\n"
                    "Лимит: 50 MB.\n\n"
                    "💡 Скачайте главы по отдельности.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="◀ Назад", callback_data=f"chapters:{manga_id}:1")]
                    ])
                )
            except Exception:
                pass
        else:
            raise
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)


@router.callback_query(F.data.startswith("dl_vol_cbz:"))
async def download_volume_cbz(callback: CallbackQuery) -> None:
    """Download entire volume as CBZ."""
    from utils import download_volume_as_cbz
    
    await safe_callback_answer(callback)
    if not callback.message:
        return
    _, manga_id_text, volume = callback.data.split(":")
    manga_id = int(manga_id_text)
    
    client = get_client()
    store = get_favorites()
    
    detail = await run_sync(client.get_manga_detail, manga_id)
    manga_title = detail.title if detail else "Manga"
    
    chapters = await run_sync(client.get_manga_chapters, manga_id)
    vol_chapters = [ch for ch in chapters if str(ch.get("vol")) == volume]
    
    if not vol_chapters:
        try:
            await callback.message.edit_text("❌ Главы тома не найдены.")
        except Exception:
            pass
        return
    
    # Sort by chapter number
    try:
        vol_chapters.sort(key=lambda x: float(x.get("ch") or 0))
    except (ValueError, TypeError):
        pass
    
    file_name = f"{manga_title} - Том {volume}.cbz"
    
    # Check cache first
    cached_file_id = store.get_cached_volume(manga_id, volume, "cbz")
    if cached_file_id:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer_document(cached_file_id, caption=f"📦 {manga_title} - Том {volume}")
        # Mark all chapters in volume as read
        for ch in vol_chapters:
            ch_id = ch.get("id")
            ch_name = chapter_title(ch)
            store.mark_chapter_read(callback.from_user.id, manga_id, ch_id, ch_name)
        return
    
    try:
        await callback.message.edit_text(
            f"⏳ Скачиваю том {volume} ({len(vol_chapters)} глав) как CBZ...\n"
            "Это может занять некоторое время."
        )
    except Exception:
        pass
    
    # Collect all pages from all chapters with chapter info
    pages_with_info = []
    for ch in vol_chapters:
        chapter_id = ch.get("id")
        ch_name = chapter_title(ch)
        pages = await run_sync(client.get_chapter_pages, manga_id, chapter_id)
        if pages:
            for page in pages:
                # Extract URL from page dict
                url = page.get("img") or page.get("image") or page.get("url")
                if url:
                    pages_with_info.append({"url": url, "chapter": ch_name})
    
    if not pages_with_info:
        try:
            await callback.message.edit_text("❌ Страницы не найдены.")
        except Exception:
            pass
        return
    
    # First try without compression
    progress_cb = create_progress_callback(callback.message)
    cbz_path = await download_volume_as_cbz(pages_with_info, f"{manga_title} - Том {volume}", progress_callback=progress_cb)
    
    if not cbz_path or not os.path.exists(cbz_path):
        try:
            await callback.message.edit_text("❌ Не удалось создать CBZ.")
        except Exception:
            pass
        return
    
    # Check file size (Telegram limit: 50MB for bots via Bot API)
    file_size_mb = os.path.getsize(cbz_path) / (1024 * 1024)
    use_telethon = False
    
    # If too large for Bot API, try Telethon first (up to 2GB)
    if file_size_mb > 50:
        from telethon_client import is_telethon_available, send_large_file
        
        if is_telethon_available() and file_size_mb <= 2000:  # Telethon limit: 2GB
            use_telethon = True
            try:
                await callback.message.edit_text(
                    f"⏳ Том большой ({file_size_mb:.1f} MB).\n"
                    "Отправляю через Telethon..."
                )
            except Exception:
                pass
        else:
            # No Telethon, try compression
            os.remove(cbz_path)
            try:
                await callback.message.edit_text(
                    f"⏳ Том слишком большой ({file_size_mb:.1f} MB).\n"
                    "Сжимаю изображения..."
                )
            except Exception:
                pass
            
            # Retry with compression
            progress_cb = create_progress_callback(callback.message)
            cbz_path = await download_volume_as_cbz(
                pages_with_info, 
                f"{manga_title} - Том {volume}",
                compress=True,
                max_dimension=1600,
                quality=70,
                progress_callback=progress_cb
            )
            
            if not cbz_path or not os.path.exists(cbz_path):
                try:
                    await callback.message.edit_text("❌ Не удалось создать сжатый CBZ.")
                except Exception:
                    pass
                return
            
            file_size_mb = os.path.getsize(cbz_path) / (1024 * 1024)
            
            # If still too large after compression
            if file_size_mb > 50:
                os.remove(cbz_path)
                try:
                    await callback.message.edit_text(
                        f"❌ Том слишком большой даже после сжатия ({file_size_mb:.1f} MB).\n"
                        "Лимит Telegram Bot API: 50 MB.\n\n"
                        "💡 Настройте Telethon (API_ID, API_HASH) для файлов до 2 GB\n"
                        "или скачайте главы по отдельности.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="◀ Назад", callback_data=f"chapters:{manga_id}:1")]
                        ])
                    )
                except Exception:
                    pass
                return
            
            # Mark as compressed in filename
            file_name = f"{manga_title} - Том {volume} (сжатый).cbz"
    
    try:
        if use_telethon:
            # Send via Telethon for large files
            from telethon_client import send_large_file
            
            # Create a new message for upload progress
            progress_msg = await callback.message.edit_text("📤 Загрузка: 0%...")
            upload_progress_cb = create_progress_callback(progress_msg)
            
            sent, file_id = await send_large_file(
                chat_id=callback.from_user.id,
                file_path=cbz_path,
                caption=f"📦 {manga_title} - Том {volume}",
                message_callback=upload_progress_cb
            )
            
            # Delete progress message after upload
            try:
                await progress_msg.delete()
            except Exception:
                pass
            
            if not sent:
                await callback.message.answer(
                    "❌ Не удалось отправить через Telethon.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="◀ Назад", callback_data=f"chapters:{manga_id}:1")]
                    ])
                )
                return
            
            # Cache file_id from Telethon (compatible with aiogram)
            if file_id:
                store.cache_volume(manga_id, volume, "cbz", file_id, file_name)
        else:
            # Send via aiogram (Bot API)
            cbz_file = FSInputFile(cbz_path, filename=file_name)
            try:
                await callback.message.delete()
            except Exception:
                pass
            sent_msg = await callback.message.answer_document(cbz_file, caption=f"📦 {manga_title} - Том {volume}")
            
            # Cache file_id
            if sent_msg.document:
                store.cache_volume(manga_id, volume, "cbz", sent_msg.document.file_id, file_name)
        
        # Mark all chapters in volume as read
        for ch in vol_chapters:
            ch_id = ch.get("id")
            ch_name = chapter_title(ch)
            store.mark_chapter_read(callback.from_user.id, manga_id, ch_id, ch_name)
    except Exception as e:
        if "Too Large" in str(e) or "EntityTooLarge" in str(type(e).__name__):
            try:
                await callback.message.edit_text(
                    f"❌ Том слишком большой для Telegram.\n"
                    "Лимит: 50 MB.\n\n"
                    "💡 Скачайте главы по отдельности.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="◀ Назад", callback_data=f"chapters:{manga_id}:1")]
                    ])
                )
            except Exception:
                pass
        else:
            raise
    finally:
        if os.path.exists(cbz_path):
            os.remove(cbz_path)
