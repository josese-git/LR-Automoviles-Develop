"""
firebase_client.py - Cliente Firebase Admin para JVeloce Bot
Gestiona la subida de imágenes a Storage y la escritura de documentos en Firestore.
"""

import logging
import os
import uuid
import urllib.parse
from pathlib import Path
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, firestore, storage

logger = logging.getLogger("FirebaseClient")


class FirebaseClient:
    """Cliente para interactuar con Firebase Firestore y Storage."""

    COLLECTION_NAME = "anuncios"
    # Bucket de Firebase Storage (extraído de firebase-config.js del proyecto)
    STORAGE_BUCKET = "jveloce-cf602.firebasestorage.app"

    def __init__(self):
        cred_path = os.getenv(
            "FIREBASE_CREDENTIALS_PATH", "./firebase-service-account.json"
        )

        if Path(cred_path).exists():
            # Opción 1: Archivo de credenciales del Service Account
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(
                cred, {"storageBucket": self.STORAGE_BUCKET}
            )
            logger.info("Firebase inicializado con Service Account JSON.")
        else:
            # Opción 2: Application Default Credentials (gcloud CLI)
            # Funciona si el usuario ha ejecutado: gcloud auth application-default login
            try:
                cred = credentials.ApplicationDefault()
                firebase_admin.initialize_app(
                    cred,
                    {
                        "storageBucket": self.STORAGE_BUCKET,
                        "projectId": "jveloce-cf602",
                    },
                )
                logger.info(
                    "Firebase inicializado con Application Default Credentials. "
                    "(Si no has hecho login, ejecuta: gcloud auth application-default login)"
                )
            except Exception as e:
                raise RuntimeError(
                    f"No se pudo inicializar Firebase.\n\n"
                    f"No se encontró '{cred_path}' y las credenciales por defecto fallaron.\n\n"
                    f"SOLUCIÓN: Ejecuta este comando en la terminal:\n"
                    f"  gcloud auth application-default login\n\n"
                    f"Error original: {e}"
                ) from e

        self.db = firestore.client()
        self.bucket = storage.bucket()

    def upload_image(
        self, local_path: Path, brand: str, model: str, img_type: str
    ) -> str:
        """
        Sube una imagen a Firebase Storage y devuelve la URL de descarga.

        Args:
            local_path: Ruta local al archivo de imagen.
            brand: Marca del vehículo (sanitizada, sin espacios).
            model: Modelo del vehículo (sanitizado, sin espacios).
            img_type: Tipo de imagen ('main', 'logo', 'exterior_0', 'interior_0', etc.).

        Returns:
            URL de descarga pública de Firebase Storage.
        """
        timestamp = int(datetime.now().timestamp() * 1000)
        ext = local_path.suffix or ".jpg"

        # Mismo patrón de rutas que usa admin.js: anuncios/{Marca}/{Modelo}/{timestamp}_{type}.ext
        remote_path = f"anuncios/{brand}/{model}/{timestamp}_{img_type}{ext}"

        # Determinar content type
        content_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }
        content_type = content_types.get(ext.lower(), "image/jpeg")

        blob = self.bucket.blob(remote_path)

        # Generar un token de descarga (mismo sistema que Firebase Client SDK)
        download_token = str(uuid.uuid4())
        blob.metadata = {"firebaseStorageDownloadTokens": download_token}

        blob.upload_from_filename(str(local_path), content_type=content_type)

        # Construir URL de descarga en el formato estándar de Firebase Storage
        encoded_path = urllib.parse.quote(remote_path, safe="")
        download_url = (
            f"https://firebasestorage.googleapis.com/v0/b/{self.bucket.name}"
            f"/o/{encoded_path}?alt=media&token={download_token}"
        )

        return download_url

    def add_vehicle(self, doc_id: str, data: dict):
        """
        Añade o sobrescribe un documento de vehículo en Firestore.

        Args:
            doc_id: ID del documento (ej: 'mercedes-clase-a-2019').
            data: Diccionario con todos los campos del vehículo.
        """
        self.db.collection(self.COLLECTION_NAME).document(doc_id).set(data)

    def list_vehicles(self) -> list[dict]:
        """Devuelve todos los vehículos ordenados por 'order'."""
        docs = (
            self.db.collection(self.COLLECTION_NAME)
            .order_by("order")
            .stream()
        )
        return [{"id": doc.id, **doc.to_dict()} for doc in docs]

    def delete_vehicle(self, doc_id: str):
        """
        Elimina un vehículo de Firestore.

        Args:
            doc_id: ID del documento a eliminar.

        Raises:
            ValueError: Si el documento no existe.
        """
        doc_ref = self.db.collection(self.COLLECTION_NAME).document(doc_id)
        doc = doc_ref.get()
        if not doc.exists:
            raise ValueError(f"Vehículo '{doc_id}' no encontrado en Firestore.")
        doc_ref.delete()

    def get_vehicle(self, doc_id: str) -> dict | None:
        """
        Obtiene un vehículo por su ID de documento.

        Returns:
            Diccionario con los datos del vehículo, o None si no existe.
        """
        doc_ref = self.db.collection(self.COLLECTION_NAME).document(doc_id)
        doc = doc_ref.get()
        if doc.exists:
            return {"id": doc.id, **doc.to_dict()}
        return None

    def update_vehicle_field(self, doc_id: str, field: str, value) -> bool:
        """
        Actualiza un campo específico de un vehículo.

        Args:
            doc_id: ID del documento.
            field: Nombre del campo a actualizar.
            value: Nuevo valor del campo.

        Returns:
            True si la actualización fue exitosa.

        Raises:
            ValueError: Si el documento no existe.
        """
        doc_ref = self.db.collection(self.COLLECTION_NAME).document(doc_id)
        doc = doc_ref.get()
        if not doc.exists:
            raise ValueError(f"Vehículo '{doc_id}' no encontrado en Firestore.")
        doc_ref.update({field: value})
        return True

    def update_vehicle_fields(self, doc_id: str, updates: dict) -> bool:
        """
        Actualiza múltiples campos de un vehículo a la vez.

        Args:
            doc_id: ID del documento.
            updates: Diccionario con los campos y valores a actualizar.

        Returns:
            True si la actualización fue exitosa.

        Raises:
            ValueError: Si el documento no existe.
        """
        doc_ref = self.db.collection(self.COLLECTION_NAME).document(doc_id)
        doc = doc_ref.get()
        if not doc.exists:
            raise ValueError(f"Vehículo '{doc_id}' no encontrado en Firestore.")
        doc_ref.update(updates)
        return True

    def search_vehicles(self, brand: str = None, model: str = None, year: str = None) -> list[dict]:
        """
        Busca vehículos por marca, modelo y/o año con coincidencia parcial (case-insensitive).

        Returns:
            Lista de vehículos que coinciden con los criterios de búsqueda.
        """
        all_vehicles = self.list_vehicles()
        results = []

        for v in all_vehicles:
            match = True
            if brand and brand.lower() not in v.get("brand", "").lower():
                match = False
            if model and model.lower() not in v.get("model", "").lower():
                match = False
            if year and str(year) != str(v.get("year", "")):
                match = False
            if match:
                results.append(v)

        return results

    def get_vehicles_by_status(self, sold: bool) -> list[dict]:
        """
        Filtra vehículos por estado de venta.

        Args:
            sold: True para vendidos, False para en venta.

        Returns:
            Lista de vehículos filtrados.
        """
        all_vehicles = self.list_vehicles()
        return [v for v in all_vehicles if v.get("sold", False) == sold]

    def get_vehicle_count(self) -> int:
        """Devuelve el número total de vehículos publicados."""
        return len(list(self.db.collection(self.COLLECTION_NAME).stream()))
