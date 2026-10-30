/**
 * Aviso de Cookies para LR Automóviles
 * Persiste consentimiento en localStorage y armoniza con el diseño glow rojo y dark glassmorphism.
 */
(function () {
    const COOKIE_STORAGE_KEY = 'lr_cookies_consent';

    function initCookieBanner() {
        try {
            if (localStorage.getItem(COOKIE_STORAGE_KEY)) {
                return; // Ya existe decisión previa del usuario
            }
        } catch (e) {
            // Manejo de restricciones en iframes o modo incógnito estricto
        }

        const banner = document.createElement('aside');
        banner.id = 'lrCookieBanner';
        banner.className = 'cookie-banner';
        banner.setAttribute('role', 'dialog');
        banner.setAttribute('aria-label', 'Aviso de Cookies');

        banner.innerHTML = `
            <div class="cookie-banner-content">
                <div class="cookie-banner-text">
                    <div class="cookie-title">
                        <span class="cookie-icon">🍪</span>
                        <span>Uso de Cookies</span>
                    </div>
                    <p>En <strong>LR Automóviles</strong> utilizamos cookies propias y técnicas para garantizar el correcto funcionamiento del sitio web y mejorar su experiencia de navegación. Puede obtener más información en nuestra <a href="/politica-privacidad.html" target="_blank" rel="noopener noreferrer">Política de Privacidad</a>.</p>
                </div>
                <div class="cookie-banner-actions">
                    <button type="button" id="cookieRejectBtn" class="cookie-btn cookie-btn-secondary">Solo Necesarias</button>
                    <button type="button" id="cookieAcceptBtn" class="cookie-btn cookie-btn-primary">Aceptar Todas</button>
                </div>
            </div>
        `;

        document.body.appendChild(banner);

        // Disparar animación de entrada
        requestAnimationFrame(() => {
            setTimeout(() => {
                banner.classList.add('cookie-banner-visible');
            }, 100);
        });

        const closeBanner = (consentType) => {
            try {
                localStorage.setItem(COOKIE_STORAGE_KEY, consentType);
            } catch (e) {
                console.warn('No se pudo guardar la preferencia de cookies en localStorage:', e);
            }

            banner.classList.remove('cookie-banner-visible');
            setTimeout(() => {
                if (banner && banner.parentNode) {
                    banner.parentNode.removeChild(banner);
                }
            }, 450);
        };

        const acceptBtn = document.getElementById('cookieAcceptBtn');
        const rejectBtn = document.getElementById('cookieRejectBtn');

        if (acceptBtn) {
            acceptBtn.addEventListener('click', () => closeBanner('all'));
        }
        if (rejectBtn) {
            rejectBtn.addEventListener('click', () => closeBanner('essential'));
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initCookieBanner);
    } else {
        initCookieBanner();
    }
})();
