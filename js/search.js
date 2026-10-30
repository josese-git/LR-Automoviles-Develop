/**
 * Search Module - Reusable search functionality for all pages
 * Uses window.store (exposed from store.js via app.js) to get vehicle data
 */

// Base path detection for correct navigation
const isInSubfolder = window.location.pathname.includes('/Coches/');
const basePath = isInSubfolder ? '../' : '';

// Store vehicles data for search
let allCars = [];

// Get cars from the store - wait for store to be available
function initStore() {
    if (window.store) {
        window.store.subscribe((cars) => {
            allCars = cars;
        });
    } else {
        // Retry after a short delay if store not yet loaded
        setTimeout(initStore, 100);
    }
}
initStore();

// DOM Elements
const searchModal = document.getElementById('searchModal');
const searchInput = document.getElementById('searchInput');
const searchResults = document.getElementById('searchResults');
const searchCloseBtn = document.getElementById('searchCloseBtn');
const desktopSearchIcon = document.querySelector('.nav-links .search-icon');
const mobileSearchBtn = document.querySelector('.mobile-search-btn');

// Open search modal
function openSearch() {
    if (!searchModal) return;
    searchModal.classList.add('active');
    document.body.style.overflow = 'hidden';
    setTimeout(() => {
        if (searchInput) searchInput.focus();
    }, 100);
}

// Close search modal
function closeSearch() {
    if (!searchModal) return;
    searchModal.classList.remove('active');
    document.body.style.overflow = '';
    if (searchInput) searchInput.value = '';
    if (searchResults) {
        searchResults.innerHTML = '<p class="search-hint">Escribe para buscar por marca, modelo, año...</p>';
    }
}

// Search filter function
function filterCars(query) {
    const searchTerm = query.toLowerCase().trim();

    if (!searchTerm) {
        return [];
    }

    return allCars.filter(car => {
        const searchableText = [
            car.brand,
            car.model,
            car.year,
            car.fuel,
            car.transmission,
            car.km || '',
            car.price || ''
        ].join(' ').toLowerCase();

        return searchableText.includes(searchTerm);
    });
}

// Render search results
function renderResults(cars, query) {
    if (!searchResults) return;

    if (!query.trim()) {
        searchResults.innerHTML = '<p class="search-hint">Escribe para buscar por marca, modelo, año...</p>';
        return;
    }

    if (cars.length === 0) {
        searchResults.innerHTML = `
            <div class="search-no-results">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <circle cx="11" cy="11" r="8"></circle>
                    <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                    <line x1="8" y1="8" x2="14" y2="14"></line>
                    <line x1="14" y1="8" x2="8" y2="14"></line>
                </svg>
                <p>No se encontraron vehículos para "<strong>${query}</strong>"</p>
            </div>
        `;
        return;
    }

    // Adjust image paths based on current location
    searchResults.innerHTML = cars.map(car => {
        const imagePath = isInSubfolder ? `../${car.image}` : car.image;
        return `
            <div class="search-result-item" data-car-id="${car.id}">
                <img src="${imagePath}" alt="${car.brand} ${car.model}" class="search-result-img">
                <div class="search-result-info">
                    <h4 class="search-result-title">${car.brand} ${car.model}</h4>
                    <div class="search-result-specs">
                        <span>${car.year}</span>
                        <span>${car.fuel}</span>
                        <span>${car.transmission}</span>
                        ${car.km ? `<span>${car.km}</span>` : ''}
                    </div>
                </div>
                <svg class="search-result-arrow" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="9 18 15 12 9 6"></polyline>
                </svg>
            </div>
        `;
    }).join('');

    // Add click handlers to results
    document.querySelectorAll('.search-result-item').forEach(item => {
        item.addEventListener('click', () => {
            const carId = item.getAttribute('data-car-id');
            closeSearch();
            // Navigate to detail page with correct path
            window.location.href = `${basePath}Coches/detalle.html?id=${carId}`;
        });
    });
}

// Initialize event listeners
function initSearchListeners() {
    if (desktopSearchIcon) {
        desktopSearchIcon.addEventListener('click', (e) => {
            e.preventDefault();
            openSearch();
        });
    }

    if (mobileSearchBtn) {
        mobileSearchBtn.addEventListener('click', (e) => {
            e.preventDefault();
            openSearch();
        });
    }

    if (searchCloseBtn) {
        searchCloseBtn.addEventListener('click', closeSearch);
    }

    // Close on backdrop click
    if (searchModal) {
        searchModal.addEventListener('click', (e) => {
            if (e.target === searchModal) {
                closeSearch();
            }
        });
    }

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && searchModal && searchModal.classList.contains('active')) {
            closeSearch();
        }
    });

    // Search input handler with debounce
    let searchTimeout;
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                const query = e.target.value;
                const results = filterCars(query);
                renderResults(results, query);
            }, 150);
        });
    }
}

// Initialize on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSearchListeners);
} else {
    initSearchListeners();
}

export { openSearch, closeSearch };
