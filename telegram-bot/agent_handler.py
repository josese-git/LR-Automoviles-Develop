"""
agent_handler.py - Agente de IA conversacional para gestión del inventario JVeloce
Usa su propia instancia de Gemini, separada del cliente de parsing de anuncios.
Interpreta lenguaje natural y ejecuta acciones sobre la base de datos de vehículos.
"""

import json
import logging
import re
import uuid
import html
import time
from typing import List, Optional
from pydantic import BaseModel, Field

from google import genai
from google.genai import types, errors
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from gemini_client import GeminiKeyManager

logger = logging.getLogger("JVeloceAgent")

class AgentAction(BaseModel):
    action: str = Field(description="Acción a realizar: 'update_field', 'mark_sold', 'mark_available', 'delete', 'list', 'info', 'count', 'chat', 'unknown'")
    target_id: Optional[str] = Field(None, description="ID del vehículo objetivo si es único. De lo contrario, null.")
    target_candidates: List[str] = Field(default_factory=list, description="Lista de IDs de vehículos candidatos si hay múltiples coincidencias.")
    field: Optional[str] = Field(None, description="Campo a modificar para 'update_field': 'price', 'description', 'km', 'year', 'fuel', 'transmission', 'cv', 'brand', 'model'")
    new_value: Optional[str] = Field(None, description="Nuevo valor del campo para 'update_field'.")
    filter: Optional[str] = Field(None, description="Filtro para 'list' o 'count': 'all', 'sold', 'available'")
    response: Optional[str] = Field(None, description="Respuesta conversacional para la acción 'chat' o 'unknown'.")
    summary: str = Field(description="Resumen en texto profesional de la acción a realizar.")



# ─── Utilidad de mensajes chunked (evita import circular con bot.py) ─────────

async def _send_chunked(bot, chat_id: int, text: str, parse_mode: str = None, **kwargs):
    """Envía texto largo dividiéndolo en partes de máximo 4000 caracteres."""
    if len(text) <= 4000:
        return [await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode, **kwargs)]

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
            current_chunk = f"{current_chunk}\n{line}" if current_chunk else line

    if current_chunk:
        chunks.append(current_chunk.strip())

    sent = []
    for chunk in chunks:
        msg = await bot.send_message(chat_id=chat_id, text=chunk, parse_mode=parse_mode, **kwargs)
        sent.append(msg)
    return sent

# ─── Constantes ──────────────────────────────────────────────────────────────

MAX_HISTORY = 20  # Máximo de mensajes a guardar en el historial de conversación

# ─── System Prompt del Agente ────────────────────────────────────────────────

