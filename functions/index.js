const { onRequest } = require('firebase-functions/v2/https');
const admin = require('firebase-admin');
const express = require('express');

if (!admin.apps.length) {
    admin.initializeApp();
}
const db = admin.firestore();
const app = express();

const isSocialBot = (userAgent) => {
    if (!userAgent) return false;
    const bots = [
        'facebookexternalhit',
        'WhatsApp',
        'Twitterbot',
        'LinkedInBot',
        'Slackbot',
        'TelegramBot',
        'Discordbot',
        'SkypeUriPreview'
    ];
    return bots.some(bot => userAgent.toLowerCase().includes(bot.toLowerCase()));
};

const isSearchBot = (userAgent) => {
    if (!userAgent) return false;
    const bots = [
        'googlebot',
        'googlebot-image',
        'bingbot',
        'yandexbot',
        'duckduckbot',
        'slurp',
        'baiduspider'
    ];
    return bots.some(bot => userAgent.toLowerCase().includes(bot.toLowerCase()));
};

const getFeaturedGalleryImage = (carData) => {
    if (carData.galleryExterior && Array.isArray(carData.galleryExterior) && carData.galleryExterior[2]) {
        return carData.galleryExterior[2];
    }
    if (carData.galleryExterior && Array.isArray(carData.galleryExterior) && carData.galleryExterior[0]) {
        return carData.galleryExterior[0];
    }
    return carData.image || 'https://lr-automoviles.web.app/assets/lr-logo.jpg';
};

// Escape HTML attribute characters to prevent broken HTML
const escapeHtmlAttr = (str) => {
    if (!str) return '';
    return str.toString()
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
};

const generateSeoGalleryHtml = (carData, carName) => {
    const exterior = (carData.galleryExterior || []).filter(Boolean);
    const interior = (carData.galleryInterior || []).filter(Boolean);
    const safeCarName = escapeHtmlAttr(carName);
    let html = '';

    if (exterior.length === 0 && interior.length === 0) {
        return '';
    }

    // === BLOCK A: Exterior - 2 stacked left + 1 large right (3ª foto destacada) ===
    if (exterior.length >= 3) {
        html += `
        <div class="gallery-block block-a">
            <div class="col-left-stacked">
                <div class="gallery-item"><img src="${escapeHtmlAttr(exterior[0])}" alt="${safeCarName} - Vista frontal"></div>
                <div class="gallery-item"><img src="${escapeHtmlAttr(exterior[1])}" alt="${safeCarName} - Vista 3/4 frontal"></div>
            </div>
            <div class="col-right-main">
                <div class="gallery-item main-img"><img src="${escapeHtmlAttr(exterior[2])}" alt="${safeCarName} - Foto principal de la galería de segunda mano en Valencia"></div>
            </div>
        </div>`;
    } else if (exterior.length > 0) {
        html += `
        <div class="gallery-block block-b">`;
        exterior.slice(0, Math.min(exterior.length, 2)).forEach((img, i) => {
            html += `
            <div class="gallery-item"><img src="${escapeHtmlAttr(img)}" alt="${safeCarName} - Exterior ${i + 1}"></div>`;
        });
        html += `
        </div>`;
    }

    // === BLOCK B: Exterior - 2 horizontal (photos 4 and 5) ===
    if (exterior.length >= 4) {
        const photo4 = exterior[3] ? `<div class="gallery-item"><img src="${escapeHtmlAttr(exterior[3])}" alt="${safeCarName} - Vista 3/4 trasera"></div>` : '';
        const photo5 = exterior[4] ? `<div class="gallery-item"><img src="${escapeHtmlAttr(exterior[4])}" alt="${safeCarName} - Vista trasera"></div>` : '';
        html += `
        <div class="gallery-block block-b">
            ${photo4}
            ${photo5}
        </div>`;
    }

    // === BLOCK C: Interior - First 3 photos in horizontal ===
    if (interior.length >= 1) {
        const interiorViews = ['Salpicadero', 'Asientos delanteros', 'Consola central'];
        html += `
        <div class="gallery-block block-c">`;
        interior.slice(0, 3).forEach((img, i) => {
            const viewName = interiorViews[i] || `Interior ${i + 1}`;
            html += `
            <div class="gallery-item"><img src="${escapeHtmlAttr(img)}" alt="${safeCarName} - ${escapeHtmlAttr(viewName)}"></div>`;
        });
        html += `
        </div>`;
    }

    // === BLOCK D: Interior - Remaining photos (4-9) in 3-column grid ===
    if (interior.length > 3) {
        const detailViews = ['Asientos traseros', 'Maletero', 'Volante', 'Panel de control', 'Detalles', 'Acabados'];
        html += `
        <div class="gallery-block block-d">`;
        interior.slice(3).forEach((img, i) => {
            const viewName = detailViews[i] || `Detalle ${i + 1}`;
            html += `
            <div class="gallery-item"><img src="${escapeHtmlAttr(img)}" alt="${safeCarName} - ${escapeHtmlAttr(viewName)}"></div>`;
        });
        html += `
        </div>`;
    }

    return html;
};

