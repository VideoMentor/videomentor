// Sounds, effects and milestones: per-device preferences. Calm mode turns all of it off.
// Part of the reusable swipe kit: no imports from the app.
import { useSyncExternalStore } from 'react';

export type EffectsLevel = 'full' | 'subtle' | 'off';

export interface DelightSettings {
  sound: boolean;
  /** 0 to 1 */
  volume: number;
  effects: EffectsLevel;
  milestones: boolean;
  /** One switch for a quiet app: no sounds, no effects, no milestone pop-ups. */
  calm: boolean;
}

export const DEFAULT_DELIGHT: DelightSettings = { sound: true, volume: 0.6, effects: 'full', milestones: true, calm: false };

const KEY = 'kit.delight.v1';

function read(): DelightSettings {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || '{}');
    return {
      sound: typeof raw.sound === 'boolean' ? raw.sound : DEFAULT_DELIGHT.sound,
      volume: typeof raw.volume === 'number' ? Math.min(1, Math.max(0, raw.volume)) : DEFAULT_DELIGHT.volume,
      effects: ['full', 'subtle', 'off'].includes(raw.effects) ? raw.effects : DEFAULT_DELIGHT.effects,
      milestones: typeof raw.milestones === 'boolean' ? raw.milestones : DEFAULT_DELIGHT.milestones,
      calm: typeof raw.calm === 'boolean' ? raw.calm : DEFAULT_DELIGHT.calm,
    };
  } catch {
    return DEFAULT_DELIGHT;
  }
}

let current: DelightSettings = typeof localStorage === 'undefined' ? DEFAULT_DELIGHT : read();
const listeners = new Set<() => void>();

export function getDelight(): DelightSettings {
  return current;
}

export function setDelight(patch: Partial<DelightSettings>): void {
  current = { ...current, ...patch };
  try {
    localStorage.setItem(KEY, JSON.stringify(current));
  } catch {
    // private mode: keep in memory
  }
  listeners.forEach((fn) => fn());
}

export function useDelight(): DelightSettings {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    () => current,
  );
}

/** What actually plays, after calm mode and the system's reduced-motion setting. */
export function effective(s: DelightSettings, reducedMotion: boolean): { sound: boolean; volume: number; effects: EffectsLevel; milestones: boolean } {
  if (s.calm) return { sound: false, volume: 0, effects: 'off', milestones: false };
  const effects: EffectsLevel = reducedMotion ? 'off' : s.effects;
  return { sound: s.sound && s.volume > 0, volume: s.volume, effects, milestones: s.milestones };
}

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}
