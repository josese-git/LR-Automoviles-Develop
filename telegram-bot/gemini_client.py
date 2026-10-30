"""
gemini_client.py - Cliente de la API de Gemini para JVeloce Bot
Envía texto + imágenes a Gemini para extraer las especificaciones del vehículo
en formato JSON estricto compatible con la base de datos Firestore de la web.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field

from google import genai
from google.genai import types, errors

logger = logging.getLogger(__name__)

class ClassifiedImages(BaseModel):
    frontal: Optional[int] = Field(None, description="Número de imagen del frontal completo del coche (visto de frente).")
    frontolateral: Optional[int] = Field(None, description="Número de imagen en ángulo diagonal de 3/4 desde el frente.")
    principal_con_fondo: Optional[int] = Field(None, description="Número de la foto principal (portada), que suele ser la frontolateral diagonal.")
    lateral_izquierdo: Optional[int] = Field(None, description="Número de la foto de perfil lateral completo apuntando a la izquierda.")
    lateral_derecho: Optional[int] = Field(None, description="Número de la foto de perfil lateral completo apuntando a la derecha.")
    interior: List[int] = Field(default_factory=list, description="Lista de números de imágenes del interior (asientos, salpicadero, maletero, etc.).")

class VehicleData(BaseModel):
    id: str = Field(description="ID único: marca-modelo-año en minúsculas separado por guiones, sin caracteres especiales ni espacios.")
    brand: str = Field(description="Marca del vehículo.")
    model: str = Field(description="Modelo completo del vehículo.")
    year: str = Field(description="Año de matriculación como string.")
    fuel: str = Field(description="Tipo de combustible: 'Gasolina', 'Diésel', 'Híbrido', 'Eléctrico', 'GLP' o 'GNC'.")
    transmission: str = Field(description="Tipo de transmisión: 'Manual' o 'Auto'.")
    price: str = Field(description="Precio con formato español y símbolo euro (ej: '28.500€').")
    km: str = Field(description="Kilometraje con formato y unidad (ej: '68.565 Km').")
    cv: str = Field(description="Potencia en caballos, solo el número (ej: '150').")
    description: str = Field(description="Descripción detallada y comercial del vehículo siguiendo la estructura de plantilla perfecta.")
    sold: bool = Field(False, description="Estado de venta del vehículo (siempre false al inicio).")
    classified_images: ClassifiedImages = Field(description="Clasificación de las fotos según su ángulo/vista.")
    inferred_fields: List[str] = Field(default_factory=list, description="Lista de campos técnicos deducidos por el modelo que no estaban explícitos en el texto.")


# System prompt que define exactamente el esquema JSON esperado
SYSTEM_PROMPT = """Eres un asistente especializado en clasificar y estructurar datos de vehículos de segunda mano para un concesionario llamado "Autos JVeloce".