const generateSeoJsonLd = (carData, carName, carId) => {
    const exterior = (carData.galleryExterior || []).filter(Boolean);
    const interior = (carData.galleryInterior || []).filter(Boolean);
    const featuredImg = getFeaturedGalleryImage(carData);

    const imageList = [];
    if (featuredImg) imageList.push(featuredImg);
    if (carData.image && !imageList.includes(carData.image)) imageList.push(carData.image);
    exterior.forEach(img => { if (!imageList.includes(img)) imageList.push(img); });
    interior.forEach(img => { if (!imageList.includes(img)) imageList.push(img); });

    let numericPrice = carData.price ? carData.price.toString().replace(/[€\s]/g, '') : undefined;
    let numericKm = carData.km ? carData.km.replace(/[^\d]/g, '') : undefined;
    let numericCv = carData.cv ? carData.cv.replace(/[^\d]/g, '') : undefined;

    const schema = {
        "@context": "https://schema.org/",
        "@type": "Car",
        "name": carName,
        "brand": {
            "@type": "Brand",
            "name": carData.brand || "JVeloce"
        },
        "model": carData.model || "",
        "vehicleModelDate": carData.year ? carData.year.toString() : undefined,
        "mileageFromOdometer": numericKm ? {
            "@type": "QuantitativeValue",
            "value": numericKm,
            "unitCode": "KMT"
        } : undefined,
        "fuelType": carData.fuel || undefined,
        "vehicleTransmission": carData.transmission === 'Auto' ? 'Automático' : carData.transmission,
        "vehicleEngine": numericCv ? {
            "@type": "EngineSpecification",
            "enginePower": {
                "@type": "QuantitativeValue",
                "value": numericCv,
                "unitCode": "BHP"
            }
        } : undefined,
        "image": imageList.length > 0 ? imageList : undefined,
        "description": `${carName} de ocasión en Valencia. ${carData.fuel || ''} ${carData.km || ''} ${carData.cv ? carData.cv + ' CV' : ''}`.trim(),
        "offers": numericPrice ? {
            "@type": "Offer",
            "price": numericPrice,
            "priceCurrency": "EUR",
            "availability": "https://schema.org/InStock",
            "url": `https://lr-automoviles.web.app/Coches/detalle.html?id=${carId}`,
            "seller": {
                "@type": "AutoDealer",
                "name": "LR Automóviles",
                "telephone": "+34633518574",
                "url": "https://lr-automoviles.web.app",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "Massanasa",
                    "addressRegion": "Valencia",
                    "postalCode": "46470",
                    "addressCountry": "ES"
                }
            }
        } : undefined,
        "url": `https://lr-automoviles.web.app/Coches/detalle.html?id=${carId}`
    };

    Object.keys(schema).forEach(key => {
        if (schema[key] === undefined) delete schema[key];
    });

    return JSON.stringify(schema, null, 2);
};