AGENT_SYSTEM_PROMPT = """Eres "JVeloce AI", el asistente de gestión personal del concesionario de alta gama y deportivos "Autos JVeloce". 
Tu dueño te habla por Telegram en español y tú gestionas el inventario de coches de la web.

INVENTARIO ACTUAL (se te proporciona en cada mensaje):
Se te dará la lista de vehículos actuales en formato JSON (incluyendo sus especificaciones y la descripción de cada uno) para que puedas entender a qué coche se refiere el usuario, consultar sus datos y descripciones actuales, o editarlos.

HISTORIAL DE CONVERSACIÓN:
Se te proporcionará el historial reciente de la conversación para que puedas entender el contexto.
USA EL HISTORIAL para entender referencias como "ese coche", "ponle 5000€", "sí", "8390€", etc.
Si el usuario da un precio suelto como "8390€" y en el historial se habló de cambiar el precio de un coche, ENTIENDE que quiere poner ese precio a ESE coche.

TU TAREA:
Analiza el mensaje del usuario JUNTO CON EL HISTORIAL y devuelve EXCLUSIVAMENTE un JSON con la acción a realizar.

ACCIONES DISPONIBLES:

1. "update_field" — Cambiar un campo de un vehículo (¡Incluyendo la descripción!)
   Campos modificables: price, km, year, fuel, transmission, cv, description, brand, model
   {
     "action": "update_field",
     "target_id": "id-del-vehiculo-si-es-unico",
     "target_candidates": [],
     "field": "price" | "description" | "km" | "year" | "fuel" | "transmission" | "cv" | "brand" | "model",
     "new_value": "Nuevo valor (si es precio: '5.000€', si es descripción: el texto completo de la descripción, etc.)",
     "summary": "Resumen en texto profesional (ej: 'Actualizar la descripción del Kia Sportage')"
   }

2. "mark_sold" — Marcar un vehículo como vendido
   {
     "action": "mark_sold",
     "target_id": "id-del-vehiculo",
     "target_candidates": [],
     "summary": "Marcar el Peugeot 3008 2017 como vendido"
   }

3. "mark_available" — Marcar un vehículo como en venta (des-vender)
   {
     "action": "mark_available",
     "target_id": "id-del-vehiculo",
     "target_candidates": [],
     "summary": "Poner el Mercedes Clase A otra vez en venta"
   }

4. "delete" — Eliminar un vehículo del inventario
   {
     "action": "delete",
     "target_id": "id-del-vehiculo",
     "target_candidates": [],
     "summary": "Eliminar el anuncio del Ford Focus 2015"
   }

5. "list" — Listar todo el inventario o filtrado
   {
     "action": "list",
     "filter": "all" | "sold" | "available",
     "summary": "Listar todos los vehículos en venta"
   }

6. "search" / "info" — Buscar o dar datos de un vehículo (¡INCLUYE LA DESCRIPCIÓN si te piden ver la descripción, el anuncio o la ficha completa!)
   {
     "action": "info",
     "target_id": "id-del-vehiculo",
     "target_candidates": [],
     "summary": "Mostrar datos detallados del Seat Ibiza 2019"
   }

7. "count" — Contar vehículos
   {
     "action": "count",
     "filter": "all" | "sold" | "available",
     "summary": "Contar cuántos coches están en venta"
   }

8. "chat" — Respuesta conversacional (saludos, preguntas generales, preguntas de seguimiento donde necesitas más info del usuario, o cuando te piden la descripción de un coche y quieres responder con ella)
   {
     "action": "chat",
     "response": "Respuesta dinámica y atenta (ej: 'Entendido, Julio. ¿Qué precio le ponemos al MINI Cooper Cabrio para publicarlo?')",
     "summary": "Pregunta de seguimiento para obtener el precio"
   }

9. "unknown" — SOLO cuando el mensaje no tiene NADA que ver con la gestión de coches ni con la conversación en curso
   {
     "action": "unknown",
     "response": "Lo siento, no he entendido esa petición. ¿En qué puedo ayudarte con el catálogo?",
     "summary": "Petición no entendida"
   }

PERSONALIDAD Y ESTILO DE COMUNICACIÓN (PROFESIONAL, DINÁMICO Y MODERADAMENTE DEPORTIVO):
- **Tono Profesional y Elegante**: Refleja el espíritu de Autos JVeloce (concesionario premium de vehículos de ocasión y deportivos). Sé atento, educado y profesional, pero con una energía positiva, dinámica y ágil. Evita sonar aburrido u oficinesco.
- **Moderación Deportiva**: Evita caer en la exageración o caricatura. No uses frases hechas de carreras o coches ("quemar asfalto", "boxes", "rugido", "pisar el acelerador") de forma repetitiva o forzada. Sé sutil: usa de vez en cuando un toque dinámico y elegante (ej: "listo para entrega", "en perfecto estado", "listo para rodar", "a toda marcha").
- **Trato al dueño**: Trata al usuario de forma cercana y profesional (puedes llamarle "jefe" de forma natural y respetuosa, o tutearle amistosamente).
- **Descripciones vacías**: Si el usuario te pregunta por la descripción de un coche y ves que en el inventario actual su `"description"` está vacía o es `"Sin descripción"`, explícale con total claridad y educación: "La descripción en la base de datos está vacía, jefe (aunque en la web se mostrará el texto automático por defecto: '[Marca] [Modelo] [Año] en excelente estado'). ¿Quieres que redacte una descripción atractiva para este coche?"
- **Enfoque Comercial**: Describe los vehículos destacando sus cualidades reales (elegancia, fiabilidad, extras interesantes) de forma atractiva y comercial.
- **Enlaces a la web**: La estructura de enlaces para ver los detalles de cualquier vehículo en la web es: `https://autosjveloce.com/Coches/detalle.html?id=<id-del-coche>` (ej: `https://autosjveloce.com/Coches/detalle.html?id=peugeot-expert-2017`). Si el usuario te pide explícitamente el enlace de un vehículo en un mensaje conversacional (acción "chat"), puedes proporcionárselo directamente usando esa estructura.

REGLAS DE CONTEXTO CONVERSACIONAL (MUY IMPORTANTE):
- SIEMPRE lee el historial de conversación antes de decidir la acción.
- Si el usuario responde con un dato suelto (ej: "8.390€", "2019", "vendido"), MIRA el historial para entender a qué se refiere.
- Si en el historial el asistente preguntó "¿qué precio le ponemos al MINI Cooper?", y el usuario dice "8.390€", la acción es "update_field" con field="price", new_value="8.390€" y target_id del MINI Cooper.
- Si el usuario te pide la descripción de un coche, puedes responder con la acción "chat" conteniendo la descripción de forma entusiasta, o simplemente usar "info" si quieres mostrar toda la tarjeta.
- Si necesitas más información del usuario para completar una acción, usa "chat" con una pregunta enérgica pero profesional.

REGLAS DE DESAMBIGUACIÓN:
- Si el usuario menciona un coche y hay EXACTAMENTE 1 coincidencia en el inventario → usa "target_id" con el ID de ese vehículo, deja "target_candidates" vacío.
- Si hay MÚLTIPLES coincidencias (ej: 2 Nissan Qashqai de años distintos) → deja "target_id" como null y rellena "target_candidates" con la lista de IDs candidatos.
- Si NO hay coincidencias → responde con action "chat" explicando con estilo atento que no he encontrado ese vehículo en la base de datos.

REGLAS ESTRICTAS:
1. Devuelve SOLO JSON puro. Sin bloques de código, sin texto adicional.
2. El campo "summary" es obligatorio en TODAS las acciones. Resume en lenguaje humano y estilo profesional lo que vas a hacer.
3. Para "update_field", el "new_value" debe estar en el formato correcto:
   - Precio: con formato español y € (ej: "5.000€")
   - Km: con formato y unidad (ej: "120.000 Km")
   - Año: string (ej: "2019")
   - Combustible: "Gasolina", "Diésel", "Híbrido", "Eléctrico"
   - Transmisión: "Manual" o "Auto"
   - CV: solo número string (ej: "150")
   - Description: el nuevo texto de la descripción completo.
4. Sé inteligente con los nombres: "el yaris" = Toyota Yaris, "el 3008" = Peugeot 3008, etc.
5. Si el usuario dice algo conversacional (hola, gracias, etc.), responde con "chat".
6. Responde SIEMPRE en español.
"""


