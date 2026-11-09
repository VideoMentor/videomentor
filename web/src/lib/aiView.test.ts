import { describe, expect, it } from 'vitest';
import { aiLine, capShown, hidesUnprepped, parseCap } from './aiView';
import type { AiStatus, StatusResponse } from './types';

describe('parseCap', () => {
  it('accepts a number from 0 to 1000 and nothing else', () => {
    expect(parseCap('7.5')).toBe(7.5);
    expect(parseCap(' 0 ')).toBe(0);
    expect(parseCap('1000')).toBe(1000);
    expect(parseCap('')).toBeNull();
    expect(parseCap('   ')).toBeNull();
    expect(parseCap('abc')).toBeNull();
    expect(parseCap('-1')).toBeNull();
    expect(parseCap('1001')).toBeNull();
  });
});

const ai = (over: Partial<AiStatus> = {}): AiStatus => ({
  backend: 'claude_code',
  choice: 'auto',
  cap_usd: 5,
  month_cost_usd: 0,
  paused: false,
  reason: null,
  ...over,
});
const status = (a?: AiStatus): StatusResponse => ({ counts: {}, last_sync: null, ai: a });

describe('aiLine', () => {
  it('names Claude Code', () => {
    expect(aiLine(status(ai()))).toBe('AI: Claude Code');
  });
  it('shows the API key spend against the cap', () => {
    expect(aiLine(status(ai({ backend: 'api', choice: 'api', month_cost_usd: 1.2 })))).toBe(
      'AI: API key · $1.20 of $5.00 this month',
    );
  });
  it('says what off means', () => {
    expect(aiLine(status(ai({ backend: 'off', choice: 'off', paused: true, reason: 'AI is off' })))).toBe(
      'AI: off · cards show without summaries or notes',
    );
  });
  it('gives the reason when a chosen backend is missing', () => {
    const a = ai({ backend: 'off', choice: 'api', paused: true, reason: 'AI is off: no API key is set' });
    expect(aiLine(status(a))).toBe('AI: off (no API key is set) · cards show without summaries or notes');
  });
  it('says when the cap is used', () => {
    const a = ai({
      backend: 'api',
      choice: 'api',
      month_cost_usd: 5.01,
      paused: true,
      reason: "AI paused: this month's $5.00 limit is used",
    });
    expect(aiLine(status(a))).toBe("AI paused: this month's $5.00 limit is used");
  });
  it('is empty when the engine sends nothing about AI', () => {
    expect(aiLine(status())).toBe('');
    expect(aiLine(null)).toBe('');
  });
});

describe('capShown', () => {
  it('shows the cap for API key and Auto only', () => {
    expect(capShown('api')).toBe(true);
    expect(capShown('auto')).toBe(true);
    expect(capShown('claude_code')).toBe(false);
    expect(capShown('off')).toBe(false);
  });
});

describe('hidesUnprepped', () => {
  it('hides the prep count while AI is off or paused', () => {
    expect(hidesUnprepped(status(ai()))).toBe(false);
    expect(hidesUnprepped(status(ai({ backend: 'off', paused: true, reason: 'AI is off' })))).toBe(true);
    expect(hidesUnprepped(status(ai({ backend: 'api', paused: true, reason: 'x' })))).toBe(true);
    expect(hidesUnprepped(status())).toBe(false);
  });
});
