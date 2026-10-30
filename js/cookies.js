/**
 * Aviso de Cookies para LR Automóviles
 * Diseño discreto, desplegable (collapsible) y totalmente adaptado a móviles.
 */
(function () {
    const COOKIE_STORAGE_KEY = 'lr_cookies_consent';

    function initCookieBanner() {
        try {
            if (localStorage.getItem(COOKIE_STORAGE_KEY)) {
                return; // Ya existe consentimiento previo guardado
            }
        } catch (e) {
            // Manejo de restricciones en almacenamiento local
        }

        const banner = document.createElement('aside');
        banner.id = 'lrCookieBanner';
        banner.className = 'cookie-banner';
        banner.setAttribute('role', 'dialog');
        banner.setAttribute('aria-label', 'Aviso de Cookies');

        banner.innerHTML = `
            <div class="cookie-banner-bar">
                <div class="cookie-bar-info">
                    <span class="cookie-icon">🍪</span>
                    <span class="cookie-bar-text">Usamos cookies para tu experiencia.</span>
                    <button type="button" id="cookieToggleBtn" class="cookie-toggle-btn" aria-expanded="false" title="Ver opciones y detalles">
                        <span id="cookieToggleText">Detalles</span>
                        <svg class="cookie-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="6 9 12 15 18 9"></polyline>
                        </svg>
                    </button>
                </div>
                <div class="cookie-bar-actions">
                    <button type="button" id="cookieAcceptQuick" class="cookie-btn cookie-btn-primary cookie-btn-sm">Aceptar</button>
                </div>
            </div>

            <!-- Panel desplegable con información detallada y opciones -->
            <div class="cookie-details" id="cookieDetails">
                <p>En <strong>LR Automóviles</strong> utilizamos cookies propias y técnicas para el correcto funcionamiento del sitio, y analíticas para optimizar tu experiencia. Más información en nuestra <a href="/politica-privacidad.html" target="_blank" rel="noopener noreferrer">Política de Privacidad</a>.</p>
                <div class="cookie-details-actions">
                    <button type="button" id="cookieRejectBtn" class="cookie-btn cookie-btn-secondary">Solo Necesarias</button>
                    <button type="button" id="cookieAcceptBtn" class="cookie-btn cookie-btn-primary">Aceptar Todas</button>
                </div>
            </div>
        `;

        document.body.appendChild(banner);

        // Animar entrada suave desde abajo
        requestAnimationFrame(() => {
            setTimeout(() => {
                banner.classList.add('cookie-banner-visible');
            }, 100);
        });

        // Alternar desplegable de detalles
        const toggleBtn = document.getElementById('cookieToggleBtn');
        const toggleText = document.getElementById('cookieToggleText');

        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                const isExpanded = banner.classList.toggle('expanded');
                toggleBtn.setAttribute('aria-expanded', isExpanded);
                if (toggleText) {
                    toggleText.textContent = isExpanded ? 'Cerrar' : 'Detalles';
                }
            });
        }

        // Función para cerrar y persistir decisión
        const closeBanner = (consentType) => {
            try {
                localStorage.setItem(COOKIE_STORAGE_KEY, consentType);
            } catch (e) {
                console.warn('No se pudo guardar preferencia en localStorage:', e);
            }

            banner.classList.remove('cookie-banner-visible');
            setTimeout(() => {
                if (banner && banner.parentNode) {
                    banner.parentNode.removeChild(banner);
                }
            }, 450);
        };

        const acceptQuick = document.getElementById('cookieAcceptQuick');
        const acceptFull = document.getElementById('cookieAcceptBtn');
        const rejectBtn = document.getElementById('cookieRejectBtn');

        if (acceptQuick) acceptQuick.addEventListener('click', () => closeBanner('all'));
        if (acceptFull) acceptFull.addEventListener('click', () => closeBanner('all'));
        if (rejectBtn) rejectBtn.addEventListener('click', () => closeBanner('essential'));
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initCookieBanner);
    } else {
        initCookieBanner();
    }
})();
