import { describe, expect, it } from 'vitest';
import { DEFAULT_DELIGHT, effective } from './settings';
import { SOUNDS, frequency } from './sound';

describe('delight settings', () => {
  it('calm mode turns everything off', () => {
    expect(effective({ ...DEFAULT_DELIGHT, calm: true }, false)).toEqual({ sound: false, volume: 0, effects: 'off', milestones: false });
  });
  it('reduced motion turns effects off but keeps sound and milestones', () => {
    const e = effective(DEFAULT_DELIGHT, true);
    expect(e.effects).toBe('off');
    expect(e.sound).toBe(true);
    expect(e.milestones).toBe(true);
  });
  it('zero volume means no sound', () => {
    expect(effective({ ...DEFAULT_DELIGHT, volume: 0 }, false).sound).toBe(false);
  });
});

describe('sounds', () => {
  it('tunes to A440 and keeps every sound short', () => {
    expect(frequency(0)).toBe(440);
    expect(Math.round(frequency(12))).toBe(880);
    for (const notes of Object.values(SOUNDS)) {
      const end = Math.max(...notes.map((n) => n.at + n.len));
      expect(end).toBeLessThanOrEqual(1.8);
    }
  });
});
