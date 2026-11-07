// Pure gesture math for the swipe card. No DOM here so it can be unit tested.

export type SwipeAction = 'keep' | 'archive' | 'group' | 'prioritize';

/** Distance past which a drag commits, in CSS px. */
export const SWIPE_THRESHOLD = 90;
/** A release this fast (px/ms) along the dominant axis commits even if short. */
export const FLICK_VELOCITY = 0.6;
/** A flick still has to travel at least this far, so a jittery tap can't swipe. */
export const FLICK_MIN_DISTANCE = 30;
/** Movement under this many px counts as "not moving" (tap or long press). */
export const TAP_SLOP = 10;
export const LONG_PRESS_MS = 500;

/**
 * Decide what a released drag means. The dominant axis wins (ties go
 * horizontal). Right = keep, left = archive, up = group, down = prioritize.
 * Returns null when the drag should spring back.
 */
export function classifySwipe(dx: number, dy: number, vx = 0, vy = 0): SwipeAction | null {
  const ax = Math.abs(dx);
  const ay = Math.abs(dy);
  const horizontal = ax >= ay;
  const dist = horizontal ? dx : dy;
  const vel = horizontal ? vx : vy;
  if (Math.abs(dist) < TAP_SLOP) return null;

  const past = Math.abs(dist) >= SWIPE_THRESHOLD;
  const flick =
    Math.abs(vel) >= FLICK_VELOCITY &&
    Math.abs(dist) >= FLICK_MIN_DISTANCE &&
    Math.sign(vel) === Math.sign(dist);
  if (!past && !flick) return null;

  if (horizontal) return dist > 0 ? 'keep' : 'archive';
  return dist < 0 ? 'group' : 'prioritize';
}

/** True when the pointer barely moved and was released before a long press. */
export function isTap(dx: number, dy: number, durationMs: number): boolean {
  return Math.hypot(dx, dy) < TAP_SLOP && durationMs < LONG_PRESS_MS;
}

/** Stamp opacity per action while dragging (0..1), on the dominant axis only. */
export function stampOpacities(dx: number, dy: number): Record<SwipeAction, number> {
  const horizontal = Math.abs(dx) >= Math.abs(dy);
  const f = (v: number) => Math.max(0, Math.min(v / SWIPE_THRESHOLD, 1));
  return {
    keep: horizontal ? f(dx) : 0,
    archive: horizontal ? f(-dx) : 0,
    group: horizontal ? 0 : f(-dy),
    prioritize: horizontal ? 0 : f(dy),
  };
}

/** The action a drag would commit to if released now (for haptics on crossing). */
export function armedAction(dx: number, dy: number): SwipeAction | null {
  return classifySwipe(dx, dy, 0, 0);
}

interface Sample {
  x: number;
  y: number;
  t: number;
}

/** Release velocity from the last `windowMs` of pointer samples, in px/ms. */
export class VelocityTracker {
  private samples: Sample[] = [];
  constructor(private windowMs = 100) {}

  reset(): void {
    this.samples = [];
  }

  add(x: number, y: number, t: number): void {
    this.samples.push({ x, y, t });
    const cutoff = t - this.windowMs;
    while (this.samples.length > 2 && this.samples[0].t < cutoff) this.samples.shift();
  }

  velocity(): { vx: number; vy: number } {
    if (this.samples.length < 2) return { vx: 0, vy: 0 };
    const first = this.samples[0];
    const last = this.samples[this.samples.length - 1];
    const dt = last.t - first.t;
    if (dt <= 0) return { vx: 0, vy: 0 };
    return { vx: (last.x - first.x) / dt, vy: (last.y - first.y) / dt };
  }
}
