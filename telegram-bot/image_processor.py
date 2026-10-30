"""
image_processor.py - Procesador de imágenes para JVeloce Bot
Maneja la eliminación de fondo de la imagen principal utilizando la API de remove.bg.
"""

import os
import logging
from pathlib import Path
import requests

logger = logging.getLogger(__name__)


class BackgroundRemovalError(Exception):
    """Excepción personalizada para errores en la eliminación del fondo."""
    pass


def remove_background(image_path: Path, api_key: str | None = None) -> Path:
    """
    Elimina el fondo de una imagen usando la API de remove.bg.
    Devuelve la ruta al nuevo archivo PNG transparente creado.

    Args:
        image_path: Ruta a la imagen original local.
        api_key: Clave de la API de remove.bg (si es None, se lee del entorno).

    Returns:
        Ruta local del nuevo archivo de imagen PNG sin fondo.

    Raises:
        BackgroundRemovalError: Si la API devuelve un error o no está configurada.
    """
    api_key = api_key or os.getenv("REMOVE_BG_API_KEY")
    if not api_key:
        raise BackgroundRemovalError(
            "REMOVE_BG_API_KEY no está configurada en el archivo .env"
        )

    logger.info(f"Iniciando eliminación de fondo para: {image_path.name}")
    output_path = image_path.parent / f"{image_path.stem}_nobg.png"

    try:
        with open(image_path, "rb") as img_file:
            response = requests.post(
                "https://api.remove.bg/v1.0/removebg",
                files={"image_file": img_file},
                data={"size": "auto"},  # auto detecta resolución óptima gratuita
                headers={"X-Api-Key": api_key},
                timeout=30,
            )

        if response.status_code == 200:
            with open(output_path, "wb") as out_file:
                out_file.write(response.content)
            logger.info(f"Fondo eliminado con éxito. Archivo guardado: {output_path.name}")
            return output_path
        else:
            # Intentar extraer mensaje de error de la API
            try:
                error_data = response.json()
                errors = error_data.get("errors", [])
                error_msg = errors[0].get("title", "Error desconocido") if errors else "Error desconocido"
            except Exception:
                error_msg = response.text or f"Código de estado HTTP {response.status_code}"

            raise BackgroundRemovalError(f"remove.bg API error: {error_msg}")

    except requests.RequestException as e:
        raise BackgroundRemovalError(f"Error de red al conectar con remove.bg: {e}")
    except Exception as e:
        if not isinstance(e, BackgroundRemovalError):
            raise BackgroundRemovalError(f"Error inesperado al quitar el fondo: {e}") from e
        raise
