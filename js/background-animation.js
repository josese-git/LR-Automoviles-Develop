/**
 * Interactive Fog/Smoke Background
 * PERFORMANCE MODE: Sprite-based Rendering
 * (No heavy blur filters = Maximum FPS)
 */

const canvas = document.createElement('canvas');
const ctx = canvas.getContext('2d');
document.body.appendChild(canvas);

// Configuration
const CONFIG = {
    particleCount: 100,
    bgFill: '#000000',
    mouseRepelDist: 200,
    mouseRepelForce: 0.005
};

// --------------------------------------------------------
// OPTIMIZATION: Create a "Smoke Sprite" off-screen
// We draw a perfect gradients ONCE, then just copy-paste it
// --------------------------------------------------------
const spriteSize = 256;
const smokeSprite = document.createElement('canvas');
smokeSprite.width = spriteSize;
smokeSprite.height = spriteSize;
const sCtx = smokeSprite.getContext('2d');

// Create a smooth radial gradient "puff"
const grad = sCtx.createRadialGradient(spriteSize / 2, spriteSize / 2, 0, spriteSize / 2, spriteSize / 2, spriteSize / 2);
grad.addColorStop(0, 'rgba(220, 220, 220, 0.4)'); // Core brightness
grad.addColorStop(0.3, 'rgba(220, 220, 220, 0.1)'); // Soft middle
grad.addColorStop(1, 'rgba(220, 220, 220, 0)'); // Fade to nothing

sCtx.fillStyle = grad;
sCtx.arc(spriteSize / 2, spriteSize / 2, spriteSize / 2, 0, Math.PI * 2);
sCtx.fill();
// --------------------------------------------------------

let particles = [];
let mouse = { x: -9999, y: -9999 };
let scrollY = window.scrollY;
let scrollVel = 0;

// Setup Main Canvas
canvas.id = 'bgCanvas';
canvas.style.position = 'fixed';
canvas.style.top = '0';
canvas.style.left = '0';
canvas.style.width = '100%';
canvas.style.height = '100%';
canvas.style.zIndex = '-1';
canvas.style.pointerEvents = 'none';

function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
}
window.addEventListener('resize', resize);
resize();

document.addEventListener('mousemove', (e) => {
    mouse.x = e.clientX;
    mouse.y = e.clientY;
});

document.addEventListener('scroll', () => {
    const newScroll = window.scrollY;
    const diff = newScroll - scrollY;
    scrollVel = diff * 0.5;
    scrollY = newScroll;
});

class FogParticle {
    constructor() {
        this.reset(true);
    }

    reset(startRandom = false) {
        this.x = Math.random() * canvas.width;

        // Distribution: Top (45%), Bottom (45%), Center (10%)
        const zone = Math.random();
        if (zone < 0.45) {
            this.y = Math.random() * canvas.height * 0.25;
            this.vy = Math.random() * 0.3 + 0.1;
        } else if (zone < 0.9) {
            this.y = canvas.height - (Math.random() * canvas.height * 0.25);
            this.vy = -Math.random() * 0.3 - 0.1;
        } else {
            this.y = Math.random() * canvas.height;
            this.vy = (Math.random() - 0.5) * 0.2;
        }

        if (!startRandom) {
            this.y = (this.vy > 0) ? -100 : canvas.height + 100;
        }

        this.vx = (Math.random() - 0.5) * 0.5;

        // Visual Properties
        this.size = Math.random() * 400 + 200; // Large sprites for coverage

        this.life = Math.random() * 0.5 + 0.2;
        this.decay = Math.random() * 0.001 + 0.0005;

        this.angle = Math.random() * Math.PI * 2;
        this.angleVel = (Math.random() - 0.5) * 0.002;

        // Stretch the sprite for "wispiness"
        this.scaleX = 2 + Math.random();
        this.scaleY = 1 + Math.random();
    }

    update() {
        this.x += this.vx;
        this.y += this.vy;
        this.angle += this.angleVel;
        this.y -= scrollVel * 0.1;

        // Mouse Interaction
        const dx = this.x - mouse.x;
        const dy = this.y - mouse.y;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < CONFIG.mouseRepelDist) {
            const angle = Math.atan2(dy, dx);
            const force = (CONFIG.mouseRepelDist - dist) / CONFIG.mouseRepelDist;
            const push = force * CONFIG.mouseRepelForce * 5;

            this.vx += Math.cos(angle) * push;
            this.vy += Math.sin(angle) * push;
        }

        this.vx *= 0.99;
        this.life -= this.decay;

        if (this.life <= 0) this.reset();
    }

    draw() {
        // Optimization: Don't draw if invisible opacity
        if (this.life <= 0.01) return;

        ctx.save();
        ctx.translate(this.x, this.y);
        ctx.rotate(this.angle);
        ctx.scale(this.scaleX, this.scaleY);

        // Opacity
        ctx.globalAlpha = this.life * 0.3; // Base opacity

        // DRAW THE PRE-RENDERED SPRITE
        // (x, y, width, height) - centered
        ctx.drawImage(smokeSprite, -this.size / 2, -this.size / 2, this.size, this.size);

        ctx.restore();
    }
}

function init() {
    particles = [];
    for (let i = 0; i < CONFIG.particleCount; i++) {
        particles.push(new FogParticle());
    }
}

function animate() {
    scrollVel *= 0.9;

    // Standard Clear - No filter needed!
    ctx.filter = 'none';
    ctx.fillStyle = CONFIG.bgFill;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Enabling 'screen' blend mode makes smoke additive and cooler (optional)
    // ctx.globalCompositeOperation = 'screen'; 

    particles.forEach(p => {
        p.update();
        p.draw();
    });

    // ctx.globalCompositeOperation = 'source-over'; 

    requestAnimationFrame(animate);
}

init();
animate();
