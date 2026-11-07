import { describe, expect, it } from 'vitest';
import { deckReducer, excludeIds, initialDecks, progress, reviveDecks } from './deck';
import { deckUrl, libraryUrl } from './api';
import { momentUrl, normalizeAnalysis, parseSeconds } from './format';
import type { Card } from './types';

const card = (id: string): Card => ({
  id: `yt:${id}`,
  video_id: id,
  url: `https://www.youtube.com/watch?v=${id}`,
  title: id,
  channel: 'c',
  posted_at: null,
  posted_exact: false,
  tags: [],
  duration_s: 60,
  thumbnail: null,
  added_at: null,
  why: null,
  topics: [],
  category: 'learning',
  status: 'inbox',
  priority: 0,
  analysis_status: 'none',
  sources: [],
  summary_short: null,
});

describe('deckReducer', () => {
  it('tracks progress through a 10-card round', () => {
    let s = deckReducer(initialDecks(), { type: 'loaded', deck: 'main', cards: 'abcdefghij'.split('').map(card) });
    expect(progress(s.main)).toEqual({ position: 1, total: 10, fraction: 0 });
    s = deckReducer(s, { type: 'removed', deck: 'main', ids: ['yt:a'], action: 'keep' });
    s = deckReducer(s, { type: 'removed', deck: 'main', ids: ['yt:b'], action: 'archive' });
    expect(progress(s.main)).toEqual({ position: 3, total: 10, fraction: 0.2 });
    expect(s.main.stats).toEqual({ keep: 1, archive: 1, prioritize: 0 });
  });

  it('restores an undone card to the front and rolls back the tally', () => {
    let s = deckReducer(initialDecks(), { type: 'loaded', deck: 'main', cards: [card('a'), card('b')] });
    s = deckReducer(s, { type: 'removed', deck: 'main', ids: ['yt:a'], action: 'keep' });
    s = deckReducer(s, { type: 'restored', deck: 'main', cards: [card('a')], action: 'keep' });
    expect(s.main.cards.map((c) => c.id)).toEqual(['yt:a', 'yt:b']);
    expect(s.main.decided).toBe(0);
    expect(s.main.stats.keep).toBe(0);
  });

  it('puts a group at the front without duplicates (one by one)', () => {
    let s = deckReducer(initialDecks(), { type: 'loaded', deck: 'main', cards: [card('a'), card('b'), card('c')] });
    s = deckReducer(s, { type: 'front', deck: 'main', cards: [card('a'), card('x'), card('c')] });
    expect(s.main.cards.map((c) => c.id)).toEqual(['yt:a', 'yt:x', 'yt:c', 'yt:b']);
  });

  it('advances to the prefetched round, dropping anything decided meanwhile', () => {
    let s = deckReducer(initialDecks(), { type: 'loaded', deck: 'music', cards: [card('a')] });
    s = deckReducer(s, { type: 'prefetched', deck: 'music', cards: [card('n1'), card('n2')] });
    s = deckReducer(s, { type: 'removed', deck: 'music', ids: ['yt:a', 'yt:n1'], action: 'archive' });
    expect(s.music.cards).toHaveLength(0);
    s = deckReducer(s, { type: 'advance', deck: 'music' });
    expect(s.music.cards.map((c) => c.id)).toEqual(['yt:n2']);
    expect(s.music.decided).toBe(0);
    expect(s.main.loaded).toBe(false); // other deck untouched
  });

  it('excludes current, prefetched, shown and queued ids', () => {
    let s = deckReducer(initialDecks(), { type: 'loaded', deck: 'main', cards: [card('a'), card('b')] });
    s = deckReducer(s, { type: 'removed', deck: 'main', ids: ['yt:a'], action: 'keep' });
    expect(excludeIds(s.main, ['yt:q']).sort()).toEqual(['yt:a', 'yt:b', 'yt:q']);
  });

  it('revives a cached deck and ignores junk', () => {
    const s = deckReducer(initialDecks(), { type: 'loaded', deck: 'main', cards: [card('a')] });
    expect(reviveDecks(JSON.stringify(s)).main.cards[0].id).toBe('yt:a');
    expect(reviveDecks('{not json').main.cards).toEqual([]);
    expect(reviveDecks(null).music.loaded).toBe(false);
  });
});

describe('url helpers', () => {
  it('builds the deck URL with a deduped exclude list', () => {
    expect(deckUrl('music', 10, ['yt:a', 'yt:b', 'yt:a'])).toBe('/api/deck?deck=music&n=10&exclude=yt%3Aa%2Cyt%3Ab');
    expect(deckUrl('main', 10, [])).toBe('/api/deck?deck=main&n=10');
  });
  it('builds the library URL', () => {
    expect(libraryUrl('  mcp auth ')).toBe('/api/library?status=kept&q=mcp+auth');
    expect(libraryUrl('')).toBe('/api/library?status=kept');
  });
  it('adds t=<seconds>s to a watch URL', () => {
    expect(momentUrl('https://www.youtube.com/watch?v=abc', 252)).toBe('https://www.youtube.com/watch?v=abc&t=252s');
    expect(momentUrl('https://youtu.be/abc', 5)).toBe('https://youtu.be/abc?t=5s');
  });
});

describe('analysis rendering helpers', () => {
  it('parses moment times in several shapes', () => {
    expect(parseSeconds(252)).toBe(252);
    expect(parseSeconds('252')).toBe(252);
    expect(parseSeconds('4:12')).toBe(252);
    expect(parseSeconds('1:00:01')).toBe(3601);
    expect(Number.isNaN(parseSeconds('soon'))).toBe(true);
  });
  it('normalizes partial or stringified analysis', () => {
    const a = normalizeAnalysis(JSON.stringify({ summary: 'S', moments: [{ t: '1:05', label: 'x' }, { label: 'no time' }] }));
    expect(a?.summary).toBe('S');
    expect(a?.key_points).toEqual([]);
    expect(a?.moments).toEqual([{ seconds: 65, label: 'x' }]);
    expect(normalizeAnalysis(null)).toBeNull();
    expect(normalizeAnalysis({ key_points: ['a', 3, ''] })?.key_points).toEqual(['a']);
  });
});

describe('reset', () => {
  it('clears both decks when the source changes', () => {
    let s = deckReducer(initialDecks(), { type: 'loaded', deck: 'main', cards: [card('a')] });
    s = deckReducer(s, { type: 'loaded', deck: 'music', cards: [card('b')] });
    s = deckReducer(s, { type: 'reset' });
    expect(s.main.cards).toEqual([]);
    expect(s.music.loaded).toBe(false);
  });
});
