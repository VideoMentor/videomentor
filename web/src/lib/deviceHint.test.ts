import { describe, expect, it } from 'vitest';
import { looksLikeIpad } from './deviceHint';

describe('looksLikeIpad', () => {
  const mac = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/27.0 Safari/605.1.15';
  it('spots an iPad behind a Mac browser by its touch screen', () => {
    expect(looksLikeIpad({ userAgent: mac, maxTouchPoints: 5 })).toBe(true);
    expect(looksLikeIpad({ userAgent: mac, maxTouchPoints: 0 })).toBe(false);
    expect(looksLikeIpad({ userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 27_0)', maxTouchPoints: 5 })).toBe(false);
  });
});
