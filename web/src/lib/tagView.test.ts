import { describe, expect, it } from 'vitest';
import { filterTags, sortTagItems, tagCount, type TagItem, type TagRow } from './tagView';

const item = (id: string, over: Partial<TagItem> = {}): TagItem => ({
  id,
  title: id,
  channel: null,
  status: 'kept',
  signal: null,
  duration_s: null,
  words: null,
  notes: 0,
  actions_open: 0,
  actions_done: 0,
  added_at: null,
  analyzed_at: null,
  ...over,
});

const ids = (list: TagItem[]) => list.map((x) => x.id);

describe('sorting a tag page', () => {
  const list = [
    item('a', { signal: 3, duration_s: 600, words: 900, notes: 4, actions_open: 1, added_at: '2026-10-01T10:00:00' }),
    item('b', { signal: null, duration_s: null, words: null, notes: 0, actions_open: 0, added_at: null }),
    item('c', { signal: 5, duration_s: 120, words: 3000, notes: 9, actions_open: 3, added_at: '2026-11-01T10:00:00' }),
    item('d', { signal: 1, duration_s: 3600, words: 200, notes: 2, actions_open: 0, added_at: '2026-09-01T10:00:00' }),
  ];

  it('sorts by signal, highest first, and flips', () => {
    expect(ids(sortTagItems(list, 'signal', 'desc'))).toEqual(['c', 'a', 'd', 'b']);
    expect(ids(sortTagItems(list, 'signal', 'asc'))).toEqual(['d', 'a', 'c', 'b']);
  });

  it('keeps missing values last in either direction', () => {
    for (const s of ['signal', 'length', 'words', 'newest'] as const) {
      expect(sortTagItems(list, s, 'desc').at(-1)?.id).toBe('b');
      expect(sortTagItems(list, s, 'asc').at(-1)?.id).toBe('b');
    }
  });

  it('sorts by length, words, notes, open actions and date added', () => {
    expect(ids(sortTagItems(list, 'length', 'desc'))).toEqual(['d', 'a', 'c', 'b']);
    expect(ids(sortTagItems(list, 'length', 'asc'))).toEqual(['c', 'a', 'd', 'b']);
    expect(ids(sortTagItems(list, 'words', 'desc'))).toEqual(['c', 'a', 'd', 'b']);
    expect(ids(sortTagItems(list, 'notes', 'desc'))).toEqual(['c', 'a', 'd', 'b']);
    expect(ids(sortTagItems(list, 'actions', 'desc'))).toEqual(['c', 'a', 'b', 'd']);
    expect(ids(sortTagItems(list, 'newest', 'desc'))).toEqual(['c', 'a', 'd', 'b']);
    expect(ids(sortTagItems(list, 'newest', 'asc'))).toEqual(['d', 'a', 'c', 'b']);
  });

  it('treats an absurd length as missing and keeps ties in their original order', () => {
    const odd = [item('x', { duration_s: 200_000 }), item('y', { duration_s: 60 }), item('z', { duration_s: 60 })];
    expect(ids(sortTagItems(odd, 'length', 'desc'))).toEqual(['y', 'z', 'x']);
    expect(ids(sortTagItems(odd, 'length', 'asc'))).toEqual(['y', 'z', 'x']);
  });

  it('does not change the list it was given', () => {
    const copy = [...list];
    sortTagItems(list, 'signal', 'asc');
    expect(list).toEqual(copy);
  });
});

describe('filtering the tag list', () => {
  const row = (tag: string, kept: number, inbox: number, archived = 0): TagRow => ({
    tag,
    total: kept + inbox + archived,
    kept,
    inbox,
    archived,
    analyzed: kept,
    avg_signal: 3,
    minutes: kept * 10,
  });
  const tags = [row('sales', 5, 1), row('hiring', 2, 4), row('pricing', 1, 0, 3), row('Sales calls', 3, 0)];

  it('counts by the chosen status', () => {
    expect(tagCount(tags[0], 'kept')).toBe(5);
    expect(tagCount(tags[0], 'inbox')).toBe(1);
    expect(tagCount(tags[2], 'all')).toBe(4);
  });

  it('shows tags with 3 or more videos by default, most first', () => {
    expect(filterTags(tags, { q: '', status: 'kept', all: false }).map((t) => t.tag)).toEqual(['sales', 'Sales calls']);
    expect(filterTags(tags, { q: '', status: 'inbox', all: false }).map((t) => t.tag)).toEqual(['hiring']);
    expect(filterTags(tags, { q: '', status: 'all', all: false }).map((t) => t.tag)).toEqual(['sales', 'hiring', 'pricing', 'Sales calls']);
  });

  it('shows every tag with at least one video when asked', () => {
    expect(filterTags(tags, { q: '', status: 'kept', all: true }).map((t) => t.tag)).toEqual(['sales', 'Sales calls', 'hiring', 'pricing']);
    expect(filterTags(tags, { q: '', status: 'inbox', all: true }).map((t) => t.tag)).toEqual(['hiring', 'sales']);
  });

  it('searches without caring about case, ignoring the 3+ filter', () => {
    expect(filterTags(tags, { q: 'SALES', status: 'kept', all: false }).map((t) => t.tag)).toEqual(['sales', 'Sales calls']);
    expect(filterTags(tags, { q: 'pric', status: 'kept', all: false }).map((t) => t.tag)).toEqual(['pricing']);
  });
});

describe('tag and next up URLs', () => {
  it('encodes the tag and defaults to kept', async () => {
    const { tagItemsUrl, nextUpUrl } = await import('./api');
    expect(tagItemsUrl('sales calls')).toBe('/api/tags/sales%20calls/items?status=kept');
    expect(tagItemsUrl('a/b', 'all')).toBe('/api/tags/a%2Fb/items?status=all');
    expect(nextUpUrl('apply')).toBe('/api/next-up?mode=apply');
    expect(nextUpUrl('watch', 'Sales & persuasion')).toBe('/api/next-up?mode=watch&skill=Sales+%26+persuasion');
  });
});

describe('a tag page row as a card', () => {
  it('fills in what the info sheet needs', async () => {
    const { tagItemCard } = await import('./tagView');
    const c = tagItemCard(item('yt:abc', { title: '', status: 'inbox', signal: 4, duration_s: 90, analyzed_at: null }));
    expect(c.video_id).toBe('abc');
    expect(c.url).toBe('https://www.youtube.com/watch?v=abc');
    expect(c.title).toBe('Untitled video');
    expect(c.status).toBe('inbox');
    expect(c.analysis_status).toBe('none');
    expect(c.tags).toEqual([]);
    expect(tagItemCard(item('yt:x', { analyzed_at: '2026-11-01' })).analysis_status).toBe('done');
  });
});
