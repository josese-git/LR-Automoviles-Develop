"""
facebook_scraper.py - Scraper de Facebook Marketplace para JVeloce Bot

Utiliza Playwright (headless Chromium) para:
  - Obtener todos los anuncios del perfil de Marketplace de JVeloce.
  - Extraer ID, título, precio, descripción completa y URLs de imágenes HD de cada anuncio.
  - Gestionar el historial de anuncios ya procesados para evitar duplicados.

El scraper NO requiere sesión de usuario de Facebook.
Funciona extrayendo los datos desde los scripts JSON de hidratación de React que
Facebook embebe en el HTML renderizado del servidor.
"""

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("FacebookScraper")

# ─── Constantes ───────────────────────────────────────────────────────────────

FB_PROFILE_URL = "https://www.facebook.com/marketplace/profile/61554155664150/"

# Ruta por defecto al archivo de estado (relativa al directorio de trabajo del bot)
DEFAULT_STATE_FILE = Path(__file__).parent / "fb_processed_listings.json"

# Tiempo mínimo entre peticiones al mismo dominio (ms)
REQUEST_DELAY_MS = 1500

# ─── Dataclass de anuncio ─────────────────────────────────────────────────────


@dataclass
class FBListing:
    """Representa un anuncio de Facebook Marketplace."""
    fb_id: str                          # ID numérico del anuncio en Facebook
    title: str                          # Título del anuncio
    price: str                          # Precio formateado (ej: "5.000€" o "N/D")
    description: str                    # Descripción completa del anuncio
    photo_urls: list[str] = field(default_factory=list)  # URLs HD de las fotos
    listing_url: str = ""               # URL completa del anuncio en Marketplace


# ─── Gestor de estado ─────────────────────────────────────────────────────────


class FBListingStateManager:
    """
    Gestiona el conjunto de IDs de anuncios de Facebook ya procesados,
    con persistencia en un archivo JSON local en la VM.
    """

    def __init__(self, state_file: Path = DEFAULT_STATE_FILE):
        self.state_file = state_file
        self._processed: set[str] = set()
        self._load()

    def _load(self):
        """Carga el estado desde el archivo JSON si existe."""
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                self._processed = set(data.get("processed_ids", []))
                logger.info(
                    f"Estado cargado: {len(self._processed)} anuncios de FB ya procesados."
                )
            except Exception as e:
                logger.warning(f"No se pudo cargar el estado de FB: {e}. Empezando desde cero.")
                self._processed = set()
        else:
            logger.info("Primer arranque: no hay estado previo de FB.")

    def _save(self):
        """Persiste el estado en el archivo JSON."""
        try:
            data = {"processed_ids": sorted(self._processed)}
            self.state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Error guardando estado de FB: {e}")

    def is_processed(self, fb_id: str) -> bool:
        return fb_id in self._processed

    def mark_processed(self, fb_id: str):
        self._processed.add(fb_id)
        self._save()

    def mark_all_processed(self, fb_ids: list[str]):
        """Marca un lote de IDs como procesados (para el primer arranque)."""
        self._processed.update(fb_ids)
        self._save()
        logger.info(f"Primer arranque: {len(fb_ids)} anuncios marcados como ya vistos.")

    @property
    def processed_count(self) -> int:
        return len(self._processed)

    def is_first_run(self) -> bool:
        """Devuelve True si aún no hay ningún anuncio marcado como procesado."""
        return len(self._processed) == 0


# ─── Scraper ──────────────────────────────────────────────────────────────────