Tu tarea es analizar el texto descriptivo y las imágenes proporcionadas del vehículo (que vienen etiquetadas en el prompt como "--- IMAGEN 1 ---", "--- IMAGEN 2 ---", etc.), y devolver EXCLUSIVAMENTE un objeto JSON válido (sin bloques de código Markdown, sin ```json, sin texto adicional antes o después) con los siguientes campos:

{
  "id": "marca-modelo-año en minúsculas separado por guiones, sin caracteres especiales ni espacios (ej: mercedes-clase-a-200d-2019)",
  "brand": "Marca del vehículo (ej: Mercedes, Peugeot, Kia, BMW, Audi, etc.)",
  "model": "Modelo completo del vehículo (ej: Clase A 200d, 3008, Sportage, etc.)",
  "year": "Año de matriculación como string (ej: '2019')",
  "fuel": "Tipo de combustible: 'Gasolina', 'Diésel', 'Híbrido', 'Eléctrico', 'GLP' o 'GNC'",
  "transmission": "Tipo de transmisión: 'Manual' o 'Auto'",
  "price": "Precio con formato español y símbolo euro (ej: '28.500€')",
  "km": "Kilometraje con formato y unidad (ej: '68.565 Km')",
  "cv": "Potencia en caballos, solo el número (ej: '150')",
  "description": "Descripción detallada y comercial del vehículo redactada obligatoriamente siguiendo la ESTRUCTURA DE PLANTILLA PERFECTA. Usa saltos de línea (\\n) para separar los párrafos.",
  "sold": false,
  "classified_images": {
    "frontal": 1,
    "frontolateral": 2,
    "principal_con_fondo": 3,
    "lateral_izquierdo": 4,
    "lateral_derecho": 5,
    "interior": [6, 7, 8]
  },
  "inferred_fields": ["cv", "transmission"]
}

REGLAS DE CLASIFICACIÓN DE IMÁGENES (classified_images):
Asocia cada número de imagen (según la etiqueta "--- IMAGEN X ---") a la categoría que mejor corresponda.
NORMA CRÍTICA DE CANTIDADES:
1. FOTOS EXTERIORES: Debe haber siempre exactamente 5 fotos clasificadas como exteriores (una única imagen asignada a cada uno de los 5 campos exteriores descritos abajo; ni una más ni una menos). Si el lote contiene al menos 5 fotos, no debes dejar ninguno de estos campos como null.
2. FOTOS INTERIORES: El campo "interior" puede contener hasta un máximo de 12 fotos interiores (no hay un mínimo, puede ser una lista vacía [] si no hay fotos del interior).

Campos exteriores a clasificar (debe haber exactamente 1 foto por campo):
- "frontal": Imagen del coche visto de frente (frontal completo).
- "frontolateral": Imagen en ángulo diagonal de 3/4 desde el frente (ej: frontal-lateral que muestra más del perfil lateral del coche).
- "principal_con_fondo": La foto principal del coche. Debe ser la foto frontolateral en diagonal de 3/4 que enseñe más morro (frontal/delantera) del coche. Esta servirá de imagen principal.
- "lateral_izquierdo": Foto de perfil lateral completo del coche donde la parte delantera apunta a la IZQUIERDA.
- "lateral_derecho": Foto de perfil lateral completo del coche donde la parte delantera apunta a la DERECHA.

Campo interior (máximo 12 fotos):
- "interior": Lista de números de imágenes correspondientes al interior del coche (asientos, volante, salpicadero, maletero, motor, etc.).

ESTRUCTURA DE PLANTILLA PERFECTA PARA LA DESCRIPCIÓN:
La descripción en el campo "description" DEBE redactarse en español y organizarse estrictamente en base a los siguientes párrafos (separados por saltos de línea \\n):
1. Párrafo 1 (Presentación básica + Motor + Año/Km + Conservación):
   Formato: "[Marca]-[Modelo] (o equivalente) con motor [Combustible/Motorización/CV] de alto rendimiento. Matriculado en [Año] con [Km] certificados. Vehículo en excelente estado de conservación."
   Ejemplo: "Mercedes-Benz Clase A 200 d con motor diésel de alto rendimiento. Matriculado en 2019 con 68.565 km certificados. Vehículo en excelente estado de conservación."
2. Párrafo 2 (Enfoque comercial y de valor):
   Formato: "Si buscas un [tipo de vehículo/carrocería (ej: compacto premium, SUV familiar, descapotable exclusivo, furgón fiable para trabajar)] este es el suyo, [Adjetivo 1 (ej: deportivo/robusto/elegante)], [Adjetivo 2 (ej: eficiente/amplio/cómodo)] y con tecnología de vanguardia."
   Ejemplo: "Si buscas un compacto premium este es el suyo, deportivo, eficiente y con tecnología de vanguardia."
3. Párrafos 3 a 5 (Equipamiento, Extras y Acabados detectados en las fotos o propios del modelo):
   Formato: 2 a 3 párrafos cortos e independientes describiendo el equipamiento interior y extras de manera comercial.
   Ejemplos:
   "Puesto de conducción Widescreen con doble pantalla digital y sistema multimedia MBUX."
   "Asientos deportivos con tapicería combinada en cuero ARTICO y tela. Consola central con Touchpad para una navegación intuitiva."
   "Selector de modos DYNAMIC SELECT (Eco, Comfort y Sport) para adaptar la conducción. Diseño deportivo de 5 puertas con acabados de alta calidad."
4. Párrafo Final (Garantía y entrega - Obligatorio e idéntico para todos los coches):
   Texto EXACTO: "Todos nuestros vehículos se entregan revisados por nuestro taller de confianza y con todo el mantenimiento recién hecho."

DETERMINACIÓN DE DATOS INFERIDOS/DEDUCIDOS (inferred_fields):
Identifica qué campos técnicos ("brand", "model", "year", "fuel", "transmission", "km", "cv") NO estaban especificados de forma explícita en el texto descriptivo proporcionado por el usuario, y que tuviste que deducir mediante tu propio conocimiento general, analizando visualmente las imágenes o realizando una búsqueda web con Google. Agrega los nombres de estos campos como elementos de la lista en "inferred_fields".
Si un dato ya estaba escrito en el texto descriptivo del usuario de alguna forma, NO lo incluyas en "inferred_fields".

BÚSQUEDA WEB Y DEDUCCIÓN:
1. Si el texto del anuncio no especifica la potencia en caballos (CV), DEBES buscarla obligatoriamente en internet utilizando la herramienta de búsqueda de Google, basándote en la marca, modelo, motorización y año del vehículo. Si encuentras múltiples potencias posibles, usa la más común para ese motor (por ejemplo, para un Seat Ibiza 1.6 TDI 2018 la potencia estándar es 95 CV). Asegúrate de que el campo "cv" contenga este número y agrega "cv" a "inferred_fields".
2. Si el tipo de transmisión no se detalla en el texto, inspecciona las fotos del interior del vehículo. Si se ve claramente una palanca de cambios manual clásica, clasifícala como "Manual"; si se ve una palanca/selector de cambios automático, clasifícala como "Auto". Si tampoco puedes deducirlo de las imágenes, usa la búsqueda de Google para encontrar la transmisión estándar para esa motorización o pon "Manual" como valor por defecto en España.
3. PRECIO (price): Si el precio no está especificado explícitamente en el texto del usuario, NO debes intentar deducirlo ni buscarlo en internet. Asigna siempre "N/D" en el campo "price" de forma obligatoria y NO agregues "price" en la lista de "inferred_fields".

REGLAS ESTRICTAS:
1. Devuelve SOLO el JSON puro. NADA MÁS. Sin explicaciones, sin texto adicional, sin bloques de código.
2. Todos los campos son obligatorios. Si no encuentras un dato y tampoco lo puedes deducir o buscar, usa "N/D" como valor. NUNCA dejes un campo sin valor ni dejes llaves vacías como '"interior":'. Si la lista de fotos de interior está vacía, usa obligatoriamente '[]'.
3. Si alguna foto exterior (frontal, frontolateral, principal_con_fondo, lateral_izquierdo, lateral_derecho) no está presente y el lote total de fotos es menor a 5, usa null como su valor. Si hay 5 o más fotos, es obligatorio asignar exactamente 1 foto distinta a cada campo exterior.
4. Cada una de las imágenes proporcionadas debe clasificarse en una sola categoría. El campo "interior" puede contener un máximo de 12 imágenes.
5. El campo "id" debe ser único y generarse a partir de marca-modelo-año en minúsculas y con guiones.
6. El precio debe incluir el símbolo € y usar puntos como separador de miles si se especifica. Si no, debe ser "N/D".
7. El kilometraje debe incluir " Km" al final y usar puntos como separador de miles.
8. La descripción ("description") debe seguir obligatoriamente la ESTRUCTURA DE PLANTILLA PERFECTA PARA LA DESCRIPCIÓN.
9. NO inventes datos que no puedas inferir o buscar. Usa "N/D" si no estás seguro.
10. El campo "year" debe ser un string, no un número."""


class GeminiKeyManager:
    """
    Gestiona múltiples claves de API de Gemini, permitiendo rotación automática
    ante errores de límite de cuota (429) y seguimiento de claves agotadas.
    """
    def __init__(self, api_keys: list[str] | str):
        if isinstance(api_keys, str):
            self.api_keys = [k.strip() for k in api_keys.split(",") if k.strip()]
        else:
            self.api_keys = [k.strip() for k in api_keys if k.strip()]
            
        if not self.api_keys:
            raise ValueError("No se proporcionaron API keys de Gemini válidas.")
            
        self.clients = [genai.Client(api_key=key) for key in self.api_keys]
        self.active_index = 0
        self.exhausted_keys = {}
        logger.info(f"GeminiKeyManager inicializado con {len(self.api_keys)} llaves de API.")

    def get_client(self) -> tuple[genai.Client, int, bool]:
        """
        Obtiene el cliente de la clave activa actual que no esté agotada.
        Si todas están agotadas, intentará reutilizar la que lleva más tiempo en 'enfriamiento'.
        Returns:
            Tuple[genai.Client, int, bool]: (cliente, índice de la llave, si todas las llaves estaban agotadas)
        """
        now = time.time()
        for idx in list(self.exhausted_keys.keys()):
            if now - self.exhausted_keys[idx] > 300: # 5 minutos de enfriamiento
                del self.exhausted_keys[idx]
                logger.info(f"Re-habilitando llave {idx} en rotación tras tiempo de enfriamiento.")

        for i in range(len(self.api_keys)):
            idx = (self.active_index + i) % len(self.api_keys)
            if idx not in self.exhausted_keys:
                self.active_index = idx
                return self.clients[idx], idx, False

        if self.exhausted_keys:
            oldest_idx = min(self.exhausted_keys, key=self.exhausted_keys.get)
            logger.warning(f"Todas las llaves de API están agotadas. Reutilizando la más antigua: llave {oldest_idx}")
            self.exhausted_keys.pop(oldest_idx, None)
            self.active_index = oldest_idx
            return self.clients[oldest_idx], oldest_idx, True

        return self.clients[0], 0, False

    def mark_exhausted(self, idx: int):
        """Marca una clave como agotada temporalmente."""
        if 0 <= idx < len(self.api_keys):
            self.exhausted_keys[idx] = time.time()
            logger.warning(f"Llave de API {idx} marcada como AGOTADA (429/Resource Exhausted).")
            self.active_index = (idx + 1) % len(self.api_keys)

    def mark_invalid(self, idx: int):
        """Marca una clave como inválida (401) temporalmente por 24 horas."""
        if 0 <= idx < len(self.api_keys):
            self.exhausted_keys[idx] = time.time() + 86400  # 24 horas de enfriamiento
            logger.error(f"Llave de API {idx} marcada como INVALIDA (401/Unauthorized). Se omitirá por 24 horas.")
            self.active_index = (idx + 1) % len(self.api_keys)


class GeminiClient:
    """Cliente para la API de Gemini que extrae datos estructurados de vehículos."""

    def __init__(self, key_manager: GeminiKeyManager | str):
        if isinstance(key_manager, str):
            self.key_manager = GeminiKeyManager([key_manager])
        else:
            self.key_manager = key_manager
        self.model_name = "gemini-2.5-flash"
        self.fallback_models = [
            "gemini-3.5-flash"
        ]

    def parse_vehicle(self, caption: str, image_paths: list[Path]) -> dict | None:
        """
        Envía el caption y las imágenes a Gemini y extrae los datos del vehículo.

        Args:
            caption: Texto descriptivo del vehículo (caption de Telegram).
            image_paths: Lista de rutas a las imágenes descargadas.

        Returns:
            Diccionario con los datos del vehículo, o None si falla el parsing.
        """
        try:
            # Construir las partes del contenido
            content_parts = []

            # Añadir imágenes (limitar a 16 para poder clasificar la galería completa)
            for i, path in enumerate(image_paths[:16]):
                try:
                    from PIL import Image
                    import io

                    # Redimensionar imagen para reducir radicalmente los tokens consumidos y evitar errores 429 (cuota de tokens por minuto)
                    with Image.open(path) as img:
                        max_size = 512
                        if img.width > max_size or img.height > max_size:
                            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                        
                        buffer = io.BytesIO()
                        if img.mode in ("RGBA", "P"):
                            img = img.convert("RGB")
                        img.save(buffer, format="JPEG", quality=85)
                        img_bytes = buffer.getvalue()
                        
                    mime_type = "image/jpeg"

                    # Insertar etiqueta de texto antes de la imagen para que Gemini pueda identificar su índice
                    content_parts.append(
                        types.Part.from_text(text=f"--- IMAGEN {i+1} ---")
                    )
                    content_parts.append(
                        types.Part.from_bytes(data=img_bytes, mime_type=mime_type)
                    )
                except Exception as e:
                    logger.warning(f"No se pudo cargar la imagen {path}: {e}")

            # Añadir el texto del usuario
            content_parts.append(
                types.Part.from_text(
                    text=f"\n--- TEXTO DEL ANUNCIO ---\n{caption}\n--- FIN DEL TEXTO ---\n\n"
                    "Ahora devuelve EXCLUSIVAMENTE el JSON del vehículo:"
                )
            )

            # Enviar a Gemini con rotación de claves y fallback de modelos
            models_to_try = [self.model_name] + self.fallback_models
            response = None
            
            for current_model in models_to_try:
                num_keys = len(self.key_manager.api_keys)
                max_attempts = max(3, num_keys * 2)
                backoff_factor = 2
                model_503_count = 0
                
                logger.info(f"Intentando generar contenido con modelo: {current_model}")
                
                success = False
                for attempt in range(max_attempts):
                    client, key_idx, all_exhausted = self.key_manager.get_client()
                    if all_exhausted:
                        logger.warning("Todas las llaves están temporalmente agotadas. Esperando 2 segundos...")
                        time.sleep(2.0)

                    try:
                        # google_search se soporta en 2.5-flash y 2.0-flash.
                        tools = [types.Tool(google_search=types.GoogleSearch())]
                        
                        # NOTA: tools y response_schema/response_mime_type son incompatibles en la API de Gemini (devuelve 400).
                        # Omitimos response_mime_type/response_schema y dejamos que _extract_json parsee el JSON del texto.
                        response = client.models.generate_content(
                            model=current_model,
                            contents=content_parts,
                            config=types.GenerateContentConfig(
                                system_instruction=SYSTEM_PROMPT,
                                temperature=0.1,
                                tools=tools,
                            ),
                        )
                        success = True
                        break  # Éxito con este modelo, salir de los intentos
                    except errors.APIError as e:
                        if e.code == 429:
                            self.key_manager.mark_exhausted(key_idx)
                            if num_keys > 1:
                                logger.warning(
                                    f"Llave {key_idx} falló con error 429 usando {current_model}. "
                                    "Rotando llave e intentando de nuevo en 1.0s..."
                                )
                                time.sleep(1.0)
                                continue
                        elif e.code == 401:
                            self.key_manager.mark_invalid(key_idx)
                            if num_keys > 1:
                                logger.warning(
                                    f"Llave {key_idx} falló con error 401 usando {current_model}. "
                                    "Rotando llave e intentando de nuevo en 0.1s..."
                                )
                                time.sleep(0.1)
                                continue
                        elif e.code == 503:
                            model_503_count += 1
                            if model_503_count >= 3:
                                logger.error(
                                    f"Error 503 recurrente ({model_503_count} veces) para {current_model}. "
                                    "Pasando al siguiente modelo fallback de inmediato."
                                )
                                break
                            
                            sleep_time = backoff_factor ** (attempt % 3 + 1)
                            logger.warning(
                                f"Gemini API devolvió error 503 usando {current_model} (intento {attempt + 1}/{max_attempts}). "
                                f"Reintentando en {sleep_time}s..."
                            )
                            time.sleep(sleep_time)
                            continue
                        
                        # Si es otro código de error (ej: 404, 400, etc.) o se agotaron los intentos
                        logger.error(f"Error definitivo con modelo {current_model} en intento {attempt+1}: {e}")
                        break
                            
                if success:
                    break  # Éxito total, salir de la rotación de modelos

            if not response or not response.text:
                logger.error("Gemini devolvió una respuesta vacía.")
                return None

            raw_text = response.text.strip()
            logger.info(f"Respuesta de Gemini (primeros 500 chars): {raw_text[:500]}")

            # Parsear JSON de la respuesta
            return self._extract_json(raw_text)

        except Exception as e:
            logger.error(f"Error al comunicarse con Gemini: {e}", exc_info=True)
            return None

    def _extract_json(self, text: str) -> dict | None:
        """
        Extrae y valida el JSON de la respuesta de Gemini.
        Maneja casos donde Gemini envuelve el JSON en bloques de código.
        """
        # Pre-procesamiento y reparación de JSON malformado de Gemini
        try:
            # 1. Reparar claves de lista vacías (como "interior": sin valor antes del cierre)
            text = re.sub(r'"interior"\s*:\s*(?=\s*[,}])', '"interior": []', text)
            text = re.sub(r'"inferred_fields"\s*:\s*(?=\s*[,}])', '"inferred_fields": []', text)
            # 2. Reparar cualquier otra clave vacía asignándole null
            text = re.sub(r'"(\w+)"\s*:\s*(?=\s*[,}])', r'"\1": null', text)
            # 3. Eliminar comas flotantes/trailing commas al final de objetos o listas
            text = re.sub(r',\s*(?=[\]}])', '', text)
        except Exception as repair_err:
            logger.warning(f"Error durante el pre-procesamiento/reparación del JSON: {repair_err}")

        # Intento 1: Parsear directamente
        try:
            data = json.loads(text)
            return self._validate_vehicle_data(data)
        except json.JSONDecodeError:
            pass

        # Intento 2: Extraer JSON de bloques de código markdown (por si acaso)
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1).strip())
                return self._validate_vehicle_data(data)
            except json.JSONDecodeError:
                pass

        # Intento 3: Buscar el primer { ... } en el texto
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            try:
                data = json.loads(brace_match.group(0))
                return self._validate_vehicle_data(data)
            except json.JSONDecodeError:
                pass

        logger.error(f"No se pudo extraer JSON válido de la respuesta de Gemini:\n{text}")
        return None

    def _validate_vehicle_data(self, data: dict) -> dict | None:
        """Valida que el JSON contenga los campos mínimos requeridos."""
        required_fields = ["brand", "model"]

        for field in required_fields:
            if field not in data or not data[field]:
                logger.error(f"Campo requerido '{field}' no encontrado en los datos.")
                return None

        # Asegurar que todos los campos opcionales existen con valores por defecto
        defaults = {
            "id": "",
            "year": "N/D",
            "fuel": "N/D",
            "transmission": "N/D",
            "price": "N/D",
            "km": "N/D",
            "cv": "",
            "description": "",
            "sold": False,
        }

        for field, default in defaults.items():
            data.setdefault(field, default)

        # Generar ID si no existe o está vacío
        if not data["id"]:
            brand_slug = data["brand"].lower().replace(" ", "-")
            model_slug = data["model"].lower().replace(" ", "-")
            year = data["year"] if data["year"] != "N/D" else ""
            parts = [brand_slug, model_slug]
            if year:
                parts.append(year)
            data["id"] = "-".join(parts)

        # Limpiar caracteres especiales del ID
        data["id"] = re.sub(r"[^a-z0-9\-]", "", data["id"])

        return data

    def transcribe_audio(self, audio_path: Path) -> str | None:
        """Sube un archivo de audio a Gemini y devuelve la transcripción."""
        logger.info(f"Subiendo audio para transcripción: {audio_path}")
        try:
            # Usar modelos más ligeros para transcripción para que sea casi instantáneo
            models_to_try = ["gemini-2.5-flash", "gemini-3.5-flash"]
            
            for current_model in models_to_try:
                num_keys = len(self.key_manager.api_keys)
                max_attempts = max(3, num_keys * 2)
                
                success = False
                for attempt in range(max_attempts):
                    client, key_idx, all_exhausted = self.key_manager.get_client()
                    if all_exhausted:
                        time.sleep(2.0)
                        
                    try:
                        # Subir el archivo (requiere la API File)
                        # Nota: En google-genai 1.0.0, upload requiere que client sea síncrono o use async. 
                        # Aquí client es síncrono.
                        uploaded_file = client.files.upload(file=str(audio_path))
                        
                        response = client.models.generate_content(
                            model=current_model,
                            contents=[
                                types.Part.from_text(text="Transcribe exactamente el contenido de este audio en el mismo idioma en el que se habla. Solo devuelve el texto transcrito sin comillas ni notas adicionales."),
                                uploaded_file
                            ],
                            config=types.GenerateContentConfig(temperature=0.1)
                        )
                        success = True
                        
                        # Intentar borrar el archivo remoto para no acumular
                        try:
                            client.files.delete(name=uploaded_file.name)
                        except Exception as e:
                            logger.warning(f"No se pudo borrar el archivo remoto {uploaded_file.name}: {e}")
                            
                        if response and response.text:
                            return response.text.strip()
                        break
                        
                    except errors.APIError as e:
                        if e.code == 429:
                            self.key_manager.mark_exhausted(key_idx)
                            if num_keys > 1: time.sleep(1.0)
                            continue
                        elif e.code == 401:
                            self.key_manager.mark_invalid(key_idx)
                            if num_keys > 1: time.sleep(0.1)
                            continue
                        else:
                            logger.error(f"Error transcribiendo con {current_model}: {e}")
                            break
                            
                if success:
                    break
                    
            return None
            
        except Exception as e:
            logger.error(f"Error general transcribiendo audio: {e}", exc_info=True)
            return None
