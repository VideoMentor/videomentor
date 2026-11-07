import { describe, expect, it } from 'vitest';
import { filterPlaylists, sortPlaylists } from './playlistView';
import type { Playlist } from './types';

const p = (id: string, o: Partial<Playlist>): Playlist =>
  ({
    id,
    title: id,
    owner: 'Me',
    visibility: null,
    video_count: null,
    modified_date: null,
    created_at: null,
    enabled: false,
    error: null,
    synced: 0,
    newest_save: null,
    dates_known: false,
    inbox: 0,
    kept: 0,
    archived: 0,
    items_synced_at: null,
    feed_order: null,
    ...o,
  }) as Playlist;

const A = p('a', { title: 'beta', video_count: 78, modified_date: '20261030', created_at: '2021-03-04T00:00:00Z', feed_order: 2, inbox: 5, enabled: true });
const B = p('b', { title: 'Alpha', video_count: 2, modified_date: '20240101', created_at: null, feed_order: 1, owner: 'Someone' });
const C = p('c', { title: 'gamma', video_count: null, feed_order: 3, newest_save: '2026-10-31T00:00:00Z', enabled: true, inbox: 9 });

describe('sortPlaylists', () => {
  const ids = (k: Parameters<typeof sortPlaylists>[1], d: 'asc' | 'desc') => sortPlaylists([A, B, C], k, d).map((x) => x.id);
  it('sorts by each key with missing values last', () => {
    expect(ids('order', 'asc')).toEqual(['b', 'a', 'c']);
    expect(ids('title', 'asc')).toEqual(['b', 'a', 'c']);
    expect(ids('videos', 'desc')).toEqual(['a', 'b', 'c']);
    expect(ids('videos', 'asc')).toEqual(['b', 'a', 'c']);
    expect(ids('updated', 'desc')).toEqual(['a', 'b', 'c']);
    expect(ids('created', 'asc')).toEqual(['a', 'b', 'c']);
    expect(ids('newest', 'desc')).toEqual(['c', 'a', 'b']);
    expect(ids('triage', 'desc')).toEqual(['c', 'a', 'b']);
  });
});

describe('filterPlaylists', () => {
  it('filters by on, owner and search text', () => {
    const ids = (f: Parameters<typeof filterPlaylists>[1]) => filterPlaylists([A, B, C], f).map((x) => x.id);
    expect(ids({ show: 'all', owner: 'anyone', q: '' })).toEqual(['a', 'b', 'c']);
    expect(ids({ show: 'on', owner: 'anyone', q: '' })).toEqual(['a', 'c']);
    expect(ids({ show: 'all', owner: 'mine', q: '', me: 'Me' })).toEqual(['a', 'c']);
    expect(ids({ show: 'all', owner: 'others', q: '', me: 'Me' })).toEqual(['b']);
    expect(ids({ show: 'all', owner: 'anyone', q: 'AL' })).toEqual(['b']);
  });
});
