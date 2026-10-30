"""
bot.py - Bot de Telegram para publicación automática de vehículos en JVeloce
Recibe fotos + descripción, usa Gemini para parsear datos, y publica en Firebase.
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from firebase_client import FirebaseClient
from gemini_client import GeminiClient, GeminiKeyManager
from image_processor import remove_background, BackgroundRemovalError
from agent_handler import AgentHandler
from facebook_scraper import FBListingStateManager
from fb_monitor import check_facebook_marketplace_job, cmd_check_fb, CHECK_INTERVAL_SECONDS

# ─── Configuración ───────────────────────────────────────────────────────────

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0"))

# Cargar API Keys de Gemini (soporta múltiples separadas por comas o una sola clave)
GEMINI_API_KEYS_RAW = os.getenv("GEMINI_API_KEYS")
GEMINI_API_KEY_SINGLE = os.getenv("GEMINI_API_KEY")

GEMINI_API_KEYS = []
if GEMINI_API_KEYS_RAW:
    GEMINI_API_KEYS = [k.strip() for k in GEMINI_API_KEYS_RAW.split(",") if k.strip()]
elif GEMINI_API_KEY_SINGLE:
    GEMINI_API_KEYS = [GEMINI_API_KEY_SINGLE]

# Validar que las variables críticas estén definidas
if not TELEGRAM_BOT_TOKEN:
    print("❌ ERROR: TELEGRAM_BOT_TOKEN no está definido en .env")
    sys.exit(1)
if not GEMINI_API_KEYS:
    print("❌ ERROR: GEMINI_API_KEY o GEMINI_API_KEYS no está definido en .env")
    sys.exit(1)

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("JVeloceBot")

# Ruta raíz del proyecto web (un nivel arriba del directorio del bot)
PROJECT_ROOT = Path(__file__).parent.parent

# Carpeta temporal para imágenes descargadas
TEMP_DIR = Path(__file__).parent / "temp_images"
TEMP_DIR.mkdir(exist_ok=True)

# Almacén temporal de fotos por usuario (para agrupar fotos enviadas juntas o en múltiples álbumes)
user_photo_batches: dict[int, dict] = {}

# ─── Inicialización de clientes ──────────────────────────────────────────────

firebase: FirebaseClient | None = None
gemini: GeminiClient | None = None
agent: AgentHandler | None = None
fb_state_manager: FBListingStateManager | None = None


def init_clients():
    """Inicializa los clientes de Firebase, Gemini (parser), el Agente IA y el monitor de FB."""
    global firebase, gemini, agent, fb_state_manager
    try:
        firebase = FirebaseClient()
        logger.info("✅ Firebase inicializado correctamente.")
    except Exception as e:
        logger.error(f"❌ Error al inicializar Firebase: {e}")
        logger.warning(
            "⚠️  El bot funcionará sin Firebase. "
            "Descarga el archivo de credenciales del Service Account."
        )

    # Inicializar el manager de claves compartido
    key_manager = GeminiKeyManager(GEMINI_API_KEYS)

    gemini = GeminiClient(key_manager)
    logger.info("✅ Gemini (parser de anuncios) inicializado con soporte de rotación de claves.")

    # Agente IA — comparte el key_manager pero tiene su lógica/prompt separado
    if firebase:
        agent = AgentHandler(key_manager, firebase)
        logger.info("✅ Agente IA inicializado con soporte de rotación de claves.")
    else:
        logger.warning("⚠️  Agente IA no inicializado (requiere Firebase).")

    # Monitor de Facebook Marketplace
    fb_state_manager = FBListingStateManager()
    logger.info("✅ Monitor de Facebook Marketplace inicializado.")


# ─── Utilidades ──────────────────────────────────────────────────────────────


async def send_message_chunked(bot, chat_id: int, text: str, parse_mode: str = None, reply_markup=None, **kwargs):
    """
    Envía un mensaje de texto largo dividiéndolo en partes de máximo 4000 caracteres.
    Intenta dividir por saltos de línea para no cortar etiquetas HTML/Markdown a la mitad.
    """
    if len(text) <= 4000:
        return [await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode, reply_markup=reply_markup, **kwargs)]

    chunks = []
    lines = text.split("\n")
    current_chunk = ""

    for line in lines:
        if len(current_chunk) + len(line) + 1 > 4000:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = line
            else:
                for i in range(0, len(line), 4000):
                    chunks.append(line[i:i+4000])
        else:
            if current_chunk:
                current_chunk += "\n" + line
            else:
                current_chunk = line

    if current_chunk:
        chunks.append(current_chunk.strip())

    sent_messages = []
    for i, chunk in enumerate(chunks):
        markup = reply_markup if i == len(chunks) - 1 else None
        msg = await bot.send_message(chat_id=chat_id, text=chunk, parse_mode=parse_mode, reply_markup=markup, **kwargs)
        sent_messages.append(msg)
    return sent_messages


def is_admin(user_id: int) -> bool:
    """Verifica si el usuario está autorizado. Si ADMIN_TELEGRAM_ID es 0, permite todos."""
    return ADMIN_TELEGRAM_ID == 0 or user_id == ADMIN_TELEGRAM_ID


def find_brand_logo(brand: str) -> Path | None:
    """
    Busca el logo de la marca en el directorio Coches/logos/ del proyecto web.
    Los logos están nombrados como: mercedes-benz.png, peugeot.png, kia.png, etc.
    """
    logos_dir = PROJECT_ROOT / "Coches" / "logos"
    if not logos_dir.exists():
        logger.warning(f"Directorio de logos no encontrado: {logos_dir}")
        return None

    # Normalizar nombre de marca para buscar
    brand_lower = brand.lower().strip()

    # Mapeo de nombres comunes a nombres de archivo
    brand_aliases = {
        "mercedes": "mercedes-benz",
        "mercedes benz": "mercedes-benz",
        "mercedes-benz": "mercedes-benz",
        "vw": "volkswagen",
        "volkswagen": "volkswagen",
        "land rover": "land-rover",
        "alfa romeo": "alfa-romeo",
        "aston martin": "aston-martin",
        "rolls royce": "rolls-royce",
    }

    # Intentar con alias primero
    search_name = brand_aliases.get(brand_lower, brand_lower.replace(" ", "-"))

    # Buscar coincidencia exacta
    for ext in [".png", ".jpg"]:
        logo_path = logos_dir / f"{search_name}{ext}"
        if logo_path.exists():
            logger.info(f"Logo encontrado: {logo_path.name}")
            return logo_path

    # Buscar coincidencia parcial
    for logo_file in logos_dir.iterdir():
        if logo_file.is_file() and search_name in logo_file.stem.lower():
            logger.info(f"Logo encontrado (parcial): {logo_file.name}")
            return logo_file

    logger.warning(f"No se encontró logo para la marca: {brand}")
    return None


# ─── Handlers de Comandos ────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler del comando /start."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ No autorizado.")
        return

    await update.message.reply_text(
        "🚗 <b>Bot JVeloce — Publicador de Vehículos</b>\n\n"
        "Envía un grupo de fotos con una descripción del vehículo en el caption "
        "y yo me encargo de publicarlo en la web automáticamente.\n\n"
        "📋 <b>Comandos disponibles:</b>\n"
        "• /start — Este mensaje de ayuda\n"
        "• /listar — Ver vehículos publicados\n"
        "• /eliminar <code>&lt;id&gt;</code> — Eliminar un vehículo\n"
        "• /estado — Verificar conexión con Firebase\n\n"
        "📸 <b>¿Cómo publicar?</b>\n"
        "1. Selecciona varias fotos del coche\n"
        "2. Escribe en el caption los datos: marca, modelo, año, precio, km, combustible, "
        "transmisión, potencia y descripción\n"
        "3. ¡Envía y espera! El bot analizará todo con IA y lo publicará\n\n"
        "<i>La primera foto será la imagen principal del anuncio.</i>",
        parse_mode="HTML",
    )


async def cmd_listar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler del comando /listar — muestra los vehículos publicados."""
    if not is_admin(update.effective_user.id):
        return

    if not firebase:
        await update.message.reply_text(
            "❌ Firebase no está conectado. Revisa las credenciales."
        )
        return

    try:
        vehicles = firebase.list_vehicles()
    except Exception as e:
        await update.message.reply_text(f"❌ Error al consultar Firestore: {e}")
        return

    if not vehicles:
        await update.message.reply_text("📭 No hay vehículos publicados actualmente.")
        return

    lines = ["🚗 *Vehículos publicados:*\n"]
    for v in vehicles:
        status = "🔴 VENDIDO" if v.get("sold") else "🟢 En venta"
        brand = v.get("brand", "?")
        model = v.get("model", "?")
        year = v.get("year", "?")
        price = v.get("price", "N/D")
        lines.append(f"• `{v['id']}`\n  {brand} {model} ({year}) — {price} {status}")

    await send_message_chunked(context.bot, update.effective_chat.id, "\n".join(lines), parse_mode="Markdown")


