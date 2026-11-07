// A tiny particle system on one full-screen canvas that exists only while drawing.
import type { EffectsLevel } from './settings';

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  max: number;
  size: number;
  color: string;
  spin: number;
  angle: number;
  shape: 'dot' | 'rect';
}

let canvas: HTMLCanvasElement | null = null;
let particles: Particle[] = [];
let running = false;

function ensureCanvas(): CanvasRenderingContext2D | null {
  if (typeof document === 'undefined') return null;
  if (!canvas) {
    canvas = document.createElement('canvas');
    canvas.setAttribute('aria-hidden', 'true');
    Object.assign(canvas.style, { position: 'fixed', inset: '0', width: '100%', height: '100%', pointerEvents: 'none', zIndex: '60' });
    document.body.appendChild(canvas);
  }
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  if (canvas.width !== innerWidth * dpr || canvas.height !== innerHeight * dpr) {
    canvas.width = innerWidth * dpr;
    canvas.height = innerHeight * dpr;
  }
  const ctx = canvas.getContext('2d');
  ctx?.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

function loop(): void {
  const ctx = ensureCanvas();
  if (!ctx || !canvas) return;
  ctx.clearRect(0, 0, innerWidth, innerHeight);
  particles = particles.filter((p) => p.life < p.max);
  for (const p of particles) {
    p.life += 1;
    p.vy += 0.18; // gravity
    p.vx *= 0.985;
    p.x += p.vx;
    p.y += p.vy;
    p.angle += p.spin;
    const fade = 1 - p.life / p.max;
    ctx.globalAlpha = Math.max(0, fade);
    ctx.fillStyle = p.color;
    if (p.shape === 'dot') {
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      ctx.fill();
    } else {
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.angle);
      ctx.fillRect(-p.size, -p.size / 2, p.size * 2, p.size);
      ctx.restore();
    }
  }
  ctx.globalAlpha = 1;
  if (particles.length) {
    requestAnimationFrame(loop);
  } else {
    running = false;
    canvas.remove();
    canvas = null;
  }
}

function start(): void {
  if (!running) {
    running = true;
    requestAnimationFrame(loop);
  }
}

const PALETTE = ['#16a34a', '#7c3aed', '#d97706', '#2563eb', '#db2777', '#0ea5e9', '#facc15'];

/** Sparks from one point, for a single swipe. */
export function burst(x: number, y: number, colors: string[], level: EffectsLevel): void {
  if (level === 'off') return;
  const count = level === 'full' ? 22 : 8;
  for (let i = 0; i < count; i++) {
    const a = Math.random() * Math.PI * 2;
    const speed = 2 + Math.random() * (level === 'full' ? 5 : 3);
    particles.push({
      x,
      y,
      vx: Math.cos(a) * speed,
      vy: Math.sin(a) * speed - 2,
      life: 0,
      max: 34 + Math.random() * 18,
      size: 2 + Math.random() * 2.5,
      color: colors[i % colors.length],
      spin: 0,
      angle: 0,
      shape: 'dot',
    });
  }
  start();
}

/** Confetti across the screen, for a cleared round or a milestone. */
export function confetti(level: EffectsLevel, amount = 1): void {
  if (level === 'off') return;
  const count = Math.round((level === 'full' ? 140 : 40) * amount);
  for (let i = 0; i < count; i++) {
    const fromLeft = i % 2 === 0;
    particles.push({
      x: fromLeft ? -10 : innerWidth + 10,
      y: innerHeight * (0.45 + Math.random() * 0.4),
      vx: (fromLeft ? 1 : -1) * (5 + Math.random() * 9),
      vy: -(9 + Math.random() * 9),
      life: 0,
      max: 90 + Math.random() * 60,
      size: 3 + Math.random() * 4,
      color: PALETTE[i % PALETTE.length],
      spin: (Math.random() - 0.5) * 0.4,
      angle: Math.random() * Math.PI,
      shape: Math.random() < 0.7 ? 'rect' : 'dot',
    });
  }
  start();
}