class FacebookMarketplaceScraper:
    """
    Scraper de Facebook Marketplace basado en Playwright.
    Extrae los anuncios publicados en el perfil de la cuenta de JVeloce.
    """

    PROFILE_URL = FB_PROFILE_URL
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )

    def __init__(self, headless: bool = True, timeout_ms: int = 30000):
        self.headless = headless
        self.timeout_ms = timeout_ms

    async def _get_page_html(self, url: str) -> Optional[str]:
        """
        Lanza un browser Playwright headless, navega a la URL
        y devuelve el HTML completo renderizado con JS.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright no está instalado. Ejecuta: pip install playwright && playwright install chromium"
            )

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=self.headless,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--lang=es-ES",
                    ],
                )
                context = await browser.new_context(
                    user_agent=self.USER_AGENT,
                    locale="es-ES",
                    viewport={"width": 1280, "height": 900},
                    java_script_enabled=True,
                    ignore_https_errors=True,
                )
                page = await context.new_page()

                # Interceptar y bloquear recursos pesados/innecesarios para mayor rapidez
                await page.route(
                    "**/*.{mp4,mp3,woff,woff2,otf,ttf,eot,svg,gif}",
                    lambda route: route.abort()
                )

                logger.info(f"Navegando a: {url}")
                await page.goto(url, timeout=self.timeout_ms, wait_until="domcontentloaded")

                # Esperar a que carguen los datos de los anuncios (buscar elementos de listing)
                try:
                    await page.wait_for_selector(
                        "[data-mcomponent-type='ListingCard'], [class*='MarketplaceCard'], "
                        "div[style*='border-radius'] > div",
                        timeout=8000
                    )
                except Exception:
                    # Continuar aunque no encuentre selectores exactos
                    await asyncio.sleep(3)

                # Scroll suave para activar lazy load de todas las cards
                await self._scroll_page(page)

                html = await page.content()
                await browser.close()
                return html

        except Exception as e:
            logger.error(f"Error en Playwright al navegar a {url}: {e}", exc_info=True)
            return None

    async def _scroll_page(self, page):
        """Hace scroll gradual para activar lazy loading de los anuncios."""
        try:
            for _ in range(4):
                await page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")
                await asyncio.sleep(0.8)
        except Exception:
            pass

    def _extract_listings_from_html(self, html: str) -> list[dict]:
        """
        Extrae los datos de los anuncios desde los scripts JSON de hidratación
        de React embebidos en el HTML de Facebook.
        Returns lista de dicts con: id, title, price, description (puede estar vacía aquí).
        """
        listings_data = []
        seen_ids = set()

        # Buscar todos los scripts JSON (application/json con data-sjs o similares)
        script_contents = re.findall(
            r'<script type="application/json"[^>]*>(.*?)</script>',
            html,
            re.DOTALL
        )

        def deep_search(obj, acc: list):
            """Búsqueda recursiva de objetos de listing en el JSON."""
            if isinstance(obj, dict):
                obj_id = obj.get("id")
                # Un listing de Marketplace tiene: id + custom_title o listing_title
                has_title = "custom_title" in obj or "listing_title" in obj
                has_price = "formatted_price" in obj

                if obj_id and (has_title or has_price) and str(obj_id).isdigit():
                    title = obj.get("custom_title") or obj.get("listing_title") or ""
                    price_obj = obj.get("formatted_price")
                    if isinstance(price_obj, dict):
                        price = price_obj.get("text", "N/D")
                    elif isinstance(price_obj, str):
                        price = price_obj
                    else:
                        price = "N/D"

                    # Limpiar precio (FB usa caracteres especiales como \u00a0 como separador)
                    price = price.replace("\u00a0", ".")

                    # URL del anuncio
                    listing_url = f"https://www.facebook.com/marketplace/item/{obj_id}/"

                    # Intentar extraer foto de portada desde el objeto actual
                    photo_url = ""
                    if "listing_photos" in obj:
                        photos = obj["listing_photos"]
                        if isinstance(photos, list) and photos:
                            img_obj = photos[0]
                            photo_url = (
                                img_obj.get("image", {}).get("uri") or
                                img_obj.get("uri") or ""
                            )
                    # Fallback: intentar desde primary_listing_photo
                    if not photo_url and "primary_listing_photo" in obj:
                        plp = obj["primary_listing_photo"]
                        photo_url = (
                            plp.get("image", {}).get("uri") or
                            plp.get("uri") or ""
                        )

                    item_data = {
                        "id": str(obj_id),
                        "title": title,
                        "price": price,
                        "photo_url": photo_url,
                        "listing_url": listing_url,
                    }
                    acc.append(item_data)

                # Recursión
                for v in obj.values():
                    deep_search(v, acc)
            elif isinstance(obj, list):
                for item in obj:
                    deep_search(item, acc)

        raw_found = []
        for script_text in script_contents:
            if "custom_title" in script_text or "listing_title" in script_text or "formatted_price" in script_text:
                try:
                    data = json.loads(script_text)
                    deep_search(data, raw_found)
                except json.JSONDecodeError:
                    pass

        # Deduplicar por ID
        for item in raw_found:
            if item["id"] not in seen_ids and len(item["id"]) >= 10:
                seen_ids.add(item["id"])
                listings_data.append(item)

        logger.info(f"Total de anuncios únicos encontrados en el perfil: {len(listings_data)}")
        return listings_data

    async def _extract_listing_details(self, fb_id: str, listing_url: str) -> tuple[str, list[str]]:
        """
        Entra en la página individual del anuncio y extrae:
        - Descripción completa del anuncio
        - Todas las URLs de imágenes en alta resolución
        Returns: (description, photo_urls)
        """
        html = await self._get_page_html(listing_url)
        if not html:
            return "", []

        description = ""
        photo_urls = []

        # Parsear scripts JSON para extraer datos del item
        script_contents = re.findall(
            r'<script type="application/json"[^>]*>(.*?)</script>',
            html,
            re.DOTALL
        )

        seen_photos = set()

        def search_item_detail(obj):
            nonlocal description
            if isinstance(obj, dict):
                # Descripción del anuncio
                for desc_key in ("redacted_description", "description", "marketplace_listing_description"):
                    desc_obj = obj.get(desc_key)
                    if isinstance(desc_obj, dict):
                        text = desc_obj.get("text", "")
                        if text and len(text) > len(description):
                            description = text
                    elif isinstance(desc_obj, str) and len(desc_obj) > len(description):
                        description = desc_obj

                # Fotos del anuncio
                for photo_key in ("listing_photos", "media", "images"):
                    photos_raw = obj.get(photo_key)
                    if isinstance(photos_raw, list):
                        for ph in photos_raw:
                            if isinstance(ph, dict):
                                # Buscar la resolución más alta disponible
                                uri = (
                                    ph.get("image", {}).get("uri") or
                                    _find_highest_res(ph) or
                                    ph.get("uri") or
                                    ""
                                )
                                if uri and uri not in seen_photos and uri.startswith("http"):
                                    seen_photos.add(uri)
                                    photo_urls.append(uri)

                # Recursión
                for v in obj.values():
                    search_item_detail(v)
            elif isinstance(obj, list):
                for item in obj:
                    search_item_detail(item)

        for script_text in script_contents:
            if fb_id in script_text or "listing" in script_text:
                try:
                    data = json.loads(script_text)
                    search_item_detail(data)
                except json.JSONDecodeError:
                    pass

        # Fallback: buscar imágenes en el HTML con regex
        if not photo_urls:
            img_matches = re.findall(
                r'"uri":"(https://[^"]*scontent[^"]*\.(?:jpg|jpeg|png)[^"]*)"',
                html
            )
            for uri in img_matches:
                clean_uri = uri.replace("\\u0026", "&")
                if clean_uri not in seen_photos:
                    seen_photos.add(clean_uri)
                    photo_urls.append(clean_uri)

        # Filtrar fotos de perfil/avatares (suelen tener dimensiones pequeñas o paths /p/ )
        photo_urls = [u for u in photo_urls if "/p/" not in u and "profile" not in u.lower()]

        logger.info(
            f"Anuncio {fb_id}: descripción={'Sí' if description else 'No'}, "
            f"fotos={len(photo_urls)}"
        )
        return description, photo_urls

    async def get_profile_listings(self) -> list[dict]:
        """
        Scrape el perfil de Marketplace y devuelve todos los anuncios encontrados
        como lista de dicts con campos básicos (id, title, price, photo_url, listing_url).
        NO entra en cada anuncio individualmente (eso se hace bajo demanda).
        """
        html = await self._get_page_html(self.PROFILE_URL)
        if not html:
            logger.error("No se pudo obtener el HTML del perfil de Facebook Marketplace.")
            return []
        return self._extract_listings_from_html(html)

    async def get_full_listing(self, fb_id: str, listing_url: str, title: str, price: str) -> FBListing:
        """
        Obtiene los detalles completos de un anuncio (descripción + fotos HD).
        """
        # Pequeño delay entre peticiones
        await asyncio.sleep(REQUEST_DELAY_MS / 1000.0)

        description, photo_urls = await self._extract_listing_details(fb_id, listing_url)

        return FBListing(
            fb_id=fb_id,
            title=title,
            price=price,
            description=description,
            photo_urls=photo_urls,
            listing_url=listing_url,
        )


# ─── Función auxiliar ─────────────────────────────────────────────────────────


def _find_highest_res(photo_obj: dict) -> str:
    """
    Dado un objeto de foto de FB, intenta encontrar la URL de la mayor resolución disponible.
    """
    for key in ("large", "full", "original", "high", "image"):
        val = photo_obj.get(key)
        if isinstance(val, dict):
            uri = val.get("uri", "")
            if uri:
                return uri
        elif isinstance(val, str) and val.startswith("http"):
            return val
    return ""