async def cmd_eliminar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler del comando /eliminar <id> — elimina un vehículo de Firestore."""
    if not is_admin(update.effective_user.id):
        return

    if not firebase:
        await update.message.reply_text("❌ Firebase no está conectado.")
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ Uso: `/eliminar <id_vehiculo>`\n\n"
            "Usa /listar para ver los IDs disponibles.",
            parse_mode="Markdown",
        )
        return

    vehicle_id = context.args[0]

    try:
        firebase.delete_vehicle(vehicle_id)
        await update.message.reply_text(
            f"✅ Vehículo `{vehicle_id}` eliminado correctamente.",
            parse_mode="Markdown",
        )
    except ValueError as e:
        await update.message.reply_text(f"⚠️ {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error inesperado: {e}")


async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler del comando /estado — verifica la conexión con Firebase."""
    if not is_admin(update.effective_user.id):
        return

    lines = ["📊 *Estado del Bot JVeloce:*\n"]

    # Firebase
    if firebase:
        try:
            count = firebase.get_vehicle_count()
            lines.append(f"🟢 Firebase: Conectado ({count} vehículos)")
        except Exception as e:
            lines.append(f"🔴 Firebase: Error — {e}")
    else:
        lines.append("🔴 Firebase: No conectado")

    # Gemini
    lines.append(f"🟢 Gemini: Configurado" if gemini else "🔴 Gemini: No configurado")

    # Admin
    if ADMIN_TELEGRAM_ID == 0:
        lines.append("⚠️ Admin: Cualquier usuario (ADMIN_TELEGRAM_ID=0)")
    else:
        lines.append(f"🔒 Admin: Restringido a ID {ADMIN_TELEGRAM_ID}")

    # Logos
    logos_dir = PROJECT_ROOT / "Coches" / "logos"
    if logos_dir.exists():
        logo_count = len(list(logos_dir.iterdir()))
        lines.append(f"🏷️ Logos disponibles: {logo_count} marcas")
    else:
        lines.append("⚠️ Logos: Directorio no encontrado")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─── Handler de Fotos / Agrupamiento por Usuario ─────────────────────────────


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler para mensajes con fotos.
    Agrupa todas las fotos enviadas por el mismo usuario en una ventana de 4 segundos
    para dar soporte a álbumes de más de 10 fotos (que Telegram divide en múltiples media groups).
    """
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ No autorizado.")
        return

    message = update.message
    user_id = message.from_user.id
    chat_id = message.chat_id

    if user_id not in user_photo_batches:
        user_photo_batches[user_id] = {
            "photos": [],
            "caption": None,
            "chat_id": chat_id,
        }

    # Tomar la versión de mayor resolución de la foto
    photo = message.photo[-1]
    user_photo_batches[user_id]["photos"].append(photo)

    # Capturar el caption si viene en alguno de los mensajes
    if message.caption:
        user_photo_batches[user_id]["caption"] = message.caption

    # Programar o posponer el job de procesamiento para esperar a que lleguen todas las fotos (4s)
    job_name = f"process_user_photos_{user_id}"
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    for job in current_jobs:
        job.schedule_removal()

    context.job_queue.run_once(
        _process_user_photos_job,
        when=4.0,
        data=user_id,
        name=job_name,
        chat_id=chat_id,
        user_id=user_id,
    )


async def _process_user_photos_job(context: ContextTypes.DEFAULT_TYPE):
    """Job callback que se ejecuta tras recopilar todas las fotos del usuario."""
    user_id = context.job.data
    batch = user_photo_batches.pop(user_id, None)

    if not batch:
        return

    # Si no hay caption, pedir la descripción en un mensaje separado
    if not batch["caption"]:
        context.user_data['pending_photos'] = {
            'file_ids': [p.file_id for p in batch['photos']],
            'chat_id': batch['chat_id'],
            'user_id': user_id
        }
        await context.bot.send_message(
            batch["chat_id"],
            "📸 <b>Álbum de fotos recibido correctamente.</b>\n\n"
            "Ahora envíame el texto descriptivo del coche en un mensaje de texto separado.\n"
            "o envíame éstos detalles clave si quieres que yo mismo genere la descripción:\n"
            "🚗 Modelo del coche:\n"
            "💰 Precio: \n"
            "📅 Año: \n"
            "⛽ Combustible: \n"
            "🔧 Transmisión:\n"
            "📏 Km: \n"
            "🐴 Potencia CV:",
            parse_mode="HTML",
        )
        return

    await _process_vehicle(
        context.bot,
        batch["chat_id"],
        user_id,
        context,
        batch["photos"],
        batch["caption"],
    )


async def handle_audio_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja las notas de voz o audios enviados por el usuario."""
    if not is_admin(update.effective_user.id):
        return

    if not gemini:
        await update.message.reply_text("❌ Gemini no está configurado, no puedo procesar audios.")
        return

    status_msg = await update.message.reply_text("🎧 Escuchando audio...")
    
    audio_obj = update.message.voice or update.message.audio
    if not audio_obj:
        return
        
    try:
        file = await context.bot.get_file(audio_obj.file_id)
        temp_audio = TEMP_DIR / f"audio_{audio_obj.file_id}.ogg"
        await file.download_to_drive(str(temp_audio))
        
        await context.bot.edit_message_text("✍️ Transcribiendo...", chat_id=update.message.chat_id, message_id=status_msg.message_id)
        
        loop = asyncio.get_event_loop()
        transcribed_text = await loop.run_in_executor(None, gemini.transcribe_audio, temp_audio)
        
        try:
            temp_audio.unlink(missing_ok=True)
        except OSError:
            pass
            
        if not transcribed_text:
            await context.bot.edit_message_text("❌ No pude entender el audio.", chat_id=update.message.chat_id, message_id=status_msg.message_id)
            return
            
        await context.bot.edit_message_text(f"🎤 <i>\"{transcribed_text}\"</i>", chat_id=update.message.chat_id, message_id=status_msg.message_id, parse_mode="HTML")
        
        # Guardar flag para responder con voz
        context.user_data["reply_with_voice"] = True
        
        # Enrutar a lógica de texto
        await handle_text_description(update, context, override_text=transcribed_text)
        
    except Exception as e:
        logger.error(f"Error procesando audio: {e}", exc_info=True)
        await context.bot.edit_message_text(f"❌ Error al procesar audio: {e}", chat_id=update.message.chat_id, message_id=status_msg.message_id)


