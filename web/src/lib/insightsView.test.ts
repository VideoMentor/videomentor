import { describe, expect, it } from 'vitest';
import { formatCost, formatHours, keepRateRows, percent, tokenTotal } from './insightsView';

describe('insights helpers', () => {
  it('shows a rate as a whole percent, whether it comes as a fraction or a percent', () => {
    expect(percent(0.756)).toBe('76%');
    expect(percent(1)).toBe('100%');
    expect(percent(90)).toBe('90%');
    expect(percent(null)).toBe('');
  });

  it('lines up raw and clean keep rates by signal', () => {
    const rows = keepRateRows(
      [
        { signal: 2, kept: 76, archived: 24, rate: 0.76 },
        { signal: 1, kept: 1, archived: 9, rate: 0.1 },
      ],
      [{ signal: 2, kept: 3, archived: 7, rate: 0.3 }],
    );
    expect(rows).toEqual([
      { signal: 1, raw: 0.1, rawN: 10, clean: null, cleanN: 0 },
      { signal: 2, raw: 0.76, rawN: 100, clean: 0.3, cleanN: 10 },
    ]);
  });

  it('copes with a missing clean list', () => {
    expect(keepRateRows([{ signal: 5, kept: 2, archived: 0, rate: 1 }], undefined)).toEqual([
      { signal: 5, raw: 1, rawN: 2, clean: null, cleanN: 0 },
    ]);
  });

  it('formats processing time in minutes, hours or days', () => {
    expect(formatHours(null)).toBe('No data yet');
    expect(formatHours(0.25)).toBe('15 min');
    expect(formatHours(2.34)).toBe('2.3 hours');
    expect(formatHours(1)).toBe('1 hour');
    expect(formatHours(60)).toBe('2.5 days');
  });

  it('adds up every kind of token', () => {
    expect(tokenTotal({ input_tokens: 10, output_tokens: 5, cache_read_tokens: 100, cache_creation_tokens: 1 })).toBe(116);
    expect(tokenTotal({})).toBe(0);
  });

  it('formats an API-equivalent cost', () => {
    expect(formatCost(0)).toBe('$0.00');
    expect(formatCost(12.345)).toBe('$12.35');
    expect(formatCost(0.004)).toBe('<$0.01');
    expect(formatCost(undefined)).toBe('$0.00');
  });
});
