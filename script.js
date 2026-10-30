document.addEventListener('DOMContentLoaded', () => {
    // 1. Mouse Follow Information (Cursor Glow)
    const cursorGlow = document.getElementById('cursorGlow');

    if (cursorGlow) {
        document.addEventListener('mousemove', (e) => {
            cursorGlow.style.left = e.clientX + 'px';
            cursorGlow.style.top = e.clientY + 'px';
        });
    }

    // 2. 3D Tilt Effect for Cars
    const cards = document.querySelectorAll('.car-card');

    cards.forEach(card => {
        card.addEventListener('mousemove', (e) => {
            const rect = card.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;

            // Calculate rotation based on cursor position relative to center
            const centerX = rect.width / 2;
            const centerY = rect.height / 2;

            const rotateX = ((y - centerY) / centerY) * -10; // Max 10 deg rotation
            const rotateY = ((x - centerX) / centerX) * 10;

            card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(1.02)`;
        });

        card.addEventListener('mouseleave', () => {
            // Reset position
            card.style.transform = 'perspective(1000px) rotateX(0) rotateY(0) scale(1)';
        });
    });

    // 3. Smooth Scroll
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth'
                });
            }
        });
    });

    // 4. Mobile Menu Toggle
    const hamburger = document.getElementById('hamburgerBtn');
    const navLinks = document.querySelector('.nav-links');

    if (hamburger) {
        hamburger.addEventListener('click', () => {
            navLinks.classList.toggle('active');
            hamburger.classList.toggle('toggle');
            document.body.classList.toggle('menu-open');
        });

        // Auto-close menu when a link is clicked AND update active state
        document.querySelectorAll('.nav-links a').forEach(link => {
            link.addEventListener('click', function () {
                // Remove active class from all links
                document.querySelectorAll('.nav-links a').forEach(l => l.classList.remove('active'));

                // Add active class to the clicked link
                this.classList.add('active');

                // Close the menu
                navLinks.classList.remove('active');
                hamburger.classList.remove('toggle');
                document.body.classList.remove('menu-open'); // Remove blur
            });
        });
    }
});