async def handle_text_description(update: Update, context: ContextTypes.DEFAULT_TYPE, override_text: str = None):
    """Maneja la descripción de texto enviada por separado después de las fotos,
    o redirige al agente IA si no hay fotos pendientes."""
    if not is_admin(update.effective_user.id):
        return

    pending_photos = context.user_data.get("pending_photos")

    # Si NO hay fotos pendientes → redirigir al agente IA de gestión
    if not pending_photos:
        if agent:
            await agent.process_message(update, context, override_text=override_text)
        return

    # Si hay fotos pendientes → flujo normal de publicación de anuncio
    context.user_data.pop("pending_photos", None)

    caption = override_text if override_text is not None else update.message.text
    chat_id = pending_photos["chat_id"]
    user_id = pending_photos["user_id"]
    file_ids = pending_photos["file_ids"]

    class FakePhoto:
        def __init__(self, file_id):
            self.file_id = file_id

    photos = [FakePhoto(fid) for fid in file_ids]

    await _process_vehicle(context.bot, chat_id, user_id, context, photos, caption)


async def handle_document_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la descripción enviada en un archivo de texto (.txt) después de las fotos."""
    if not is_admin(update.effective_user.id):
        return

    pending_photos = context.user_data.get("pending_photos")
    if not pending_photos:
        return

    document = update.message.document
    if not (document.mime_type == "text/plain" or (document.file_name and document.file_name.lower().endswith(".txt"))):
        await update.message.reply_text("⚠️ Solo se admiten archivos de texto (.txt) para la descripción del coche.")
        return

    # Limpiar estado
    context.user_data.pop("pending_photos", None)

    chat_id = pending_photos["chat_id"]
    user_id = pending_photos["user_id"]
    file_ids = pending_photos["file_ids"]

    # Descargar y leer el archivo .txt
    try:
        status_msg = await update.message.reply_text("📥 Descargando archivo de texto...")
        file = await context.bot.get_file(document.file_id)
        # Descargar temporalmente
        temp_txt = TEMP_DIR / f"desc_{document.file_id}.txt"
        await file.download_to_drive(str(temp_txt))
        caption = temp_txt.read_text(encoding="utf-8")
        temp_txt.unlink(missing_ok=True)
        await context.bot.delete_message(chat_id, status_msg.message_id)
    except Exception as e:
        await update.message.reply_text(f"❌ Error al leer el archivo de texto: {e}")
        return

    class FakePhoto:
        def __init__(self, file_id):
            self.file_id = file_id

    photos = [FakePhoto(fid) for fid in file_ids]

    await _process_vehicle(context.bot, chat_id, user_id, context, photos, caption)


# ─── Lógica Principal de Procesamiento ────────────────────────────────────────


async def _process_vehicle(
    bot,
    chat_id: int,
    user_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    photos: list,
    caption: str,
    photo_paths: list[Path] | None = None,
    fb_listing_id: str | None = None,
    fb_listing_url: str | None = None,
):
    """
    Fase 1: Descarga imágenes (desde Telegram o desde rutas locales pre-descargadas),
    extrae datos con Gemini, ordena las fotos, quita el fondo de la principal
    y presenta la vista previa interactiva.

    Args:
        photos: Lista de objetos de foto de Telegram (con file_id).
        photo_paths: Lista de Path locales ya descargadas (desde Facebook). Si se especifica,
                     se omite la descarga desde Telegram.
        fb_listing_id: ID del anuncio de Facebook (si el origen es Facebook Marketplace).
        fb_listing_url: URL del anuncio de Facebook para incluir en la vista previa.
    """
    if not firebase:
        await bot.send_message(
            chat_id,
            "❌ Firebase no está conectado. "
            "Coloca el archivo `firebase-service-account.json` y reinicia el bot.",
        )
        return

    if not gemini:
        await bot.send_message(chat_id, "❌ Gemini no está configurado.")
        return

    # Mensaje de estado
    status_msg = await bot.send_message(
        chat_id,
        f"⏳ Procesando {len(photos)} imagen(es)...\n"
        "📥 Descargando fotos de Telegram...",
    )

    image_paths: list[Path] = []

    try:
        # ── Paso 1: Obtener imágenes (desde Telegram o ya descargadas de Facebook) ──
        if photo_paths:
            # Caso Facebook: imágenes ya descargadas localmente
            image_paths = [p for p in photo_paths if p and p.exists()]
            logger.info(f"[FB] Usando {len(image_paths)} imágenes pre-descargadas de Facebook.")
        else:
            # Caso normal: descargar desde Telegram
            for i, photo in enumerate(photos):
                file = await bot.get_file(photo.file_id)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{timestamp}_{i:02d}.jpg"
                filepath = TEMP_DIR / filename
                await file.download_to_drive(str(filepath))
                image_paths.append(filepath)

        # ── Paso 2: Analizar descripción e imágenes con Gemini primero ──
        fb_label = " [desde Facebook Marketplace]" if fb_listing_id else ""
        await bot.edit_message_text(
            f"📸 {len(image_paths)} foto(s) descargadas{fb_label}.\n"
            "🤖 Analizando con Gemini y clasificando imágenes...",
            chat_id,
            status_msg.message_id,
        )

        vehicle_data = gemini.parse_vehicle(caption, image_paths)

        if not vehicle_data:
            await bot.edit_message_text(
                "❌ <b>Error de análisis</b>\n\n"
                "Gemini no pudo extraer los datos del vehículo.\n"
                "Revisa que el caption contenga al menos la marca, modelo y precio.",
                chat_id,
                status_msg.message_id,
                parse_mode="HTML",
            )
            # Limpiar archivos si falla
            for img_path in image_paths:
                try:
                    img_path.unlink(missing_ok=True)
                except OSError:
                    pass
            return

        # ── Paso 3: Clasificar y ordenar imágenes según el análisis de Gemini ──
        classification = {
            "classified_images": vehicle_data.pop("classified_images", None)
        }
        principal_con_fondo, sorted_exteriors, sorted_interiors = _sort_images_by_classification(
            image_paths, classification
        )

        # ── Paso 4: Quitar fondo a la imagen principal seleccionada por la IA ──
        await bot.edit_message_text(
            "🚗 Ordenación de imágenes completada por IA.\n"
            "✨ Quitándole el fondo a la imagen principal...",
            chat_id,
            status_msg.message_id,
        )

        main_image_nobg_path = None
        if principal_con_fondo:
            try:
                # remove_background es síncrono, se ejecuta en un executor para no bloquear el loop del bot
                loop = asyncio.get_event_loop()
                main_image_nobg_path = await loop.run_in_executor(
                    None, remove_background, principal_con_fondo
                )
                # Voltear horizontalmente (espejo) solo la imagen con fondo transparente
                if main_image_nobg_path and main_image_nobg_path != principal_con_fondo:
                    from PIL import Image
                    def _flip_image(path):
                        with Image.open(path) as img:
                            flipped = img.transpose(Image.FLIP_LEFT_RIGHT)
                            flipped.save(path)
                    await loop.run_in_executor(None, _flip_image, main_image_nobg_path)
            except Exception as e:
                logger.error(f"Error al quitar el fondo: {e}")
                await bot.send_message(
                    chat_id,
                    f"⚠️ No se pudo quitar el fondo de la imagen principal: {e}\n"
                    "Se usará la foto original con fondo como portada principal."
                )
                main_image_nobg_path = principal_con_fondo

        # ── Paso 5: Limpiar publicación pendiente anterior si existía ──
        _cleanup_pending_vehicle(context)

        # Guardar en memoria temporal
        brand = vehicle_data.get("brand", "Desconocido")
        model = vehicle_data.get("model", "Desconocido")
        inferred_fields = vehicle_data.pop("inferred_fields", [])
        
        context.user_data["pending_vehicle"] = {
            "vehicle_data": vehicle_data,
            "inferred_fields": inferred_fields,
            "main_image_path": str(main_image_nobg_path) if main_image_nobg_path else "",
            "sorted_exterior_paths": [str(p) if p else None for p in sorted_exteriors],
            "sorted_interior_paths": [str(p) for p in sorted_interiors],
            # Lista de todos los archivos físicos a borrar
            "image_paths": [str(p) for p in image_paths] + ([str(main_image_nobg_path)] if main_image_nobg_path and main_image_nobg_path != principal_con_fondo else []),
            "brand": brand,
            "model": model,
            "chat_id": chat_id,
            "preview_message_id": None,
            # Metadatos de Facebook (si procede)
            "fb_listing_id": fb_listing_id,
            "fb_listing_url": fb_listing_url,
        }

        # ── Paso 6: Generar vista previa con teclado en línea ──
        price = vehicle_data.get("price", "N/D")
        year = vehicle_data.get("year", "N/D")
        fuel = vehicle_data.get("fuel", "N/D")
        transmission = vehicle_data.get("transmission", "N/D")
        km = vehicle_data.get("km", "N/D")
        cv = vehicle_data.get("cv", "N/D")

        keyboard = [
            [
                InlineKeyboardButton("✅ Confirmar y Publicar", callback_data="publish_confirm"),
                InlineKeyboardButton("❌ Cancelar", callback_data="publish_cancel"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Usar la imagen transparente si se creó, o la original como fallback
        preview_image = main_image_nobg_path or principal_con_fondo or image_paths[0]

        # Contar cuántas fotos exteriores se identificaron
        exterior_count = len([p for p in sorted_exteriors if p])

        # Función auxiliar para añadir "(guessed)" en la vista previa a los campos que la IA dedujo
        def get_preview_val(field_name, val):
            if field_name in inferred_fields:
                return f"{val} (guessed)"
            return val

        cv_display = f"{cv} CV"
        if "cv" in inferred_fields:
            cv_display = f"{cv} CV (guessed)"

        def build_preview_lines(include_description=True):
            lines = []
            # Cabecera especial si viene de Facebook
            if fb_listing_id:
                lines.append("🔔 <b>NUEVO ANUNCIO DETECTADO EN FACEBOOK MARKETPLACE</b>")
                if fb_listing_url:
                    lines.append(f"🔗 <a href='{fb_listing_url}'>Ver anuncio original en Facebook</a>")
                lines.append("")
            lines += [
                "👀 <b>VISTA PREVIA DEL ANUNCIO</b>\n",
                f"🚗 <b>{get_preview_val('brand', brand)} {get_preview_val('model', model)}</b>",
                f"💰 Precio: {get_preview_val('price', price)}",
                f"📅 Año: {get_preview_val('year', year)}",
                f"⛽ Combustible: {get_preview_val('fuel', fuel)}",
                f"🔧 Transmisión: {get_preview_val('transmission', transmission)}",
                f"📏 Km: {get_preview_val('km', km)}",
                f"🐴 Potencia: {cv_display if cv != 'N/D' else 'N/D CV'}",
                f"📸 Imágenes: {exterior_count} ext. + {len(sorted_interiors)} int.",
                f"🏷️ Logo: {'✅ Detectado' if find_brand_logo(brand) else '⚠️ No encontrado'}",
            ]
            if include_description:
                lines.append(f"\n📝 <b>Descripción:</b>\n<i>{vehicle_data.get('description', 'Sin descripción')}</i>\n")
            
            lines.append("\n<i>¿Es correcta la información? Pulsa Confirmar para publicar en la web.</i>")
            return lines

        preview_caption = "\n".join(build_preview_lines(include_description=True))

        # Borrar el mensaje de estado para no saturar el chat
        try:
            await bot.delete_message(chat_id, status_msg.message_id)
        except Exception:
            pass

        # Si el caption es demasiado largo para Telegram (límite 1024 caracteres), se envía la descripción por separado
        if len(preview_caption) > 1000:
            preview_caption = "\n".join(build_preview_lines(include_description=False))

            # Enviar foto con ficha básica
            preview_msg = await bot.send_photo(
                chat_id=chat_id,
                photo=open(preview_image, "rb"),
                caption=preview_caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
            # Enviar descripción en mensaje de texto complementario (soportando chunking)
            desc_msgs = await send_message_chunked(
                bot=bot,
                chat_id=chat_id,
                text=f"📝 <b>Descripción completa:</b>\n{vehicle_data.get('description', 'Sin descripción')}",
                parse_mode="HTML"
            )
            context.user_data["pending_vehicle"]["description_message_ids"] = [msg.message_id for msg in desc_msgs]
        else:
            preview_msg = await bot.send_photo(
                chat_id=chat_id,
                photo=open(preview_image, "rb"),
                caption=preview_caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )

        context.user_data["pending_vehicle"]["preview_message_id"] = preview_msg.message_id

    except Exception as e:
        logger.error(f"Error procesando vehículo: {e}", exc_info=True)
        try:
            await bot.edit_message_text(
                f"❌ <b>Error al procesar el vehículo:</b>\n<code>{e}</code>",
                chat_id,
                status_msg.message_id,
                parse_mode="HTML",
            )
        except Exception:
            await bot.send_message(chat_id, f"❌ Error: {e}")

        # Limpiar archivos temporales en caso de error
        for img_path in image_paths:
            try:
                img_path.unlink(missing_ok=True)
            except OSError:
                pass


def _sort_images_by_classification(image_paths: list[Path], classification: dict | None) -> tuple[Path | None, list[Path | None], list[Path]]:
    """
    Ordena las imágenes según la clasificación de Gemini.
    Devuelve (principal_con_fondo, sorted_exteriors, sorted_interiors).
    """
    n = len(image_paths)
    if not classification or "classified_images" not in classification:
        main_img = image_paths[0] if n > 0 else None
        exteriors = [None, None, main_img, None, None]
        interiors = image_paths[1:] if n > 1 else []
        return main_img, exteriors, interiors

    ci = classification["classified_images"]
    if not ci:
        main_img = image_paths[0] if n > 0 else None
        exteriors = [None, None, main_img, None, None]
        interiors = image_paths[1:] if n > 1 else []
        return main_img, exteriors, interiors

    # Helper para obtener Path por índice 1-based
    def get_path_by_index(idx) -> Path | None:
        if idx is None:
            return None
        try:
            idx_int = int(idx)
            if 1 <= idx_int <= n:
                return image_paths[idx_int - 1]
        except (ValueError, TypeError):
            pass
        return None

    frontal = get_path_by_index(ci.get("frontal"))
    frontolateral = get_path_by_index(ci.get("frontolateral"))
    principal_con_fondo = get_path_by_index(ci.get("principal_con_fondo"))
    lateral_izquierdo = get_path_by_index(ci.get("lateral_izquierdo"))
    lateral_derecho = get_path_by_index(ci.get("lateral_derecho"))

    if not principal_con_fondo and n > 0:
        principal_con_fondo = frontolateral or frontal or image_paths[0]

    assigned_paths = {frontal, frontolateral, principal_con_fondo, lateral_izquierdo, lateral_derecho}
    assigned_paths.discard(None)

    interiors = []
    interior_indices = ci.get("interior", [])
    if isinstance(interior_indices, list):
        for idx in interior_indices:
            p = get_path_by_index(idx)
            if p and p not in assigned_paths:
                interiors.append(p)
                assigned_paths.add(p)

    # Añadir cualquier otra foto no asignada a interiores
    for path in image_paths:
        if path not in assigned_paths:
            interiors.append(path)

    sorted_exteriors = [frontal, frontolateral, principal_con_fondo, lateral_izquierdo, lateral_derecho]
    return principal_con_fondo, sorted_exteriors, interiors


def _cleanup_pending_vehicle(context: ContextTypes.DEFAULT_TYPE):
    """Elimina archivos temporales y datos de cualquier anuncio pendiente en memoria."""
    if context.user_data is None:
        return
    pending = context.user_data.pop("pending_vehicle", None)
    if pending:
        # Intentar borrar archivos locales
        for img_path_str in pending.get("image_paths", []):
            try:
                Path(img_path_str).unlink(missing_ok=True)
            except OSError:
                pass
        logger.info("Publicación pendiente anterior limpiada correctamente.")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja las interacciones de los botones (publicación y agente IA)."""
    query = update.callback_query

    user_id = update.effective_user.id
    if not is_admin(user_id):
        await query.answer("⛔ No autorizado.")
        return

    action = query.data

    # Callbacks del agente IA (prefijo agent_)
    if action.startswith("agent_") and agent:
        await agent.handle_callback(update, context)
        return

    # Callbacks de publicación de vehículos
    await query.answer()
    if action == "publish_confirm":
        await _publish_pending_vehicle(update, context)
    elif action == "publish_cancel":
        await _cancel_pending_vehicle(update, context)


