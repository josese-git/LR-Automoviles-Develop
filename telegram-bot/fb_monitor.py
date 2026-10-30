"""
fb_monitor.py - Monitor de Facebook Marketplace para el Bot JVeloce

Contiene:
  - check_facebook_marketplace_job(): Job periódico que se ejecuta en la Job Queue
    del bot de Telegram y detecta nuevos anuncios en el perfil de FB Marketplace.
  - _send_fb_vehicle_preview(): Envía al admin la vista previa del anuncio detectado
    reutilizando el pipeline de IA (Gemini + remove.bg) del bot.
"""

import asyncio
import logging
import os
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from facebook_scraper import FacebookMarketplaceScraper, FBListingStateManager, FBListing

logger = logging.getLogger("FBMonitor")

# ─── Constantes ───────────────────────────────────────────────────────────────

# Intervalo entre comprobaciones, configurable vía .env
CHECK_INTERVAL_SECONDS = int(os.getenv("FB_CHECK_INTERVAL_MINUTES", "15")) * 60
ADMIN_TELEGRAM_ID_ENV = "ADMIN_TELEGRAM_ID"

# Directorio temporal compartido con el bot
TEMP_DIR = Path(__file__).parent / "temp_images"
TEMP_DIR.mkdir(exist_ok=True)


# ─── Descarga de imágenes ─────────────────────────────────────────────────────


def _download_image(url: str, dest_dir: Path) -> Path | None:
    """
    Descarga una imagen desde una URL a un directorio temporal.
    Devuelve la ruta al archivo descargado, o None si falla.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.facebook.com/",
    }
    try:
        r = requests.get(url, headers=headers, timeout=20, stream=True)
        r.raise_for_status()

        # Detectar extensión desde Content-Type o URL
        content_type = r.headers.get("Content-Type", "image/jpeg")
        ext = ".jpg"
        if "png" in content_type:
            ext = ".png"
        elif "webp" in content_type:
            ext = ".webp"

        filename = f"fb_{uuid.uuid4().hex[:8]}{ext}"
        dest = dest_dir / filename
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.debug(f"Imagen descargada: {dest.name} ({dest.stat().st_size} bytes)")
        return dest

    except Exception as e:
        logger.warning(f"No se pudo descargar la imagen {url[:80]}...: {e}")
        return None


# ─── Job periódico ────────────────────────────────────────────────────────────


async def check_facebook_marketplace_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Job periódico de la Job Queue del bot.
    Comprueba si hay nuevos anuncios en el perfil de Facebook Marketplace de JVeloce.
    Si hay nuevos, los descarga y los procesa con el pipeline de IA del bot.
    """
    # Importar los objetos globales del bot principal (se inyectan vía context.bot_data)
    firebase = context.bot_data.get("firebase")
    gemini = context.bot_data.get("gemini")
    admin_id = context.bot_data.get("admin_id", 0)
    state_manager: FBListingStateManager = context.bot_data.get("fb_state_manager")
    process_vehicle_fn = context.bot_data.get("process_vehicle_from_data_fn")

    if not all([firebase, gemini, admin_id, state_manager, process_vehicle_fn]):
        logger.warning("FBMonitor: No se puede ejecutar, faltan dependencias en bot_data.")
        return

    if admin_id == 0:
        logger.warning("FBMonitor: ADMIN_TELEGRAM_ID no configurado, saltando check.")
        return

    logger.info("🔍 FBMonitor: Iniciando comprobación de Facebook Marketplace...")

    try:
        scraper = FacebookMarketplaceScraper(headless=True)
        listings = await scraper.get_profile_listings()
    except Exception as e:
        logger.error(f"FBMonitor: Error al obtener anuncios de Facebook: {e}", exc_info=True)
        return

    if not listings:
        logger.info("FBMonitor: No se encontraron anuncios en el perfil de Facebook.")
        return

    logger.info(f"FBMonitor: {len(listings)} anuncios encontrados en el perfil.")

    # ── Primer arranque: marcar todos como procesados ──
    if state_manager.is_first_run():
        all_ids = [item["id"] for item in listings]
        state_manager.mark_all_processed(all_ids)
        logger.info(
            f"FBMonitor: Primer arranque completado. "
            f"{len(all_ids)} anuncios existentes marcados como vistos. "
            f"El monitor detectará solo los NUEVOS anuncios a partir de ahora."
        )
        # Notificar al admin
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    "✅ <b>Monitor de Facebook Marketplace activado</b>\n\n"
                    f"📊 Se han marcado <b>{len(all_ids)} anuncios existentes</b> como ya procesados.\n"
                    "🔔 A partir de ahora recibirás una notificación en este chat cuando se publique "
                    "un nuevo anuncio en el perfil de Facebook Marketplace.\n\n"
                    f"⏱ Intervalo de comprobación: cada <b>{CHECK_INTERVAL_SECONDS // 60} minutos</b>.\n\n"
                    "💡 Usa /check_fb para forzar una comprobación manual en cualquier momento."
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass
        return

    # ── Buscar anuncios nuevos (no vistos previamente) ──
    new_listings = [
        item for item in listings
        if not state_manager.is_processed(item["id"])
    ]

    if not new_listings:
        logger.info("FBMonitor: Sin anuncios nuevos. Todo al día.")
        return

    logger.info(f"FBMonitor: ¡{len(new_listings)} anuncios NUEVOS detectados!")

    # Procesar cada nuevo anuncio
    for basic_info in new_listings:
        fb_id = basic_info["id"]
        try:
            await _process_new_fb_listing(
                context=context,
                basic_info=basic_info,
                scraper=scraper,
                state_manager=state_manager,
                admin_id=admin_id,
                process_vehicle_fn=process_vehicle_fn,
            )
        except Exception as e:
            logger.error(f"FBMonitor: Error procesando anuncio {fb_id}: {e}", exc_info=True)
            # Marcar como procesado de todas formas para no volver a intentarlo en bucle
            state_manager.mark_processed(fb_id)


