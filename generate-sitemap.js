/**
 * Update index.html with SEO links from Firebase
 * Run with: node generate-sitemap.js
 */

import { initializeApp } from 'firebase/app';
import { getFirestore, collection, getDocs } from 'firebase/firestore';
import { readFileSync, writeFileSync } from 'fs';

const firebaseConfig = {
    apiKey: "AIzaSyAKr2_t_-JjzeiO8G8vQUkitqgDXi49ih0",
    authDomain: "jveloce-cf602.firebaseapp.com",
    projectId: "jveloce-cf602",
    storageBucket: "jveloce-cf602.firebasestorage.app",
    messagingSenderId: "779415799900",
    appId: "1:779415799900:web:759f5e87559312550dfe99",
    measurementId: "G-YSCZ95T9LY"
};

const app = initializeApp(firebaseConfig);
const db = getFirestore(app);

const BASE_URL = 'https://autosjveloce.com';
const COLLECTION_NAME = 'anuncios';

async function updateSeoLinks() {
    console.log('🔄 Obteniendo vehículos para enlaces SEO...');

    try {
        // Fetch all vehicles from Firebase
        const querySnapshot = await getDocs(collection(db, COLLECTION_NAME));
        const vehicles = [];

        querySnapshot.forEach((doc) => {
            const data = doc.data();
            vehicles.push({
                id: doc.id,
                ...data
            });
        });

        console.log(`✅ Encontrados ${vehicles.length} vehículos`);

        // Inject static links into index.html for SEO
        console.log('🔄 Inyectando enlaces estáticos en index.html...');
        
        const indexPath = 'index.html';
        let indexHtml = readFileSync(indexPath, 'utf8');

        let linksHtml = '\n';
        vehicles.forEach(vehicle => {
            const carName = `${vehicle.brand} ${vehicle.model} ${vehicle.year || ''}`.trim();
            const carUrl = `${BASE_URL}/Coches/detalle.html?id=${encodeURIComponent(vehicle.id)}`;
            linksHtml += `            <a href="${carUrl}">${escapeXml(carName)}</a>\n`;
        });
        linksHtml += '        ';

        // Regex to replace content between the injection markers
        const regex = /(<!-- SEO_LINKS_START -->)[\s\S]*?(<!-- SEO_LINKS_END -->)/;
        if (regex.test(indexHtml)) {
            indexHtml = indexHtml.replace(regex, `$1${linksHtml}$2`);
            writeFileSync(indexPath, indexHtml, 'utf8');
            console.log('✅ Enlaces SEO inyectados exitosamente en index.html');
        } else {
            console.warn('⚠️ No se encontraron las marcas <!-- SEO_LINKS_START --> y <!-- SEO_LINKS_END --> en index.html');
        }

    } catch (error) {
        console.error('❌ Error actualizando enlaces SEO:', error);
        process.exit(1);
    }

    process.exit(0);
}

function escapeXml(unsafe) {
    if (!unsafe) return '';
    return unsafe.toString()
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&apos;');
}

// Run the updater
updateSeoLinks();
