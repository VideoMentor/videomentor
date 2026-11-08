import { describe, expect, it } from 'vitest';
import { takeFromPack } from './packDeck';
import type { Card } from './types';

const cards = (n: number) => Array.from({ length: n }, (_, i) => ({ id: `yt:${i}` }) as Card);

describe('takeFromPack', () => {
  it('skips cards already decided, queued or in hand', () => {
    const { round, rest } = takeFromPack(cards(5), 3, new Set(['yt:0', 'yt:2']));
    expect(round.map((c) => c.id)).toEqual(['yt:1', 'yt:3', 'yt:4']);
    expect(rest).toEqual([]);
  });

  it('returns fewer when the pack runs low', () => {
    expect(takeFromPack(cards(2), 10, new Set()).round).toHaveLength(2);
    expect(takeFromPack([], 10, new Set()).round).toEqual([]);
  });

  it('never repeats a card across rounds', () => {
    const first = takeFromPack(cards(25), 10, new Set());
    const seen = new Set(first.round.map((c) => c.id));
    const second = takeFromPack(first.rest, 10, seen);
    expect(second.round.some((c) => seen.has(c.id))).toBe(false);
    expect(second.rest).toHaveLength(5);
  });
});

describe('removeFromPack', () => {
  it('takes a decided card out of both saved decks', async () => {
    const { removeFromPack } = await import('./packDeck');
    const { MemoryOfflineStore } = await import('./offlineStore');
    const store = new MemoryOfflineStore();
    await store.set('pack:decks', { source: 'all', decks: { main: cards(3), music: [{ id: 'yt:1' } as Card] } });
    await removeFromPack(store, 'yt:1');
    const saved = (await store.get('pack:decks')) as { decks: { main: Card[]; music: Card[] } };
    expect(saved.decks.main.map((c) => c.id)).toEqual(['yt:0', 'yt:2']);
    expect(saved.decks.music).toEqual([]);
  });
});