async def _process_new_fb_listing(
    context: ContextTypes.DEFAULT_TYPE,
    basic_info: dict,
    scraper: FacebookMarketplaceScraper,
    state_manager: FBListingStateManager,
    admin_id: int,
    process_vehicle_fn,
):
    """
    Procesa un nuevo anuncio detectado en Facebook:
    1. Obtiene los detalles completos (descripción + fotos HD).
    2. Descarga las fotos localmente.
    3. Llama al pipeline de IA del bot (Gemini + remove.bg) para generar la vista previa.
    4. Envía la notificación al admin con los botones de Confirmar/Cancelar.
    """
    fb_id = basic_info["id"]
    listing_url = basic_info.get("listing_url", f"https://www.facebook.com/marketplace/item/{fb_id}/")
    title = basic_info.get("title", "Vehículo desconocido")
    price = basic_info.get("price", "N/D")

    logger.info(f"FBMonitor: Procesando nuevo anuncio: {fb_id} | {title} | {price}")

    # Notificar al admin que se está procesando
    status_msg = await context.bot.send_message(
        chat_id=admin_id,
        text=(
            f"🔔 <b>¡Nuevo anuncio detectado en Facebook Marketplace!</b>\n\n"
            f"📋 <b>Título:</b> {title}\n"
            f"💰 <b>Precio:</b> {price}\n"
            f"🔗 <a href='{listing_url}'>Ver en Facebook</a>\n\n"
            "⏳ Descargando fotos y analizando con IA..."
        ),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    # ── Paso 1: Obtener detalles completos del anuncio ──
    try:
        full_listing: FBListing = await scraper.get_full_listing(
            fb_id=fb_id,
            listing_url=listing_url,
            title=title,
            price=price,
        )
    except Exception as e:
        logger.error(f"FBMonitor: No se pudieron obtener los detalles de {fb_id}: {e}")
        await context.bot.edit_message_text(
            chat_id=admin_id,
            message_id=status_msg.message_id,
            text=(
                f"⚠️ <b>Nuevo anuncio detectado pero falló la descarga de detalles.</b>\n\n"
                f"📋 <b>Título:</b> {title}\n"
                f"💰 <b>Precio:</b> {price}\n"
                f"🔗 <a href='{listing_url}'>Ver en Facebook</a>\n\n"
                f"❌ Error: {e}\n\n"
                "Puedes procesarlo manualmente enviando las fotos al bot."
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        state_manager.mark_processed(fb_id)
        return

    if not full_listing.photo_urls:
        await context.bot.edit_message_text(
            chat_id=admin_id,
            message_id=status_msg.message_id,
            text=(
                f"⚠️ <b>Nuevo anuncio detectado en Facebook, pero sin fotos accesibles.</b>\n\n"
                f"📋 <b>Título:</b> {title}\n"
                f"💰 <b>Precio:</b> {price}\n"
                f"🔗 <a href='{listing_url}'>Ver en Facebook</a>\n\n"
                "Por favor, procésalo manualmente enviando las fotos al bot."
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        state_manager.mark_processed(fb_id)
        return

    # ── Paso 2: Descargar fotos localmente ──
    await context.bot.edit_message_text(
        chat_id=admin_id,
        message_id=status_msg.message_id,
        text=(
            f"🔔 <b>¡Nuevo anuncio en Facebook Marketplace!</b>\n\n"
            f"📋 {title} | {price}\n"
            f"📥 Descargando {len(full_listing.photo_urls)} foto(s)..."
        ),
        parse_mode="HTML",
    )

    downloaded_paths: list[Path] = []
    loop = asyncio.get_event_loop()

    for url in full_listing.photo_urls:
        path = await loop.run_in_executor(None, _download_image, url, TEMP_DIR)
        if path:
            downloaded_paths.append(path)

    if not downloaded_paths:
        await context.bot.edit_message_text(
            chat_id=admin_id,
            message_id=status_msg.message_id,
            text=(
                f"⚠️ No se pudo descargar ninguna foto del anuncio {fb_id}.\n"
                f"📋 {title} | {price}\n"
                f"🔗 <a href='{listing_url}'>Ver en Facebook</a>\n\n"
                "Procésalo manualmente."
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        state_manager.mark_processed(fb_id)
        return

    logger.info(
        f"FBMonitor: {len(downloaded_paths)}/{len(full_listing.photo_urls)} "
        f"fotos descargadas para {fb_id}."
    )

    # ── Paso 3: Borrar el mensaje de estado ──
    try:
        await context.bot.delete_message(chat_id=admin_id, message_id=status_msg.message_id)
    except Exception:
        pass

    # ── Paso 4: Construir la caption/descripción para el pipeline de IA ──
    # Combinar título, precio y descripción del anuncio de Facebook como input para Gemini
    caption_parts = []
    if title and title != "Vehículo desconocido":
        caption_parts.append(title)
    if price and price != "N/D":
        caption_parts.append(f"Precio: {price}")
    if full_listing.description:
        caption_parts.append(full_listing.description)

    fb_caption = "\n".join(caption_parts) if caption_parts else title

    # ── Paso 5: Encabezado de notificación de Facebook ──
    fb_header_msg = await context.bot.send_message(
        chat_id=admin_id,
        text=(
            f"🔔 <b>¡Nuevo anuncio detectado en Facebook Marketplace!</b>\n"
            f"🔗 <a href='{listing_url}'>Ver anuncio original</a>"
        ),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    # ── Paso 6: Llamar al pipeline del bot ──
    # Crear objetos "FakePhoto" para que _process_vehicle pueda leerlos
    class FakeLocalPhoto:
        """Simula un objeto de foto de Telegram con file_id, pero usando rutas locales."""
        def __init__(self, local_path: Path):
            self._local_path = local_path
            # El file_id se usa para descargar, pero nosotros ya tenemos el archivo
            self.file_id = f"local:{local_path}"

        @property
        def local_path(self):
            return self._local_path

    # Guardar el header msg_id en bot_data para limpieza posterior
    context.bot_data[f"fb_header_msg_{admin_id}"] = fb_header_msg.message_id

    # Marcar el origen de este proceso como "facebook" para el callback de confirmación
    # Guardamos el fb_id en bot_data para que el callback lo pueda usar
    context.bot_data["pending_fb_listing_id"] = fb_id
    context.bot_data["pending_fb_state_manager"] = state_manager

    # Llamar al pipeline de procesamiento del bot
    await process_vehicle_fn(
        bot=context.bot,
        chat_id=admin_id,
        user_id=admin_id,
        context=context,
        photo_paths=downloaded_paths,  # Lista de Path locales ya descargadas
        caption=fb_caption,
        fb_listing_id=fb_id,
        fb_listing_url=listing_url,
    )

    # Marcar como procesado DESPUÉS de que el pipeline ha terminado
    # (si el usuario cancela, también se marcará como procesado para no volver a detectarlo)
    state_manager.mark_processed(fb_id)


# ─── Comando manual /check_fb ─────────────────────────────────────────────────


async def cmd_check_fb(update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /check_fb - fuerza una comprobación inmediata de Facebook Marketplace."""
    from bot import is_admin  # Import local para evitar circular

    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ No autorizado.")
        return

    admin_id = context.bot_data.get("admin_id", update.effective_user.id)

    msg = await update.message.reply_text(
        "🔍 Comprobando Facebook Marketplace manualmente...",
        parse_mode="HTML"
    )

    try:
        # Ejecutar el job manualmente
        await check_facebook_marketplace_job(context)
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
        except Exception:
            pass
    except Exception as e:
        await context.bot.edit_message_text(
            f"❌ Error al comprobar Facebook Marketplace: {e}",
            chat_id=update.effective_chat.id,
            message_id=msg.message_id,
        )
