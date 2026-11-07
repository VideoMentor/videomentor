// One place the app calls when something good happens. Reads the settings, then plays
// the right sound, haptic and effect. The milestone overlay is driven by `milestones`.
import { useSyncExternalStore } from 'react';
import { burst, confetti } from './effects';
import { haptic } from './haptics';
import { effective, getDelight, prefersReducedMotion } from './settings';
import { play, type SoundName } from './sound';

export type CelebrateAction = 'keep' | 'archive' | 'prioritize' | 'group' | 'undo';

const COLORS: Record<CelebrateAction, string[]> = {
  keep: ['#16a34a', '#4ade80', '#facc15'],
  prioritize: ['#d97706', '#facc15', '#fb923c'],
  group: ['#7c3aed', '#a78bfa'],
  archive: ['#9ca3af', '#d1d5db'],
  undo: ['#9ca3af'],
};

function now() {
  return effective(getDelight(), prefersReducedMotion());
}

/** A single decision. `at` is where the sparks start (the card's center). */
export function decision(action: CelebrateAction, at?: { x: number; y: number }): void {
  const e = now();
  if (e.sound) play(action as SoundName, e.volume);
  if (!getDelight().calm) haptic(action === 'prioritize' ? 'strong' : 'light');
  if (at && action !== 'archive' && action !== 'undo') burst(at.x, at.y, COLORS[action], e.effects === 'full' ? 'subtle' : 'off');
}

/** A cleared round of cards. */
export function round(): void {
  const e = now();
  if (e.sound) play('round', e.volume);
  confetti(e.effects, 0.5);
}

export interface Milestone {
  id: string;
  kind: string;
  value: number;
  label: string;
  detail?: string;
}

let queue: Milestone[] = [];
const listeners = new Set<() => void>();

/** Queue milestones to show, one at a time, in the overlay. */
export function milestones(list: Milestone[]): void {
  if (!list.length || !now().milestones) return;
  const known = new Set(queue.map((m) => m.id));
  queue = [...queue, ...list.filter((m) => !known.has(m.id))];
  listeners.forEach((fn) => fn());
}

export function nextMilestone(): Milestone | null {
  return queue[0] ?? null;
}

export function dismissMilestone(): void {
  queue = queue.slice(1);
  listeners.forEach((fn) => fn());
}

/** Played when the overlay appears (from the overlay, so timing matches the visuals). */
export function milestoneFanfare(): void {
  const e = now();
  if (e.sound) play('milestone', e.volume);
  if (!getDelight().calm) haptic('strong');
  confetti(e.effects, 1);
}

export function useMilestone(): Milestone | null {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    nextMilestone,
  );
}
