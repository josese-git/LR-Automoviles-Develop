/**
 * Gallery Lightbox with Dual-Mode Zoom & Navigation
 * - Desktop: Click to Zoom, Mouse Move to Pan.
 * - Mobile: Tap to Zoom, Pinch to Scale, Drag to Pan.
 * - Navigation: Next/Prev buttons, Counter (X of Y).
 */

document.addEventListener('DOMContentLoaded', () => {
    const lightbox = document.getElementById('lightbox');
    const lightboxImg = document.getElementById('lightbox-img');
    const closeBtn = document.querySelector('.lightbox-close');
    const prevBtn = document.querySelector('.lightbox-prev');
    const nextBtn = document.querySelector('.lightbox-next');
    const counter = document.querySelector('.lightbox-counter');

    // Select all images from the gallery blocks
    const galleryItems = Array.from(document.querySelectorAll('.gallery-item img'));

    // State
    let currentIndex = 0;
    let isZoomed = false;

    // Mobile State
    let scale = 1;
    let pointX = 0;
    let pointY = 0;
    let startX = 0;
    let startY = 0;
    let isDragging = false;

    // Tap detection state
    let tapStartTime = 0;
    let tapStartX = 0;
    let tapStartY = 0;

    // Open Lightbox
    galleryItems.forEach((img, index) => {
        img.addEventListener('click', () => {
            openLightbox(index);
        });
    });

    function openLightbox(index) {
        currentIndex = index;
        updateLightboxImage();
        lightbox.classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    function closeLightbox() {
        lightbox.classList.remove('active');
        document.body.style.overflow = '';
        resetZoom();
    }

    function updateLightboxImage() {
        resetZoom(); // Always reset zoom when changing images

        const img = galleryItems[currentIndex];
        lightboxImg.src = img.src;

        // Update Counter
        if (counter) {
            counter.textContent = `${currentIndex + 1} de ${galleryItems.length}`;
        }
    }

    function showNext() {
        currentIndex = (currentIndex + 1) % galleryItems.length;
        updateLightboxImage();
    }

    function showPrev() {
        currentIndex = (currentIndex - 1 + galleryItems.length) % galleryItems.length;
        updateLightboxImage();
    }

    // Event Listeners
    closeBtn.addEventListener('click', closeLightbox);

    if (prevBtn) prevBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        showPrev();
    });

    if (nextBtn) nextBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        showNext();
    });

    lightbox.addEventListener('click', (e) => {
        if (e.target === lightbox || e.target.classList.contains('lightbox-content')) {
            closeLightbox();
        }
    });

    // Keyboard Navigation
    document.addEventListener('keydown', (e) => {
        if (!lightbox.classList.contains('active')) return;

        if (e.key === 'Escape') closeLightbox();
        if (e.key === 'ArrowRight') showNext();
        if (e.key === 'ArrowLeft') showPrev();
    });

    // --- ZOOM CORE LOGIC ---

    // 1. DESKTOP (Mouse)
    lightboxImg.addEventListener('click', (e) => {
        if (e.pointerType === 'mouse' && !isDragging) {
            toggleDesktopZoom(e);
        }
    });

    lightboxImg.addEventListener('mousemove', (e) => {
        if (isZoomed && scale === 1) {
            moveImageDesktop(e);
        }
    });

    // 2. MOBILE (Touch)
    let initialDistance = 0;
    let initialScale = 1;

    lightboxImg.addEventListener('touchstart', (e) => {
        if (e.touches.length === 1) {
            startX = e.touches[0].clientX - pointX;
            startY = e.touches[0].clientY - pointY;
            isDragging = true;

            tapStartTime = new Date().getTime();
            tapStartX = e.touches[0].clientX;
            tapStartY = e.touches[0].clientY;

        } else if (e.touches.length === 2) {
            isDragging = false;
            initialDistance = getDistance(e.touches);
            initialScale = scale;
        }
    }, { passive: false });

    lightboxImg.addEventListener('touchmove', (e) => {
        e.preventDefault();

        if (e.touches.length === 1 && isDragging) {
            const currentX = e.touches[0].clientX;
            const currentY = e.touches[0].clientY;

            if (scale > 1) {
                pointX = currentX - startX;
                pointY = currentY - startY;
                updateTransform();
            }

        } else if (e.touches.length === 2) {
            const currentDistance = getDistance(e.touches);
            if (initialDistance > 0) {
                const distanceDiff = currentDistance / initialDistance;
                scale = initialScale * distanceDiff;
                scale = Math.max(1, Math.min(scale, 4));
                updateTransform();
            }
        }
    }, { passive: false });

    lightboxImg.addEventListener('touchend', (e) => {
        if (e.changedTouches.length === 1 && e.touches.length === 0) {
            const currentTime = new Date().getTime();
            const tapDuration = currentTime - tapStartTime;

            const touch = e.changedTouches[0];
            const dist = Math.hypot(touch.clientX - tapStartX, touch.clientY - tapStartY);

            if (tapDuration < 300 && dist < 10) {
                handleMobileTap();
            }
        }

        isDragging = false;

        if (scale < 1) {
            scale = 1;
            pointX = 0;
            pointY = 0;
            updateTransform();
        }
    });

    function handleMobileTap() {
        if (scale > 1.1) {
            scale = 1;
            pointX = 0;
            pointY = 0;
            updateTransform();
            isZoomed = false;
        } else {
            scale = 2.5;
            pointX = 0;
            pointY = 0;
            updateTransform();
            isZoomed = true;
        }
    }

    // --- HELPER FUNCTIONS ---

    function resetZoom() {
        isZoomed = false;
        scale = 1;
        pointX = 0;
        pointY = 0;

        lightboxImg.classList.remove('zoomed');
        lightboxImg.style.transform = '';
        lightboxImg.style.transformOrigin = 'center center';
    }

    function toggleDesktopZoom(e) {
        if (isZoomed) {
            resetZoom();
        } else {
            isZoomed = true;
            lightboxImg.classList.add('zoomed');
            moveImageDesktop(e);
        }
    }

    function moveImageDesktop(e) {
        const offsetX = e.clientX - (window.innerWidth - lightboxImg.offsetWidth) / 2;
        const offsetY = e.clientY - (window.innerHeight - lightboxImg.offsetHeight) / 2;
        const xPercent = (offsetX / lightboxImg.offsetWidth) * 100;
        const yPercent = (offsetY / lightboxImg.offsetHeight) * 100;
        lightboxImg.style.transformOrigin = `${xPercent}% ${yPercent}%`;
    }

    function updateTransform() {
        lightboxImg.style.transform = `translate(${pointX}px, ${pointY}px) scale(${scale})`;
        lightboxImg.classList.remove('zoomed');
    }

    function getDistance(touches) {
        return Math.hypot(
            touches[0].clientX - touches[1].clientX,
            touches[0].clientY - touches[1].clientY
        );
    }
});