app.get('/Coches/detalle.html', async (req, res) => {
    const userAgent = req.headers['user-agent'] || '';
    const carId = req.query.id;

    const social = isSocialBot(userAgent);
    const search = isSearchBot(userAgent);

    // 1. Social bots get lightweight raw HTML
    if (social && carId) {
        try {
            const doc = await db.collection('anuncios').doc(carId).get();
            if (!doc.exists) {
                return res.status(404).send('Vehículo no encontrado');
            }

            const carData = doc.data();
            const carName = `${carData.brand} ${carData.model} ${carData.year || ''}`.trim();
            const carImage = getFeaturedGalleryImage(carData);
            const optimizedImage = `https://wsrv.nl/?url=${encodeURIComponent(carImage)}&w=800&h=420&fit=cover&output=jpeg`;

            let priceStr = 'N/D€';
            if (carData.price) {
                let numericPrice = carData.price.toString().replace(/[€\s]/g, '');
                numericPrice = numericPrice.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
                priceStr = `${numericPrice}€`;
            }

            let description = `${priceStr}`;
            if (carData.fuel && carData.fuel !== 'N/D') description += ` | ${carData.fuel}`;
            if (carData.km && carData.km !== 'N/D') description += ` | ${carData.km}`;
            description += ` - Descubre este increíble ${carName} en LR Automóviles Valencia.`;

            const rawHtml = `<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>${carName} | LR Automóviles Valencia</title>
    <meta name="description" content="${description}">
    <!-- Open Graph (Facebook, WhatsApp) -->
    <meta property="og:title" content="${carName} | LR Automóviles">
    <meta property="og:description" content="${description}">
    <meta property="og:image" content="${optimizedImage}">
    <meta property="og:image:alt" content="${carName} - Foto principal de la galería">
    <meta property="og:image:width" content="800">
    <meta property="og:image:height" content="420">
    <meta property="og:url" content="https://lr-automoviles.web.app/Coches/detalle.html?id=${carId}">
    <meta property="og:type" content="article">
    <!-- Twitter Card -->
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="${carName} | LR Automóviles">
    <meta name="twitter:description" content="${description}">
    <meta name="twitter:image" content="${optimizedImage}">
    <!-- Explicit icon tags for messenger apps -->
    <link rel="icon" href="https://lr-automoviles.web.app/assets/icons/favicon.png" sizes="48x48">
    <link rel="apple-touch-icon" href="https://lr-automoviles.web.app/assets/icons/favicon.png">
</head>
<body>
    <h1>${carName}</h1>
    <p>${description}</p>
    <img src="${carImage}" alt="${carName} - Foto principal de la galería">
    <script>window.location.replace("/Coches/detalle-app.html?id=${carId}");</script>
</body>
</html>`;

            res.set('Cache-Control', 'private, no-cache, no-store, must-revalidate');
            return res.status(200).send(rawHtml);

        } catch (error) {
            console.error("Error fetching car for social bot:", error);
            return res.status(500).send('Error interno del servidor');
        }
    }

    // 2. Humans and Search bots get the full HTML framework with SSR injection
    if (!social) {
        console.log(`Serving request format: ${search ? 'Search Bot' : 'Human visitor'}.`, { userAgent, carId });
        try {
            const https = require('https');
            const targetUrl = `https://lrautomoviles.web.app/Coches/detalle-app.html?id=${carId || ''}`;

            let html = await new Promise((resolve, reject) => {
                https.get(targetUrl, (res) => {
                    if (res.statusCode < 200 || res.statusCode >= 300) {
                        return reject(new Error('Status ' + res.statusCode));
                    }
                    let data = '';
                    res.on('data', chunk => data += chunk);
                    res.on('end', () => resolve(data));
                }).on('error', err => reject(err));
            });

            // 3. For all valid carId requests (especially search bots), inject SSR SEO tags, Schema JSON-LD, and pre-rendered <img> gallery
            if (carId) {
                try {
                    const doc = await db.collection('anuncios').doc(carId).get();
                    if (doc.exists) {
                        const carData = doc.data();
                        const carName = `${carData.brand} ${carData.model} ${carData.year || ''}`.trim();

                        let priceStr = 'N/D€';
                        if (carData.price) {
                            let numericPrice = carData.price.toString().replace(/[€\s]/g, '');
                            numericPrice = numericPrice.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
                            priceStr = `${numericPrice}€`;
                        }

                        let description = `${priceStr}`;
                        if (carData.fuel && carData.fuel !== 'N/D') description += ` | ${carData.fuel}`;
                        if (carData.km && carData.km !== 'N/D') description += ` | ${carData.km}`;
                        description += ` - Descubre este increíble ${carName} en LR Automóviles Valencia.`;

                        const mainCarImage = getFeaturedGalleryImage(carData);
                        const jsonLdString = generateSeoJsonLd(carData, carName, carId);
                        const seoGalleryHtml = generateSeoGalleryHtml(carData, carName);

                        const injectedHeadTags = `
    <!-- SSR Injected SEO Tags & Structured Data for Google Indexing -->
    <title>${carName} | LR Automóviles Valencia</title>
    <link rel="canonical" id="canonical-url" href="https://lr-automoviles.web.app/Coches/detalle.html?id=${carId}">
    <link rel="icon" href="/favicon.ico" sizes="any">
    <link rel="icon" type="image/png" sizes="48x48" href="/assets/icons/favicon.png">
    <link rel="apple-touch-icon" href="/assets/icons/favicon.png">
    <meta name="description" content="${description}">
    <meta property="og:title" content="${carName} | LR Automóviles Valencia">
    <meta property="og:description" content="${description}">
    <meta property="og:image" content="${mainCarImage}">
    <meta property="og:image:alt" content="${carName} - Foto principal de la galería">
    <meta property="og:url" content="https://lr-automoviles.web.app/Coches/detalle.html?id=${carId}">
    <meta property="og:type" content="article">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="${carName} | LR Automóviles Valencia">
    <meta name="twitter:description" content="${description}">
    <meta name="twitter:image" content="${mainCarImage}">
    <script type="application/ld+json">
${jsonLdString}
    </script>`;

                        // Inject Head Tags - replace the entire inline SEO script block
                        const scriptStart = html.indexOf('<!-- SEO Tags to be dynamically injected for Googlebot -->');
                        const scriptEnd = html.indexOf('</script>', scriptStart);

                        if (scriptStart !== -1 && scriptEnd !== -1) {
                            html = html.substring(0, scriptStart) + injectedHeadTags + html.substring(scriptEnd + 9);
                        }

                        // Inject Pre-rendered Full SEO Gallery into #galleryContainer
                        const galleryMarker = /(<div\s+id=["']galleryContainer["']>)([\s\S]*?)(<\/div>)/i;
                        if (galleryMarker.test(html)) {
                            html = html.replace(galleryMarker, `$1${seoGalleryHtml}$3`);
                        }
                    } else {
                        // SEO FIX: If the car was deleted or doesn't exist, return HTTP 404
                        // so Google drops it from the index immediately (avoids Soft 404s).
                        // We still send the HTML shell so the human user sees the "Not Found" UI.
                        console.log(`Car ID ${carId} not found, returning 404`);
                        res.set('Cache-Control', 'private, no-cache, no-store, must-revalidate');
                        return res.status(404).send(html);
                    }
                } catch (err) {
                    console.error("Error fetching car data for SSR", err);
                }
            } else {
                // No carId provided -> redirect to inventory
                return res.redirect(301, '/index.html#inventory');
            }

            console.log("Successfully retrieved HTML shell via proxy with SSR injection.");
            res.set('Cache-Control', 'private, no-cache, no-store, must-revalidate');
            return res.status(200).send(html);
        } catch (error) {
            console.error("Failed to proxy HTML shell, falling back to JS redirect:", error);
            return res.status(200).send(`<!DOCTYPE html><html><head><title>LR Automóviles</title></head><body><script>window.location.href="/Coches/detalle-app.html?id=${carId || ''}";</script></body></html>`);
        }
    }
});

app.get('/sitemap.xml', async (req, res) => {
    try {
        const BASE_URL = 'https://lr-automoviles.web.app';
        const snapshot = await db.collection('anuncios').orderBy('order').get();
        const vehicles = [];
        snapshot.forEach(doc => {
            vehicles.push({ id: doc.id, ...doc.data() });
        });

        const escapeXml = (unsafe) => {
            if (!unsafe) return '';
            return unsafe.toString()
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&apos;');
        };

        const generateImageTag = (imageUrl, caption, title) => {
            let tag = `        <image:image>
            <image:loc>${escapeXml(imageUrl)}</image:loc>
            <image:caption>${escapeXml(caption)}</image:caption>`;
            if (title) {
                tag += `\n            <image:title>${escapeXml(title)}</image:title>`;
            }
            tag += `\n        </image:image>\n`;
            return tag;
        };

        const getCurrentDate = () => {
            return new Date().toISOString().split('T')[0];
        };

        let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
    <!-- Página principal -->
    <url>
        <loc>${BASE_URL}/</loc>
        <lastmod>${getCurrentDate()}</lastmod>
        <changefreq>weekly</changefreq>
        <priority>1.0</priority>
    </url>

    <!-- Página de reseñas -->
    <url>
        <loc>${BASE_URL}/resenas.html</loc>
        <lastmod>${getCurrentDate()}</lastmod>
        <changefreq>monthly</changefreq>
        <priority>0.7</priority>
    </url>
`;

        vehicles.forEach(vehicle => {
            const carName = `${vehicle.brand} ${vehicle.model} ${vehicle.year || ''}`.trim();
            xml += `    <url>
        <loc>${BASE_URL}/Coches/detalle.html?id=${encodeURIComponent(vehicle.id)}</loc>
        <lastmod>${getCurrentDate()}</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.8</priority>
`;

            // Priorizar la 3ª imagen de la galería exterior (foto principal destacada de la galería)
            // Esta imagen aparece como la grande en el layout y es la más representativa del vehículo
            if (vehicle.galleryExterior && Array.isArray(vehicle.galleryExterior) && vehicle.galleryExterior[2]) {
                xml += generateImageTag(
                    vehicle.galleryExterior[2],
                    `${carName} - Foto principal de la galería de segunda mano en Valencia`,
                    `${carName} ocasión Valencia`
                );
            } else if (vehicle.image) {
                xml += generateImageTag(
                    vehicle.image,
                    `${carName} - Imagen principal`,
                    `${carName} ocasión Valencia`
                );
            }

            if (vehicle.galleryExterior && Array.isArray(vehicle.galleryExterior)) {
                const exteriorViews = ['Vista frontal', 'Vista 3/4 frontal', 'Vista lateral', 'Vista 3/4 trasera', 'Vista trasera'];
                vehicle.galleryExterior.filter(img => img).forEach((img, index) => {
                    // La 3ª foto (index 2) ya fue añadida como imagen principal arriba - omitir para evitar duplicado
                    if (index === 2 && vehicle.galleryExterior[2]) return;
                    const caption = `${carName} - ${exteriorViews[index] || `Exterior ${index + 1}`}`;
                    xml += generateImageTag(img, caption, `${carName} vista exterior`);
                });
            }

            if (vehicle.galleryInterior && Array.isArray(vehicle.galleryInterior)) {
                const interiorViews = ['Salpicadero', 'Asientos delanteros', 'Consola central', 'Asientos traseros', 'Maletero', 'Volante', 'Panel de control', 'Detalles', 'Acabados'];
                vehicle.galleryInterior.filter(img => img).forEach((img, index) => {
                    const caption = `${carName} - ${interiorViews[index] || `Interior ${index + 1}`}`;
                    xml += generateImageTag(img, caption, `${carName} interior`);
                });
            }

            xml += `    </url>
`;
        });

        xml += `</urlset>`;

        res.header('Content-Type', 'application/xml');
        res.header('Cache-Control', 'public, max-age=3600, s-maxage=3600');
        return res.status(200).send(xml);

    } catch (error) {
        console.error('Error generating dynamic sitemap:', error);
        return res.status(500).send('Error interno al generar el sitemap');
    }
});

// Export the Express app as a Firebase Cloud Function (2nd Gen)
exports.renderSocialTags = onRequest({ region: 'us-central1', maxInstances: 10, cors: true, invoker: 'public' }, app);


