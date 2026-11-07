import { describe, expect, it } from 'vitest';
import { UNDO_LIMIT, conflictMessage, describeStep, pushCapped, removeEntry, trimHistory, undoneMessage } from './undoHistory';

describe('undo history', () => {
  it('keeps exactly the last 20 steps, two decks of 10', () => {
    let h: number[] = [];
    for (let i = 1; i <= 27; i++) h = pushCapped(h, i);
    expect(UNDO_LIMIT).toBe(20);
    expect(h).toHaveLength(20);
    expect(h[0]).toBe(8);
    expect(h[19]).toBe(27);
  });
  it('trims a saved history from an older version that kept 30', () => {
    const saved = Array.from({ length: 30 }, (_, i) => ({ kind: 'decision', action: 'keep', card: { title: `v${i}` } }));
    expect(trimHistory(saved)).toEqual(saved.slice(10));
    expect(trimHistory('junk')).toEqual([]);
  });
  it('describes single decisions and groups', () => {
    expect(describeStep({ kind: 'decision', action: 'keep', card: { title: 'Claude Code best practices' } })).toBe('Kept “Claude Code best practices”');
    expect(describeStep({ kind: 'decision', action: 'prioritize', card: { title: 'x' } })).toBe('Kept, analyze first “x”');
    expect(describeStep({ kind: 'group', action: 'archive', cards: [1, 2, 3], label: 'pricing' })).toBe('Archived 3 in “pricing”');
    const long = describeStep({ kind: 'decision', action: 'archive', card: { title: 'A'.repeat(80) } });
    expect(long.length).toBeLessThan(62);
    expect(long.endsWith('…”')).toBe(true);
  });
  it('offers "Undo previous" only while older steps remain', () => {
    const step = { kind: 'decision' as const, action: 'keep', card: { title: 'T' } };
    expect(undoneMessage(step, 3)).toEqual({ message: 'Undid: Kept “T”', undoLabel: 'Undo previous' });
    expect(undoneMessage(step, 0)).toEqual({ message: 'Undid: Kept “T”', undoLabel: undefined });
  });
});

describe('undo history edge cases', () => {
  it('removes an entry by identity, keeping a newer swipe made while waiting', () => {
    const group = { kind: 'group', action: 'keep', cards: [1], label: 'g' };
    const newer = { kind: 'decision', action: 'keep', card: { title: 'new' } };
    expect(removeEntry<object>([group, newer], group)).toEqual([newer]);
    expect(removeEntry<object>([newer], group)).toEqual([newer]);
  });
  it('keeps only well-formed steps when loading', () => {
    const ok = { kind: 'decision', action: 'keep', card: { title: 'x' }, client_id: 'c' };
    const grp = { kind: 'group', action: 'archive', cards: [], label: 'l' };
    expect(trimHistory([null, 5, { kind: 'decision' }, ok, { kind: 'group' }, grp])).toEqual([ok, grp]);
    expect(trimHistory([])).toEqual([]);
    expect(trimHistory(undefined)).toEqual([]);
  });
  it('keeps exactly 20 at the boundary and honors a custom limit', () => {
    const twenty = Array.from({ length: 20 }, (_, i) => i);
    expect(pushCapped(twenty.slice(0, 19), 19)).toHaveLength(20);
    expect(pushCapped(twenty, 20)[0]).toBe(1);
    expect(pushCapped([1, 2], 3, 2)).toEqual([2, 3]);
  });
  it('describes odd steps sensibly', () => {
    expect(describeStep({ kind: 'decision', action: 'snooze', card: { title: 'x' } })).toBe('snooze “x”');
    expect(describeStep({ kind: 'decision', action: 'keep', card: { title: '   ' } })).toBe('Kept “Untitled video”');
    expect(describeStep({ kind: 'group', action: 'keep' })).toBe('Kept 0 in “group”');
    expect(describeStep({ kind: 'group', action: 'keep', cards: [], label: 'L'.repeat(40) })).toMatch(/“L{31}…”$/);
  });
  it('explains a step that changed since and still offers older steps', () => {
    const step = { kind: 'group' as const, action: 'keep', cards: [1, 2], label: 'pricing' };
    expect(conflictMessage(step, 2)).toEqual({ message: 'Can’t undo Kept 2 in “pricing”: it changed since', undoLabel: 'Undo previous' });
    expect(conflictMessage(step, 0).undoLabel).toBeUndefined();
  });
});