async def _publish_pending_vehicle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fase 2: Sube las imágenes procesadas a Storage y guarda en Firestore."""
    query = update.callback_query
    if context.user_data is None:
        await query.edit_message_caption(
            caption="⚠️ Error: No se pudo acceder a los datos de la sesión.",
            reply_markup=None,
        )
        return
    pending = context.user_data.pop("pending_vehicle", None)

    if not pending:
        await query.edit_message_caption(
            caption="⚠️ No hay ninguna publicación pendiente o ya expiró.",
            reply_markup=None,
        )
        return

    vehicle_data = pending["vehicle_data"]
    main_image_path = Path(pending["main_image_path"]) if pending.get("main_image_path") else None
    sorted_exterior_paths = [Path(p) if p else None for p in pending.get("sorted_exterior_paths", [])]
    sorted_interior_paths = [Path(p) for p in pending.get("sorted_interior_paths", [])]
    image_paths = [Path(p) for p in pending["image_paths"]]
    brand = pending["brand"]
    model = pending["model"]
    chat_id = pending["chat_id"]

    # Editar el mensaje para mostrar estado de carga
    await query.edit_message_caption(
        caption="📤 <b>Subiendo imágenes y publicando en la web...</b>",
        parse_mode="HTML",
        reply_markup=None,
    )

    try:
        # ── Paso 3: Subir imágenes a Firebase Storage ──
        safe_brand = brand.replace(" ", "_")
        safe_model = model.replace(" ", "_")

        loop = asyncio.get_event_loop()
        upload_tasks = []

        # 1. Definir tarea para imagen principal
        main_image_exists = bool(main_image_path and main_image_path.exists())
        if main_image_exists:
            upload_tasks.append(
                loop.run_in_executor(None, firebase.upload_image, main_image_path, safe_brand, safe_model, "main")
            )

        # 2. Definir tareas para imágenes exteriores ordenadas
        exterior_indices = []
        for i, path in enumerate(sorted_exterior_paths):
            if path and path.exists():
                upload_tasks.append(
                    loop.run_in_executor(None, firebase.upload_image, path, safe_brand, safe_model, f"exterior_{i}")
                )
                exterior_indices.append(i)

        # 3. Definir tareas para imágenes interiores ordenadas
        interior_count = 0
        for i, path in enumerate(sorted_interior_paths):
            if path and path.exists():
                upload_tasks.append(
                    loop.run_in_executor(None, firebase.upload_image, path, safe_brand, safe_model, f"interior_{i}")
                )
                interior_count += 1

        # 4. Definir tarea para buscar y subir logo de la marca
        logo_path = find_brand_logo(brand)
        logo_exists = bool(logo_path)
        if logo_exists:
            upload_tasks.append(
                loop.run_in_executor(None, firebase.upload_image, logo_path, safe_brand, safe_model, "logo")
            )

        # Ejecutar todas las subidas en paralelo
        uploaded_urls = await asyncio.gather(*upload_tasks)

        # Mapear las URLs devueltas a sus respectivas variables
        url_idx = 0
        
        main_url = ""
        if main_image_exists:
            main_url = uploaded_urls[url_idx]
            url_idx += 1

        gallery_exterior: list[str | None] = [None, None, None, None, None]
        for i in exterior_indices:
            gallery_exterior[i] = uploaded_urls[url_idx]
            url_idx += 1

        gallery_interior: list[str] = []
        for _ in range(interior_count):
            gallery_interior.append(uploaded_urls[url_idx])
            url_idx += 1

        logo_url = ""
        if logo_exists:
            logo_url = uploaded_urls[url_idx]
            url_idx += 1
            logger.info(f"Logo subido: {logo_path.name}")

        # ── Paso 5: Construir documento final ──
        vehicle_data["image"] = main_url
        vehicle_data["logo"] = logo_url
        vehicle_data["galleryExterior"] = gallery_exterior
        vehicle_data["galleryInterior"] = gallery_interior

        vehicle_data["sold"] = False
        vehicle_data["order"] = int(datetime.now().timestamp() * 1000)
        vehicle_data.setdefault("logoSize", 100)
        vehicle_data.setdefault("logoMargin", "")
        vehicle_data.setdefault("logoClass", "")

        # ── Paso 6: Escribir en Firestore ──
        doc_id = vehicle_data.get("id", f"{safe_brand}-{safe_model}").lower()
        doc_id = doc_id.replace(" ", "-")
        vehicle_data["id"] = doc_id

        firebase.add_vehicle(doc_id, vehicle_data)

        # ── Paso 7: Limpieza de archivos temporales ──
        for img_path in image_paths:
            try:
                img_path.unlink(missing_ok=True)
            except OSError:
                pass

        # ── Paso 8: Confirmación final ──
        detail_url = f"https://autosjveloce.com/Coches/detalle.html?id={doc_id}"

        import html
        safe_brand = html.escape(brand)
        safe_model = html.escape(model)
        safe_price = html.escape(str(vehicle_data.get("price", "N/D")))
        safe_year = html.escape(str(vehicle_data.get("year", "N/D")))
        safe_fuel = html.escape(str(vehicle_data.get("fuel", "N/D")))
        safe_transmission = html.escape(str(vehicle_data.get("transmission", "N/D")))
        safe_km = html.escape(str(vehicle_data.get("km", "N/D")))
        safe_cv = html.escape(str(vehicle_data.get("cv", "N/D")))
        safe_doc_id = html.escape(doc_id)

        total_uploaded = (1 if main_url else 0) + len([u for u in gallery_exterior if u]) + len(gallery_interior)

        summary_lines = [
            "✅ <b>¡Vehículo publicado con éxito!</b>\n",
            f"🚗 <b>{safe_brand} {safe_model}</b>",
            f"💰 Precio: {safe_price}",
            f"📅 Año: {safe_year}",
            f"⛽ Combustible: {safe_fuel}",
            f"🔧 Transmisión: {safe_transmission}",
            f"📏 Km: {safe_km}",
            f"🐴 Potencia: {safe_cv} CV",
            f"📸 Imágenes: {total_uploaded} subidas",
            f"🏷️ Logo: {'✅ Asignado' if logo_url else '⚠️ No encontrado'}",
            f"\n🔗 <a href=\"{detail_url}\">Ver en la web</a>",
            f"\n📝 ID: <code>{safe_doc_id}</code>",
        ]

        await query.edit_message_caption(
            caption="\n".join(summary_lines),
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"Error publicando vehículo: {e}", exc_info=True)
        await query.edit_message_caption(
            caption=f"❌ <b>Error al publicar en Firebase:</b>\n<code>{e}</code>",
            parse_mode="HTML",
            reply_markup=None,
        )
        # Limpieza en caso de error
        for img_path in image_paths:
            try:
                img_path.unlink(missing_ok=True)
            except OSError:
                pass


async def _cancel_pending_vehicle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela la publicación pendiente y limpia los recursos."""
    query = update.callback_query
    if context.user_data is None:
        await query.edit_message_caption(
            caption="⚠️ Error: No se pudo acceder a los datos de la sesión.",
            reply_markup=None,
        )
        return
    pending = context.user_data.pop("pending_vehicle", None)

    if not pending:
        await query.edit_message_caption(
            caption="⚠️ No hay ninguna publicación pendiente o ya expiró.",
            reply_markup=None,
        )
        return

    # Limpiar archivos temporales
    image_paths = [Path(p) for p in pending["image_paths"]]
    for img_path in image_paths:
        try:
            img_path.unlink(missing_ok=True)
        except OSError:
            pass

    # Borrar el mensaje de descripción complementaria si existe (soportando chunking)
    desc_msg_ids = pending.get("description_message_ids", [])
    if pending.get("description_message_id"):
        desc_msg_ids.append(pending["description_message_id"])
    for msg_id in desc_msg_ids:
        try:
            await context.bot.delete_message(pending["chat_id"], msg_id)
        except Exception:
            pass

    await query.edit_message_caption(
        caption="❌ <b>Publicación cancelada.</b> Se han eliminado los archivos temporales.",
        parse_mode="HTML",
        reply_markup=None,
    )


