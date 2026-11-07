import { describe, expect, it } from 'vitest';
import { groupCards, rowNote, sortCards, type LibraryCard } from './libraryView';

const c = (id: string, o: Partial<LibraryCard>): LibraryCard =>
  ({
    id,
    video_id: id,
    url: '',
    title: id,
    channel: null,
    posted_at: null,
    posted_exact: false,
    duration_s: null,
    thumbnail: null,
    added_at: null,
    why: null,
    topics: [],
    tags: [],
    category: null,
    status: 'kept',
    priority: 0,
    analysis_status: 'none',
    sources: [],
    saved_in_labels: [],
    summary_short: null,
    decided_at: null,
    ...o,
  }) as LibraryCard;

const A = c('a', { title: 'Beta', decided_at: '2026-10-30T10:00:00Z', posted_at: '2020-01-01', signal: 2, saved_at: '2026-01-01T00:00:00Z', tags: ['pricing', 'sales'], saved_in_labels: ['Biz ideas'] });
const B = c('b', { title: 'alpha', decided_at: '2026-10-31T10:00:00Z', posted_at: '2024-01-01T09:00:00+00:00', signal: 5, saved_at: null, tags: ['sales'], saved_in_labels: ['Watch Later', 'Biz ideas'] });
const C = c('c', { title: 'Gamma', decided_at: null, posted_at: null, signal: null, tags: [], saved_in_labels: [] });

describe('sortCards', () => {
  it('sorts by each key, missing values last either way', () => {
    const ids = (s: Parameters<typeof sortCards>[1], d: 'asc' | 'desc') => sortCards([A, B, C], s, d).map((x) => x.id);
    expect(ids('decided', 'desc')).toEqual(['b', 'a', 'c']);
    expect(ids('decided', 'asc')).toEqual(['a', 'b', 'c']);
    expect(ids('posted', 'asc')).toEqual(['a', 'b', 'c']);
    expect(ids('saved', 'desc')).toEqual(['a', 'b', 'c']);
    expect(ids('signal', 'desc')).toEqual(['b', 'a', 'c']);
    expect(ids('title', 'asc')).toEqual(['b', 'a', 'c']); // case-insensitive: alpha, Beta, Gamma
  });
  it('does not change the input', () => {
    const list = [A, B];
    sortCards(list, 'title', 'asc');
    expect(list.map((x) => x.id)).toEqual(['a', 'b']);
  });
});

describe('groupCards', () => {
  it('groups by playlist (where saved), a video in several lists appears in each', () => {
    const g = groupCards([A, B, C], 'playlist');
    expect(g.map((x) => [x.label, x.items.map((i) => i.id)])).toEqual([
      ['Biz ideas', ['a', 'b']],
      ['Watch Later', ['b']],
      ['Not in a list', ['c']],
    ]);
  });
  it('groups by tag, biggest first, untagged last', () => {
    const g = groupCards([A, B, C], 'tag');
    expect(g.map((x) => [x.label, x.items.length])).toEqual([
      ['sales', 2],
      ['pricing', 1],
      ['Untagged', 1],
    ]);
  });
  it('keeps the sorted order inside each group', () => {
    const g = groupCards(sortCards([A, B], 'title', 'asc'), 'tag');
    expect(g[0].items.map((i) => i.id)).toEqual(['b', 'a']);
  });
  it('none is one group', () => {
    expect(groupCards([A, B], 'none')).toEqual([{ key: 'all', label: '', items: [A, B] }]);
  });
});

describe('analyzed sort and row notes', () => {
  it('sorts by analysis time', () => {
    const x = c('x', { analyzed_at: '2026-10-31T09:00:00+00:00' });
    const y = c('y', { analyzed_at: '2026-10-31T11:00:00+00:00' });
    expect(sortCards([x, y], 'analyzed', 'desc').map((i) => i.id)).toEqual(['y', 'x']);
  });
  it('shows the sorted-by value and status when showing both', () => {
    const k = c('k', { status: 'kept', decided_at: '2026-10-30T10:00:00Z', analysis_status: 'done', signal: 4 });
    expect(rowNote(k, { sort: 'decided', status: 'kept' })).toBe('kept Oct 30, 2026 · analyzed');
    expect(rowNote(k, { sort: 'signal', status: 'processed' })).toBe('kept · signal 4/5 · analyzed');
    expect(rowNote(c('a', { status: 'archived', analyzed_at: null }), { sort: 'analyzed', status: 'kept' })).toBe('');
  });
});

describe('group order', () => {
  const X = c('x', { tags: ['b-tag', 'a-tag'] });
  const Y = c('y', { tags: ['b-tag'] });
  const Z = c('z', { tags: [] });
  it('orders groups by count either way or by name, catch-all last', () => {
    const labels = (o: Parameters<typeof groupCards>[2]) => groupCards([X, Y, Z], 'tag', o).map((g) => g.label);
    expect(labels('most')).toEqual(['b-tag', 'a-tag', 'Untagged']);
    expect(labels('fewest')).toEqual(['a-tag', 'b-tag', 'Untagged']);
    expect(labels('name')).toEqual(['a-tag', 'b-tag', 'Untagged']);
  });
});

describe('group by channel', () => {
  it('groups by channel name, unknown last', () => {
    const a = c('a', { channel: 'Lenny' });
    const b = c('b', { channel: 'Lenny' });
    const z = c('z', { channel: null });
    const d = c('d', { channel: 'Anthropic' });
    expect(groupCards([a, z, b, d], 'channel').map((g) => [g.label, g.items.length])).toEqual([
      ['Lenny', 2],
      ['Anthropic', 1],
      ['Unknown channel', 1],
    ]);
  });
  it('puts a two-channel video under both channels, keyed by id', () => {
    const v = c('v', { channel: 'Host Channel', channel_id: 'UC1', collaborators: [{ name: 'Guest Channel', channel_id: 'UC2' }] });
    const w = c('w', { channel: 'Guest Channel', channel_id: 'UC2' });
    const twin = c('t', { channel: 'Guest Channel', channel_id: 'UC9' });
    const groups = groupCards([v, w, twin], 'channel');
    expect(groups.map((g) => [g.label, g.channelId, g.items.map((x) => x.id)])).toEqual([
      ['Guest Channel', 'UC2', ['v', 'w']],
      ['Host Channel', 'UC1', ['v']],
      ['Guest Channel', 'UC9', ['t']],
    ]);
  });
});
