// Small synthesized sounds (Web Audio, no files). Each is a few notes with a soft
// envelope, so they stay pleasant when heard a hundred times.
export type SoundName = 'keep' | 'archive' | 'prioritize' | 'group' | 'undo' | 'round' | 'milestone';

interface Note {
  /** Semitones from A4 (440 Hz). */
  n: number;
  /** Start, seconds after the sound begins. */
  at: number;
  /** Length in seconds. */
  len: number;
  type?: OscillatorType;
  gain?: number;
}

// Warm and soft by default: sine and triangle tones in a pentatonic-friendly set.
export const SOUNDS: Record<SoundName, Note[]> = {
  keep: [
    { n: 3, at: 0, len: 0.12, type: 'triangle' },
    { n: 10, at: 0.07, len: 0.18, type: 'triangle' },
  ],
  archive: [{ n: -5, at: 0, len: 0.1, type: 'sine', gain: 0.7 }],
  prioritize: [
    { n: 7, at: 0, len: 0.1, type: 'triangle' },
    { n: 14, at: 0.06, len: 0.1, type: 'triangle' },
    { n: 19, at: 0.12, len: 0.22, type: 'sine' },
  ],
  group: [
    { n: 0, at: 0, len: 0.14, type: 'sine' },
    { n: 5, at: 0.05, len: 0.18, type: 'sine', gain: 0.6 },
  ],
  undo: [
    { n: 7, at: 0, len: 0.08, type: 'sine', gain: 0.6 },
    { n: 2, at: 0.06, len: 0.12, type: 'sine', gain: 0.6 },
  ],
  round: [
    { n: 3, at: 0, len: 0.5, type: 'triangle' },
    { n: 7, at: 0.08, len: 0.5, type: 'triangle' },
    { n: 10, at: 0.16, len: 0.55, type: 'triangle' },
    { n: 15, at: 0.24, len: 0.7, type: 'sine' },
  ],
  milestone: [
    { n: 3, at: 0, len: 0.25, type: 'triangle' },
    { n: 7, at: 0.12, len: 0.25, type: 'triangle' },
    { n: 10, at: 0.24, len: 0.25, type: 'triangle' },
    { n: 15, at: 0.36, len: 0.3, type: 'triangle' },
    { n: 10, at: 0.6, len: 0.9, type: 'sine', gain: 0.6 },
    { n: 15, at: 0.6, len: 0.9, type: 'sine', gain: 0.6 },
    { n: 19, at: 0.6, len: 1.1, type: 'sine', gain: 0.7 },
  ],
};

export function frequency(semitones: number): number {
  return 440 * Math.pow(2, semitones / 12);
}

let ctx: AudioContext | null = null;

function context(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  if (!ctx) ctx = new Ctor();
  if (ctx.state === 'suspended') void ctx.resume();
  return ctx;
}

/** Play a sound. Must first happen inside a tap or swipe (iOS unlocks audio then). */
export function play(name: SoundName, volume: number): void {
  const ac = context();
  if (!ac || volume <= 0) return;
  const t0 = ac.currentTime + 0.01;
  const master = ac.createGain();
  master.gain.value = 0.18 * volume;
  master.connect(ac.destination);
  for (const note of SOUNDS[name]) {
    const osc = ac.createOscillator();
    const env = ac.createGain();
    osc.type = note.type ?? 'sine';
    osc.frequency.value = frequency(note.n);
    const start = t0 + note.at;
    const peak = note.gain ?? 1;
    env.gain.setValueAtTime(0, start);
    env.gain.linearRampToValueAtTime(peak, start + 0.012);
    env.gain.exponentialRampToValueAtTime(0.0001, start + note.len);
    osc.connect(env).connect(master);
    osc.start(start);
    osc.stop(start + note.len + 0.05);
  }
}
