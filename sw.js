/**
 * Service Worker - JVeloce Image Cache
 * Implementa estrategia "Cache First" para imágenes de Firebase Storage
 * y assets locales, reduciendo consumo de ancho de banda.
 */

const CACHE_VERSION = 'v1';
const IMAGE_CACHE_NAME = `lr-images-${CACHE_VERSION}`;
const STATIC_CACHE_NAME = `lr-static-${CACHE_VERSION}`;

// Patrones de URLs a cachear
const IMAGE_PATTERNS = [
    'firebasestorage.googleapis.com',  // Imágenes de Firebase Storage
    '/assets/',                         // Assets locales
];

// Assets estáticos a pre-cachear durante la instalación
const STATIC_ASSETS = [
    '/assets/lr-logo.jpg',
    '/assets/icons/favicon.png',
    '/assets/lr-logo.jpg',
    '/assets/vendido.png'
];

/**
 * Evento: Install
 * Pre-cachea assets estáticos esenciales
 */
self.addEventListener('install', (event) => {
    console.log('[SW] Installing Service Worker...');

    event.waitUntil(
        caches.open(STATIC_CACHE_NAME)
            .then((cache) => {
                console.log('[SW] Pre-caching static assets');
                // Intentar cachear assets estáticos (no falla si alguno no existe)
                return Promise.allSettled(
                    STATIC_ASSETS.map(url =>
                        cache.add(url).catch(err =>
                            console.log(`[SW] Could not pre-cache: ${url}`, err)
                        )
                    )
                );
            })
            .then(() => {
                // Activar inmediatamente sin esperar
                return self.skipWaiting();
            })
    );
});

/**
 * Evento: Activate
 * Limpia cachés antiguas cuando hay nueva versión
 */
self.addEventListener('activate', (event) => {
    console.log('[SW] Activating Service Worker...');

    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames
                    .filter((cacheName) => {
                        // Eliminar cachés que no coincidan con la versión actual
                        return cacheName.startsWith('jveloce-') &&
                            !cacheName.endsWith(CACHE_VERSION);
                    })
                    .map((cacheName) => {
                        console.log('[SW] Deleting old cache:', cacheName);
                        return caches.delete(cacheName);
                    })
            );
        }).then(() => {
            // Tomar control de todas las páginas inmediatamente
            return self.clients.claim();
        })
    );
});

/**
 * Evento: Fetch
 * Intercepta peticiones y aplica estrategia de caché
 */
self.addEventListener('fetch', (event) => {
    const request = event.request;
    const url = request.url;

    // Solo manejar peticiones GET
    if (request.method !== 'GET') return;

    // NO interceptar peticiones que requieren CORS
    // (cuando JavaScript necesita leer la imagen, como en Cropper.js)
    // Estas peticiones tienen mode: 'cors' en lugar de 'no-cors'
    if (request.mode === 'cors') {
        return; // Dejar que el navegador maneje las peticiones CORS
    }

    // NO cachear si la URL del cliente es admin.html
    // Usamos el referrer Y también verificamos el clientId
    const referrer = request.referrer || '';
    const isFromAdmin = referrer.includes('admin.html') ||
        referrer.includes('/admin');
    if (isFromAdmin) {
        return; // Dejar que el navegador maneje normalmente
    }

    // Verificar si es una imagen que debemos cachear
    const isImage = request.destination === 'image' ||
        /\.(jpg|jpeg|png|gif|webp|svg|ico)(\?.*)?$/i.test(url);

    const shouldCache = IMAGE_PATTERNS.some(pattern => url.includes(pattern));

    if (isImage && shouldCache) {
        event.respondWith(cacheFirstStrategy(request, IMAGE_CACHE_NAME));
    }
    // Para otros recursos, dejar que el navegador maneje normalmente
});

/**
 * Estrategia: Cache First, Network Fallback
 * 1. Busca en caché primero
 * 2. Si no está, descarga de red y guarda en caché
 * 3. Devuelve la respuesta
 */
async function cacheFirstStrategy(request, cacheName) {
    try {
        // 1. Buscar en caché
        const cachedResponse = await caches.match(request);

        if (cachedResponse) {
            console.log('[SW] Serving from cache:', request.url.substring(0, 80) + '...');
            return cachedResponse;
        }

        // 2. No está en caché, descargar de red
        console.log('[SW] Fetching from network:', request.url.substring(0, 80) + '...');
        const networkResponse = await fetch(request);

        // Verificar que la respuesta es válida
        // Para respuestas cross-origin (Firebase Storage), el tipo es 'opaque' y status es 0
        // Pero aún así son válidas y podemos cachearlas
        const isValidResponse = networkResponse && (
            networkResponse.status === 200 ||  // Normal response
            networkResponse.type === 'opaque'  // Cross-origin response (Firebase Storage)
        );

        if (!isValidResponse) {
            console.log('[SW] Invalid response, not caching:', networkResponse?.status);
            return networkResponse;
        }

        // 3. Guardar en caché (clonar porque el body solo se puede leer una vez)
        const cache = await caches.open(cacheName);
        cache.put(request, networkResponse.clone());
        console.log('[SW] Cached successfully:', request.url.substring(0, 60) + '...');

        return networkResponse;

    } catch (error) {
        console.error('[SW] Fetch failed:', error);

        // Intentar servir desde caché como fallback
        const cachedResponse = await caches.match(request);
        if (cachedResponse) {
            return cachedResponse;
        }

        // Si no hay caché, devolver error
        throw error;
    }
}

/**
 * Mensaje: Limpiar caché manualmente
 * Útil para forzar actualización de imágenes desde el admin
 */
self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'CLEAR_IMAGE_CACHE') {
        console.log('[SW] Clearing image cache...');
        caches.delete(IMAGE_CACHE_NAME).then(() => {
            console.log('[SW] Image cache cleared');
            // Notificar al cliente que se completó
            if (event.source) {
                event.source.postMessage({ type: 'CACHE_CLEARED' });
            }
        });
    }

    if (event.data && event.data.type === 'CLEAR_SPECIFIC_URL') {
        const urlToClear = event.data.url;
        console.log('[SW] Clearing specific URL from cache:', urlToClear);
        caches.open(IMAGE_CACHE_NAME).then((cache) => {
            cache.delete(urlToClear).then((deleted) => {
                console.log('[SW] URL deleted:', deleted);
            });
        });
    }
});