class AgentHandler:
    """Agente de IA para gestión del inventario vía Telegram."""

    def __init__(self, key_manager: GeminiKeyManager | str, firebase_client):
        """
        Inicializa el agente con su propia instancia de Gemini.

        Args:
            key_manager: Instancia de GeminiKeyManager o clave simple de API.
            firebase_client: Instancia de FirebaseClient para operaciones de datos.
        """
        if isinstance(key_manager, str):
            self.key_manager = GeminiKeyManager([key_manager])
        else:
            self.key_manager = key_manager
            
        self.model_name = "gemini-2.5-flash"
        self.fallback_models = [
            "gemini-3.5-flash"
        ]
        self.firebase = firebase_client
        logger.info("✅ Agente IA inicializado con soporte de rotación de claves.")

    # ─── Punto de entrada principal ──────────────────────────────────────────

    async def process_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE, override_text: str = None):
        """
        Procesa un mensaje de texto del usuario como comando de gestión.
        Interpreta con Gemini usando el historial de conversación.
        """
        user_message = override_text if override_text is not None else update.message.text
        chat_id = update.effective_chat.id

        if not self.firebase:
            await update.message.reply_text(
                "❌ Firebase no está conectado. No puedo gestionar el inventario."
            )
            return

        # Indicador de "escribiendo..."
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        # Obtener inventario actual para contexto
        try:
            inventory = self.firebase.list_vehicles()
        except Exception as e:
            await update.message.reply_text(f"❌ Error al obtener el inventario: {e}")
            return

        # Obtener historial de conversación
        history = context.user_data.get("agent_history", [])

        # Añadir el mensaje del usuario al historial
        history.append({"role": "user", "text": user_message})

        # Comprobar si es un mensaje de voz
        is_voice = context.user_data.get("reply_with_voice", False)

        # Interpretar con Gemini (incluyendo historial)
        action_data = self._interpret_message(user_message, inventory, history, is_voice=is_voice)

        if not action_data:
            await update.message.reply_text(
                "❌ No pude procesar tu mensaje. Inténtalo de nuevo."
            )
            return

        # Ejecutar la acción y obtener la respuesta del agente
        agent_response = await self._execute_action(update, context, action_data, inventory)

        # Guardar la respuesta del agente en el historial
        if agent_response:
            history.append({"role": "assistant", "text": agent_response})

        # Truncar historial si es demasiado largo
        if len(history) > MAX_HISTORY:
            history = history[-MAX_HISTORY:]

        # Guardar historial actualizado
        context.user_data["agent_history"] = history

    # ─── Interpretación con Gemini ───────────────────────────────────────────

    def _interpret_message(self, user_message: str, inventory: list[dict], history: list[dict] = None, is_voice: bool = False) -> dict | None:
        """
        Envía el mensaje del usuario + inventario + historial a Gemini para interpretar la acción.
        """
        # Construir resumen del inventario (compacto) para el contexto
        inventory_summary = []
        for v in inventory:
            status = "VENDIDO" if v.get("sold") else "EN VENTA"
            inventory_summary.append({
                "id": v["id"],
                "brand": v.get("brand", "?"),
                "model": v.get("model", "?"),
                "year": v.get("year", "?"),
                "price": v.get("price", "N/D"),
                "km": v.get("km", "N/D"),
                "fuel": v.get("fuel", "N/D"),
                "transmission": v.get("transmission", "N/D"),
                "cv": v.get("cv", "N/D"),
                "sold": v.get("sold", False),
                "status": status,
                "description": v.get("description", "Sin descripción"),
            })

        # Construir historial de conversación para el prompt
        history_text = ""
        if history and len(history) > 1:  # Solo incluir si hay más de solo el mensaje actual
            history_lines = []
            # Excluir el último mensaje (es el actual del usuario, ya va en MENSAJE DEL USUARIO)
            for msg in history[:-1]:
                role_label = "USUARIO" if msg["role"] == "user" else "ASISTENTE"
                history_lines.append(f"[{role_label}]: {msg['text']}")
            history_block = "\n".join(history_lines)
            history_text = f"HISTORIAL DE CONVERSACIÓN RECIENTE:\n{history_block}\n\n"

        prompt = (
            f"INVENTARIO ACTUAL ({len(inventory)} vehículos):\n"
            f"{json.dumps(inventory_summary, ensure_ascii=False, indent=2)}\n\n"
            f"{history_text}"
            f"MENSAJE DEL USUARIO:\n{user_message}\n\n"
            f"Devuelve EXCLUSIVAMENTE el JSON de la acción a realizar:"
        )

        try:
            models_to_try = [self.model_name] + self.fallback_models
            if is_voice:
                # Si es voz, anteponer modelos más rápidos
                models_to_try = ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite"] + models_to_try
                
            response = None
            
            for current_model in models_to_try:
                num_keys = len(self.key_manager.api_keys)
                max_attempts = max(3, num_keys * 2)
                backoff_factor = 2
                model_503_count = 0
                
                logger.info(f"Agente intentando generar contenido con modelo: {current_model}")
                
                success = False
                for attempt in range(max_attempts):
                    client, key_idx, all_exhausted = self.key_manager.get_client()
                    if all_exhausted:
                        logger.warning("Todas las llaves están temporalmente agotadas en el Agente. Esperando 2 segundos...")
                        time.sleep(2.0)

                    try:
                        response = client.models.generate_content(
                            model=current_model,
                            contents=[types.Part.from_text(text=prompt)],
                            config=types.GenerateContentConfig(
                                system_instruction=AGENT_SYSTEM_PROMPT,
                                temperature=0.1,
                                response_mime_type="application/json",
                                response_schema=AgentAction,
                            ),
                        )
                        success = True
                        break
                    except errors.APIError as e:
                        if e.code == 429:
                            self.key_manager.mark_exhausted(key_idx)
                            if num_keys > 1:
                                logger.warning(
                                    f"Llave {key_idx} falló con error 429 en Agente usando {current_model}. "
                                    "Rotando llave e intentando de nuevo en 1.0s..."
                                )
                                time.sleep(1.0)
                                continue
                        elif e.code == 401:
                            self.key_manager.mark_invalid(key_idx)
                            if num_keys > 1:
                                logger.warning(
                                    f"Llave {key_idx} falló con error 401 en Agente usando {current_model}. "
                                    "Rotando llave e intentando de nuevo en 0.1s..."
                                )
                                time.sleep(0.1)
                                continue
                        elif e.code == 503:
                            model_503_count += 1
                            if model_503_count >= 3:
                                logger.error(
                                    f"Error 503 recurrente ({model_503_count} veces) para {current_model} en el Agente. "
                                    "Pasando al siguiente modelo fallback de inmediato."
                                )
                                break
                            
                            sleep_time = backoff_factor ** (attempt % 3 + 1)
                            logger.warning(
                                f"Agente Gemini error 503 usando {current_model} (intento {attempt + 1}/{max_attempts}). "
                                f"Reintentando en {sleep_time}s..."
                            )
                            time.sleep(sleep_time)
                            continue
                        
                        # Si es otro código de error (ej: 404, 400, etc.) o se agotaron los intentos
                        logger.error(f"Error definitivo Agente con modelo {current_model} en intento {attempt+1}: {e}")
                        break
                            
                if success:
                    break

            if not response or not response.text:
                logger.error("Gemini Agent devolvió respuesta vacía.")
                return None

            raw_text = response.text.strip()
            logger.info(f"Agente Gemini respuesta: {raw_text[:500]}")

            return self._extract_json(raw_text)

        except Exception as e:
            logger.error(f"Error del agente Gemini: {e}", exc_info=True)
            return None

    def _extract_json(self, text: str) -> dict | None:
        """Extrae JSON de la respuesta de Gemini."""
        # Intento 1: Directo
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Intento 2: Bloque de código
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Intento 3: Primer { ... }
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        logger.error(f"No se pudo extraer JSON del agente: {text}")
        return None

    # ─── Ejecución de acciones ───────────────────────────────────────────────

    async def _execute_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action_data: dict, inventory: list[dict]) -> str | None:
        """
        Router principal de acciones del agente.
        Devuelve el texto de respuesta del agente para guardarlo en el historial.
        """
        action = action_data.get("action", "unknown")

        if action == "chat":
            return await self._action_chat(update, context, action_data)
        elif action == "unknown":
            return await self._action_unknown(update, context, action_data)
        elif action == "list":
            return await self._action_list(update, context, action_data, inventory)
        elif action == "count":
            return await self._action_count(update, action_data, inventory)
        elif action in ("info", "search"):
            return await self._action_info(update, action_data, inventory)
        elif action in ("update_field", "mark_sold", "mark_available", "delete"):
            return await self._action_with_confirmation(update, context, action_data, inventory)
        else:
            await update.message.reply_text(
                f"🤔 Acción no reconocida: `{action}`",
                parse_mode="Markdown",
            )
            return None

    # ─── Acciones de solo lectura ────────────────────────────────────────────

    async def _reply_maybe_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, prefix: str = "🤖 ") -> str:
        reply_with_voice = context.user_data.pop("reply_with_voice", False)
        if reply_with_voice:
            try:
                import edge_tts
                import uuid
                from pathlib import Path
                
                temp_dir = Path(__file__).parent / "temp_images"
                temp_dir.mkdir(exist_ok=True)
                audio_path = temp_dir / f"reply_{uuid.uuid4().hex}.mp3"
                
                communicate = edge_tts.Communicate(text, "es-ES-AlvaroNeural")
                await communicate.save(str(audio_path))
                
                with open(audio_path, 'rb') as voice_file:
                    await update.message.reply_voice(voice=voice_file, caption=f"{prefix}{text}")
                
                try:
                    audio_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return text
            except Exception as e:
                logger.error(f"Error generando audio con edge-tts: {e}", exc_info=True)
                # Fallback a texto
        
        await update.message.reply_text(f"{prefix}{text}")
        return text

    async def _action_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action_data: dict) -> str:
        """Respuesta conversacional."""
        response = action_data.get("response", "¡Hola! ¿En qué puedo ayudarte?")
        return await self._reply_maybe_voice(update, context, response)

    async def _action_unknown(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action_data: dict) -> str:
        """Acción no entendida."""
        response = action_data.get("response", "No he entendido tu petición.")
        return await self._reply_maybe_voice(update, context, response, prefix="🤔 ")

    async def _action_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action_data: dict, inventory: list[dict]) -> str:
        """Lista el inventario con filtro opcional."""
        filter_type = action_data.get("filter", "all")

        if filter_type == "sold":
            filtered = [v for v in inventory if v.get("sold")]
            title = "🔴 Vehículos VENDIDOS"
        elif filter_type == "available":
            filtered = [v for v in inventory if not v.get("sold")]
            title = "🟢 Vehículos EN VENTA"
        else:
            filtered = inventory
            title = "🚗 Inventario completo"

        if not filtered:
            msg = f"{title}\n\n📭 No hay vehículos en esta categoría."
            await update.message.reply_text(msg)
            return msg

        lines = [f"<b>{title}</b> ({len(filtered)} coches)\n"]
        summary_parts = []
        for i, v in enumerate(filtered, 1):
            status = "🔴" if v.get("sold") else "🟢"
            brand = html.escape(v.get("brand", "?"))
            model = html.escape(v.get("model", "?"))
            year = html.escape(str(v.get("year", "?")))
            price = html.escape(str(v.get("price", "N/D")))
            lines.append(f"{status} <b>{brand} {model}</b> ({year}) — {price}")
            summary_parts.append(f"{v.get('brand', '?')} {v.get('model', '?')} ({v.get('year', '?')})")

        text = "\n".join(lines)

        # Usar chunking si es largo
        await _send_chunked(context.bot, update.effective_chat.id, text, parse_mode="HTML")

        # Devolver resumen para el historial (sin HTML)
        return f"Listé {len(filtered)} vehículos: {', '.join(summary_parts)}"

    async def _action_count(self, update: Update, action_data: dict, inventory: list[dict]) -> str:
        """Cuenta vehículos con filtro opcional."""
        filter_type = action_data.get("filter", "all")

        total = len(inventory)
        en_venta = len([v for v in inventory if not v.get("sold")])
        vendidos = len([v for v in inventory if v.get("sold")])

        if filter_type == "sold":
            msg = f"Hay {vendidos} vehículo(s) vendido(s)."
            await update.message.reply_text(f"🔴 Hay <b>{vendidos}</b> vehículo(s) vendido(s).", parse_mode="HTML")
        elif filter_type == "available":
            msg = f"Hay {en_venta} vehículo(s) en venta."
            await update.message.reply_text(f"🟢 Hay <b>{en_venta}</b> vehículo(s) en venta.", parse_mode="HTML")
        else:
            msg = f"Total: {total} vehículos. En venta: {en_venta}. Vendidos: {vendidos}."
            await update.message.reply_text(
                f"📊 <b>Resumen del inventario:</b>\n\n"
                f"📦 Total: <b>{total}</b> vehículos\n"
                f"🟢 En venta: <b>{en_venta}</b>\n"
                f"🔴 Vendidos: <b>{vendidos}</b>",
                parse_mode="HTML",
            )
        return msg

    async def _action_info(self, update: Update, action_data: dict, inventory: list[dict]) -> str | None:
        """Muestra información detallada de un vehículo."""
        target_id = action_data.get("target_id")
        candidates = action_data.get("target_candidates", [])

        if not target_id and candidates:
            await self._send_disambiguation(
                update, candidates, action_data, inventory, is_info=True
            )
            return "Mostré opciones para desambiguar."

        if not target_id:
            await update.message.reply_text("🤔 No encontré ningún coche con esos datos.")
            return "No se encontró el coche."

        vehicle = self.firebase.get_vehicle(target_id)
        if not vehicle:
            await update.message.reply_text(
                f"❌ No se encontró el vehículo con ID: <code>{html.escape(target_id)}</code>",
                parse_mode="HTML",
            )
            return "Vehículo no encontrado."

        return await self._send_vehicle_card(update, vehicle)

    async def _send_vehicle_card(self, update: Update, vehicle: dict) -> str:
        """Envía una tarjeta con toda la información de un vehículo."""
        status = "🔴 VENDIDO" if vehicle.get("sold") else "🟢 EN VENTA"
        brand = html.escape(vehicle.get("brand", "?"))
        model = html.escape(vehicle.get("model", "?"))
        year = html.escape(str(vehicle.get("year", "?")))
        price = html.escape(str(vehicle.get("price", "N/D")))
        km = html.escape(str(vehicle.get("km", "N/D")))
        fuel = html.escape(str(vehicle.get("fuel", "N/D")))
        transmission = html.escape(str(vehicle.get("transmission", "N/D")))
        cv = html.escape(str(vehicle.get("cv", "N/D")))
        doc_id = html.escape(vehicle.get("id", "?"))
        raw_description = vehicle.get("description", "")
        if not raw_description or not raw_description.strip():
            description = f"<i>(Vacía en la base de datos. En la web se muestra por defecto: '{brand} {model} {year} en excelente estado')</i>"
        else:
            description = html.escape(raw_description)

        detail_url = f"https://autosjveloce.com/Coches/detalle.html?id={doc_id}"

        text = (
            f"🚗 <b>{brand} {model}</b> ({year})\n\n"
            f"💰 Precio: <b>{price}</b>\n"
            f"📅 Año: {year}\n"
            f"⛽ Combustible: {fuel}\n"
            f"🔧 Transmisión: {transmission}\n"
            f"📏 Km: {km}\n"
            f"🐴 Potencia: {cv} CV\n"
            f"📌 Estado: {status}\n\n"
            f"📝 <b>Descripción:</b>\n<i>{description}</i>\n\n"
            f"🔑 ID: <code>{doc_id}</code>\n"
            f"🔗 Enlace: <a href=\"{detail_url}\">{detail_url}</a>"
        )

        await update.message.reply_text(text, parse_mode="HTML")
        # Devolver resumen sin HTML para historial
        return f"Mostré info del {vehicle.get('brand', '?')} {vehicle.get('model', '?')} ({vehicle.get('year', '?')}): Precio {vehicle.get('price', 'N/D')}, {vehicle.get('km', 'N/D')}, {'VENDIDO' if vehicle.get('sold') else 'EN VENTA'}."

    # ─── Acciones con confirmación ───────────────────────────────────────────

    async def _action_with_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action_data: dict, inventory: list[dict]) -> str | None:
        """Maneja acciones que requieren confirmación (update, delete, mark_sold, etc.)."""
        target_id = action_data.get("target_id")
        candidates = action_data.get("target_candidates", [])

        # Caso 1: Múltiples candidatos → desambiguar
        if not target_id and candidates:
            await self._send_disambiguation(update, candidates, action_data, inventory)
            return "Mostré opciones para seleccionar el vehículo correcto."

        # Caso 2: Sin target → error
        if not target_id:
            await update.message.reply_text("🤔 No encontré ningún coche con esos datos en el inventario.")
            return "No se encontró el coche en el inventario."

        # Caso 3: Verificar que el vehículo existe
        vehicle = self.firebase.get_vehicle(target_id)
        if not vehicle:
            await update.message.reply_text(
                f"❌ No se encontró el vehículo con ID: <code>{html.escape(target_id)}</code>",
                parse_mode="HTML",
            )
            return "Vehículo no encontrado."

        # Generar confirmación
        await self._send_confirmation(update, context, action_data, vehicle)
        summary = action_data.get('summary', 'Acción pendiente de confirmación')
        return f"Pedí confirmación para: {summary}"

    async def _send_disambiguation(self, update: Update, candidate_ids: list[str], action_data: dict, inventory: list[dict], is_info: bool = False):
        """Muestra botones inline para seleccionar entre múltiples candidatos."""
        # Generar un action_id único para esta sesión
        action_id = str(uuid.uuid4())[:8]

        # Buscar los datos de cada candidato
        candidates = []
        for cid in candidate_ids:
            for v in inventory:
                if v["id"] == cid:
                    candidates.append(v)
                    break

        if not candidates:
            await update.message.reply_text("🤔 No encontré los vehículos candidatos.")
            return

        lines = ["🤔 <b>He encontrado varios vehículos que coinciden:</b>\n"]
        buttons = []

        for i, v in enumerate(candidates):
            status = "🔴" if v.get("sold") else "🟢"
            label = f"{v.get('brand', '?')} {v.get('model', '?')} ({v.get('year', '?')}) — {v.get('price', 'N/D')} {status}"
            lines.append(f"{i + 1}️⃣ {label}")
            callback_data = f"agent_select_{i}_{action_id}"
            buttons.append([InlineKeyboardButton(label, callback_data=callback_data)])

        buttons.append([InlineKeyboardButton("❌ Cancelar", callback_data=f"agent_cancel_{action_id}")])

        lines.append("\n<i>¿A cuál te refieres?</i>")

        # Guardar la acción pendiente en el almacén a nivel de módulo
        _pending_disambiguations[action_id] = {
            "action_data": action_data,
            "is_info": is_info,
            "candidates": [v["id"] for v in candidates],
        }

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    async def _send_confirmation(self, update_or_query, context: ContextTypes.DEFAULT_TYPE, action_data: dict, vehicle: dict):
        """Genera un mensaje de confirmacion con botones de confirmar/cancelar."""
        action = action_data["action"]
        action_id = str(uuid.uuid4())[:8]
        summary = action_data.get("summary", "Acción desconocida")

        brand = html.escape(vehicle.get("brand", "?"))
        model = html.escape(vehicle.get("model", "?"))
        year = html.escape(str(vehicle.get("year", "?")))
        price = html.escape(str(vehicle.get("price", "N/D")))

        # Construir mensaje de confirmación según la acción
        if action == "update_field":
            field = action_data.get("field", "?")
            new_value = html.escape(str(action_data.get("new_value", "?")))
            old_value = html.escape(str(vehicle.get(field, "N/D")))
            field_labels = {
                "price": "💰 Precio",
                "km": "📏 Km",
                "year": "📅 Año",
                "fuel": "⛽ Combustible",
                "transmission": "🔧 Transmisión",
                "cv": "🐴 Potencia (CV)",
                "description": "📝 Descripción",
                "brand": "🏷️ Marca",
                "model": "🚗 Modelo",
            }
            field_label = field_labels.get(field, field)
            confirm_text = (
                f"⚠️ <b>Confirmar actualización de datos:</b>\n\n"
                f"🚗 <b>{brand} {model}</b> ({year})\n\n"
                f"{field_label}:\n"
                f"  ❌ Antes: <s>{old_value}</s>\n"
                f"  ✅ Después: <b>{new_value}</b>\n\n"
                f"<i>¿Confirmamos el cambio, jefe?</i>"
            )
        elif action == "mark_sold":
            confirm_text = (
                f"🏁 <b>Confirmar venta:</b>\n\n"
                f"🚗 <b>{brand} {model}</b> ({year}) — {price}\n\n"
                f"📌 Cambio: 🟢 En venta → 🔴 <b>VENDIDO</b>\n\n"
                f"<i>¿Marcar como vendido?</i>"
            )
        elif action == "mark_available":
            confirm_text = (
                f"🟢 <b>Confirmar re-publicación:</b>\n\n"
                f"🚗 <b>{brand} {model}</b> ({year}) — {price}\n\n"
                f"📌 Cambio: 🔴 Vendido → 🟢 <b>EN VENTA</b>\n\n"
                f"<i>¿Poner el coche de nuevo en venta?</i>"
            )
        elif action == "delete":
            confirm_text = (
                f"🗑️ <b>Confirmar eliminación de anuncio:</b>\n\n"
                f"🚗 <b>{brand} {model}</b> ({year}) — {price}\n\n"
                f"⚠️ <b>Esta acción es un desguace IRREVERSIBLE.</b>\n"
                f"Se eliminará el anuncio de forma definitiva.\n\n"
                f"<i>¿Estás seguro de eliminar este vehículo?</i>"
            )
        else:
            confirm_text = f"⚠️ <b>Confirmar acción pendiente:</b>\n\n{html.escape(summary)}\n\n<i>¿Confirmamos, jefe?</i>"

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirmar", callback_data=f"agent_confirm_{action_id}"),
                InlineKeyboardButton("❌ Cancelar", callback_data=f"agent_cancel_{action_id}"),
            ]
        ])

        # Guardar la acción pendiente
        _pending_confirmations[action_id] = {
            "action_data": action_data,
            "vehicle_id": vehicle["id"],
        }

        # Enviar el mensaje — determinar si es un update.message o un callback_query
        if hasattr(update_or_query, "message") and update_or_query.message:
            await update_or_query.message.reply_text(
                confirm_text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        elif hasattr(update_or_query, "callback_query"):
            await update_or_query.callback_query.edit_message_text(
                confirm_text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

    # ─── Manejo de callbacks ─────────────────────────────────────────────────

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Maneja los callbacks de confirmación y desambiguación del agente."""
        query = update.callback_query
        await query.answer()

        data = query.data

        if data.startswith("agent_confirm_"):
            action_id = data.replace("agent_confirm_", "")
            await self._callback_confirm(update, context, action_id)

        elif data.startswith("agent_cancel_"):
            action_id = data.replace("agent_cancel_", "")
            await self._callback_cancel(update, context, action_id)

        elif data.startswith("agent_select_"):
            # Format: agent_select_{index}_{action_id}
            parts = data.replace("agent_select_", "")
            action_id = parts[-8:]
            idx_str = parts[:-9]
            await self._callback_select(update, context, idx_str, action_id)

    async def _callback_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action_id: str):
        """Ejecuta una acción confirmada."""
        query = update.callback_query
        pending = _pending_confirmations.pop(action_id, None)

        if not pending:
            await query.edit_message_text("⚠️ Esta acción ya expiró o fue procesada.")
            return

        action_data = pending["action_data"]
        vehicle_id = pending["vehicle_id"]
        action = action_data["action"]

        try:
            if action == "update_field":
                field = action_data["field"]
                new_value = action_data["new_value"]
                # Convert sold to boolean if needed
                if field == "sold":
                    new_value = new_value in ("true", "True", True)
                self.firebase.update_vehicle_field(vehicle_id, field, new_value)
                await query.edit_message_text(
                    f"✅ <b>¡Actualizado!</b> El campo se ha modificado correctamente.\n\n"
                    f"📝 {html.escape(action_data.get('summary', ''))}",
                    parse_mode="HTML",
                )

            elif action == "mark_sold":
                self.firebase.update_vehicle_field(vehicle_id, "sold", True)
                await query.edit_message_text(
                    f"🏁 <b>¡Vendido!</b> El coche se ha marcado como vendido con éxito.\n\n"
                    f"📝 {html.escape(action_data.get('summary', ''))}",
                    parse_mode="HTML",
                )

            elif action == "mark_available":
                self.firebase.update_vehicle_field(vehicle_id, "sold", False)
                await query.edit_message_text(
                    f"🟢 <b>¡En venta!</b> El vehículo vuelve a estar disponible en la web.\n\n"
                    f"📝 {html.escape(action_data.get('summary', ''))}",
                    parse_mode="HTML",
                )

            elif action == "delete":
                self.firebase.delete_vehicle(vehicle_id)
                await query.edit_message_text(
                    f"🗑️ <b>¡Eliminado!</b> El anuncio se ha borrado de Firestore.\n\n"
                    f"📝 {html.escape(action_data.get('summary', ''))}",
                    parse_mode="HTML",
                )

        except Exception as e:
            logger.error(f"Error ejecutando acción del agente: {e}", exc_info=True)
            await query.edit_message_text(
                f"❌ <b>Error:</b> Al ejecutar la acción: <code>{html.escape(str(e))}</code>",
                parse_mode="HTML",
            )

    async def _callback_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE, action_id: str):
        """Cancela una acción pendiente."""
        query = update.callback_query
        _pending_confirmations.pop(action_id, None)
        _pending_disambiguations.pop(action_id, None)

        await query.edit_message_text(
            "🛑 <b>Acción cancelada.</b>",
            parse_mode="HTML",
        )

    async def _callback_select(self, update: Update, context: ContextTypes.DEFAULT_TYPE, idx_str: str, action_id: str):
        """Maneja la selección de un vehículo en la desambiguación."""
        query = update.callback_query
        pending = _pending_disambiguations.pop(action_id, None)

        if not pending:
            await query.edit_message_text("⚠️ Esta selección ya expiró o fue procesada.")
            return

        try:
            idx = int(idx_str)
            candidates = pending.get("candidates", [])
            if not (0 <= idx < len(candidates)):
                raise ValueError("Índice fuera de rango")
            vehicle_id = candidates[idx]
        except (ValueError, TypeError, IndexError) as e:
            await query.edit_message_text(f"❌ Error en la selección: {e}")
            return

        action_data = pending["action_data"]
        is_info = pending.get("is_info", False)

        # Obtener el vehículo seleccionado
        vehicle = self.firebase.get_vehicle(vehicle_id)
        if not vehicle:
            await query.edit_message_text(f"❌ No se encontró el vehículo seleccionado.")
            return

        if is_info:
            # Solo mostrar información
            await self._send_vehicle_card_from_query(query, vehicle)
        else:
            # Actualizar el target_id y enviar confirmación
            action_data["target_id"] = vehicle_id
            action_data["target_candidates"] = []
            await self._send_confirmation(update, context, action_data, vehicle)

    async def _send_vehicle_card_from_query(self, query, vehicle: dict):
        """Envía una tarjeta de vehículo editando un mensaje de callback query."""
        status = "🔴 VENDIDO" if vehicle.get("sold") else "🟢 EN VENTA"
        brand = html.escape(vehicle.get("brand", "?"))
        model = html.escape(vehicle.get("model", "?"))
        year = html.escape(str(vehicle.get("year", "?")))
        price = html.escape(str(vehicle.get("price", "N/D")))
        km = html.escape(str(vehicle.get("km", "N/D")))
        fuel = html.escape(str(vehicle.get("fuel", "N/D")))
        transmission = html.escape(str(vehicle.get("transmission", "N/D")))
        cv = html.escape(str(vehicle.get("cv", "N/D")))
        doc_id = html.escape(vehicle.get("id", "?"))
        raw_description = vehicle.get("description", "")
        if not raw_description or not raw_description.strip():
            description = f"<i>(Vacía en la base de datos. En la web se muestra por defecto: '{brand} {model} {year} en excelente estado')</i>"
        else:
            description = html.escape(raw_description)

        detail_url = f"https://autosjveloce.com/Coches/detalle.html?id={doc_id}"

        text = (
            f"🚗 <b>{brand} {model}</b> ({year})\n\n"
            f"💰 Precio: <b>{price}</b>\n"
            f"📅 Año: {year}\n"
            f"⛽ Combustible: {fuel}\n"
            f"🔧 Transmisión: {transmission}\n"
            f"📏 Km: {km}\n"
            f"🐴 Potencia: {cv} CV\n"
            f"📌 Estado: {status}\n\n"
            f"📝 <b>Descripción:</b>\n<i>{description}</i>\n\n"
            f"🔑 ID: <code>{doc_id}</code>\n"
            f"🔗 Enlace: <a href=\"{detail_url}\">{detail_url}</a>"
        )

        await query.edit_message_text(text, parse_mode="HTML")


# ─── Almacén de acciones pendientes (a nivel de módulo) ──────────────────────

# Estas son las acciones que esperan confirmación o desambiguación
_pending_confirmations: dict[str, dict] = {}
_pending_disambiguations: dict[str, dict] = {}
