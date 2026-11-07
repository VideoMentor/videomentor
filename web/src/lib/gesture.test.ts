import { describe, expect, it } from 'vitest';
import {
  FLICK_VELOCITY,
  SWIPE_THRESHOLD,
  VelocityTracker,
  classifySwipe,
  isTap,
  stampOpacities,
} from './gesture';

describe('classifySwipe', () => {
  it('maps each direction past the threshold to its action', () => {
    expect(classifySwipe(SWIPE_THRESHOLD + 1, 0)).toBe('keep');
    expect(classifySwipe(-(SWIPE_THRESHOLD + 1), 0)).toBe('archive');
    expect(classifySwipe(0, -(SWIPE_THRESHOLD + 1))).toBe('group');
    expect(classifySwipe(0, SWIPE_THRESHOLD + 1)).toBe('prioritize');
  });

  it('treats exactly the threshold as committed', () => {
    expect(classifySwipe(SWIPE_THRESHOLD, 0)).toBe('keep');
  });

  it('springs back under the threshold with no velocity', () => {
    expect(classifySwipe(60, 0)).toBeNull();
    expect(classifySwipe(0, -89)).toBeNull();
    expect(classifySwipe(0, 0)).toBeNull();
  });

  it('uses the dominant axis', () => {
    // Mostly right, a bit up: keep, not group.
    expect(classifySwipe(140, -100)).toBe('keep');
    // Mostly down, drifting left: prioritize, not archive.
    expect(classifySwipe(-95, 150)).toBe('prioritize');
    // A diagonal that is far on the minor axis but not dominant does nothing
    // when the major axis is short.
    expect(classifySwipe(80, 70)).toBeNull();
  });

  it('breaks exact diagonal ties toward horizontal', () => {
    expect(classifySwipe(120, 120)).toBe('keep');
    expect(classifySwipe(-120, -120)).toBe('archive');
  });

  it('commits a fast short flick', () => {
    expect(classifySwipe(40, 5, FLICK_VELOCITY + 0.1, 0)).toBe('keep');
    expect(classifySwipe(3, -45, 0, -(FLICK_VELOCITY + 0.2))).toBe('group');
  });

  it('ignores a flick that is too short or goes against the drag', () => {
    expect(classifySwipe(15, 0, 2, 0)).toBeNull();
    // Dragged right, then flicked back left on release.
    expect(classifySwipe(50, 0, -1.5, 0)).toBeNull();
    // Fast but on the minor axis.
    expect(classifySwipe(50, 10, 0, 2)).toBeNull();
  });

  it('never classifies a near-stationary pointer, even with velocity noise', () => {
    expect(classifySwipe(4, 3, 5, 5)).toBeNull();
  });
});

describe('isTap', () => {
  it('is a tap when the pointer barely moves and lifts quickly', () => {
    expect(isTap(2, 3, 120)).toBe(true);
  });
  it('is not a tap after real movement', () => {
    expect(isTap(12, 0, 100)).toBe(false);
  });
  it('is not a tap when held as long as a long press', () => {
    expect(isTap(0, 0, 600)).toBe(false);
  });
});

describe('stampOpacities', () => {
  it('fades in only the stamp for the dominant direction', () => {
    const o = stampOpacities(45, 10);
    expect(o.keep).toBeCloseTo(0.5);
    expect(o.archive).toBe(0);
    expect(o.group).toBe(0);
    expect(o.prioritize).toBe(0);
  });
  it('caps at 1', () => {
    expect(stampOpacities(0, -400).group).toBe(1);
  });
});

describe('VelocityTracker', () => {
  it('measures px/ms over the recent window', () => {
    const t = new VelocityTracker(100);
    t.add(0, 0, 0);
    t.add(10, 0, 50);
    t.add(200, -20, 300); // old samples fall out of the 100ms window
    t.add(260, -20, 360);
    const v = t.velocity();
    expect(v.vx).toBeCloseTo(1);
    expect(v.vy).toBeCloseTo(0);
  });
  it('is zero with fewer than two samples', () => {
    const t = new VelocityTracker();
    t.add(5, 5, 10);
    expect(t.velocity()).toEqual({ vx: 0, vy: 0 });
  });
});