def _escape_md(text: str) -> str:
    """Escapa caracteres especiales de MarkdownV2."""
    if not text:
        return ""
    special_chars = r"_*[]()~`>#+-=|{}.!"
    escaped = ""
    for char in str(text):
        if char in special_chars:
            escaped += f"\\{char}"
        else:
            escaped += char
    return escaped


# ─── Main ────────────────────────────────────────────────────────────────────


def main():
    """Punto de entrada principal del bot."""
    logger.info("=" * 50)
    logger.info("🚗 Bot JVeloce - Iniciando...")
    logger.info("=" * 50)

    # Inicializar clientes externos
    init_clients()

    # Crear aplicación de Telegram
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # ── Inyectar dependencias en bot_data para el monitor de Facebook ──
    application.bot_data["firebase"] = firebase
    application.bot_data["gemini"] = gemini
    application.bot_data["admin_id"] = ADMIN_TELEGRAM_ID
    application.bot_data["fb_state_manager"] = fb_state_manager
    # Función de procesamiento de vehículos reutilizable por el monitor de FB
    application.bot_data["process_vehicle_from_data_fn"] = _process_vehicle

    # Registrar handlers
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("listar", cmd_listar))
    application.add_handler(CommandHandler("eliminar", cmd_eliminar))
    application.add_handler(CommandHandler("estado", cmd_estado))
    application.add_handler(CommandHandler("check_fb", cmd_check_fb))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_description))
    application.add_handler(
        MessageHandler(
            filters.Document.ALL & ~filters.COMMAND,
            handle_document_description
        )
    )
    application.add_handler(CallbackQueryHandler(handle_callback))

    # ── Registrar job periódico del monitor de Facebook Marketplace ──
    if ADMIN_TELEGRAM_ID != 0:
        # Primera comprobación a los 30s del inicio (para el primer arranque / marcado inicial)
        application.job_queue.run_once(
            check_facebook_marketplace_job,
            when=30,
            name="fb_marketplace_first_check",
        )
        # Comprobaciones periódicas cada CHECK_INTERVAL_SECONDS (15 min)
        application.job_queue.run_repeating(
            check_facebook_marketplace_job,
            interval=CHECK_INTERVAL_SECONDS,
            first=CHECK_INTERVAL_SECONDS,  # Primera ejecución periódica tras 15 min
            name="fb_marketplace_monitor",
        )
        logger.info(
            f"✅ Monitor de Facebook Marketplace activo "
            f"(intervalo: {CHECK_INTERVAL_SECONDS // 60} min, primera comprobación en 30s)."
        )
    else:
        logger.warning(
            "⚠️  ADMIN_TELEGRAM_ID=0 → Monitor de Facebook Marketplace desactivado. "
            "Configura tu ID en .env para activar las notificaciones automáticas."
        )

    # Iniciar polling
    logger.info("🤖 Bot listo. Esperando mensajes...")
    if ADMIN_TELEGRAM_ID == 0:
        logger.warning(
            "⚠️  ADMIN_TELEGRAM_ID=0 → Cualquier usuario puede usar el bot. "
            "Configura tu ID en .env para restringir el acceso."
        )

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
