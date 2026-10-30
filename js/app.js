/**
 * App.js - Main Render Logic for Home Page
 */

// Note: Ensure this is treated as a module in HTML
import store from './store.js';

document.addEventListener('DOMContentLoaded', () => {
    // Determine which page we are on and init appropriately
    // The main page uses index.html, which has this script
    // We subscribe to the store to get real-time updates
    store.subscribe((cars) => {
        renderInventory(cars);
    });
});

function renderInventory(cars) {
    const container = document.querySelector('.car-grid');
    if (!container) return;

    // If no cars, show empty message
    if (cars.length === 0) {
        container.innerHTML = `
            <div style="text-align: center; padding: 50px; grid-column: 1 / -1; width: 100%;">
                <h3 style="color: var(--gold-primary); font-family: 'Orbitron', sans-serif;">Inventario Actualizado</h3>
                <p style="color: #888; margin-top: 10px;">No hay vehículos disponibles en este momento.</p>
            </div>
        `;
        return;
    }

    container.innerHTML = ''; // Clear loader/content only when we have data to show

    cars.forEach(car => {

        // Determine Logo Class (wide or normal)
        // Determine Logo Class (wide or normal)
        const isWide = car.logoClass && car.logoClass.includes('wide');
        const logoClass = isWide ? `brand-logo-floating ${car.logoClass}` : 'brand-logo-floating';

        // Calculate Logo Size
        // standard: 80x80, wide: 200x100
        const baseW = isWide ? 200 : 80;
        const baseH = isWide ? 100 : 80;

        const scale = car.logoSize ? (parseFloat(car.logoSize) / 100) : 1;
        let style = `width: ${baseW * scale}px; height: ${baseH * scale}px;`;

        if (car.logoMargin !== undefined && car.logoMargin !== "" && car.logoMargin !== null) {
            style += ` margin-bottom: ${car.logoMargin}px;`;
        }

        // Sold Overlay
        const soldOverlay = car.sold ? '<img src="assets/vendido.png" class="sold-overlay-img" alt="Vendido">' : '';

        const card = document.createElement('div');
        card.className = `car-card glass-panel ${car.sold ? 'sold' : ''}`;
        card.setAttribute('data-tilt', ''); // Tilt.js attribute

        card.innerHTML = `
            <div class="card-image-wrapper">
                ${soldOverlay}
                <img src="${car.image}" alt="${car.brand} ${car.model}" class="car-image">
            </div>

            <div class="card-details">
                <img src="${car.logo}" alt="${car.brand}" class="${logoClass}" style="${style}">
                <h3 class="car-model">${car.brand} ${car.model}</h3>
                <div class="car-specs">
                    <span>${car.year}</span>
                    <span>${car.fuel}</span>
                    <span>${car.transmission}</span>
                    ${car.km ? `<span>${car.km}</span>` : ''}
                </div>
            </div>
            <div class="card-glow"></div>
        `;

        // Add click event to navigate to detail page
        card.style.cursor = 'pointer';
        card.addEventListener('click', () => {
            window.location.href = `Coches/detalle.html?id=${car.id}`;
        });

        container.appendChild(card);
    });
}
