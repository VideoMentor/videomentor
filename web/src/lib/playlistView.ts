// Sorting and filtering for the Playlists screen. Pure, tested without a browser.
import type { Playlist } from './types';

export type PlaylistSort = 'order' | 'title' | 'videos' | 'updated' | 'created' | 'newest' | 'triage';
export type PlaylistShow = 'all' | 'on';
export type PlaylistOwner = 'anyone' | 'mine' | 'others';

export const PLAYLIST_SORT_LABELS: Record<PlaylistSort, string> = {
  order: 'YouTube order',
  title: 'Title',
  videos: 'Number of videos',
  updated: 'Last updated',
  created: 'Created',
  newest: 'Newest save',
  triage: 'To triage',
};

/** Words for the direction button: [descending, ascending]. */
export const PLAYLIST_DIR_WORDS: Record<PlaylistSort, [string, string]> = {
  order: ['Last first', 'First first'],
  title: ['Z to A', 'A to Z'],
  videos: ['Most', 'Fewest'],
  updated: ['Newest', 'Oldest'],
  created: ['Newest', 'Oldest'],
  newest: ['Newest', 'Oldest'],
  triage: ['Most', 'Fewest'],
};

function key(p: Playlist, s: PlaylistSort): string | number | null {
  switch (s) {
    case 'order':
      return p.feed_order ?? null;
    case 'title':
      return (p.title || '').toLocaleLowerCase();
    case 'videos':
      return p.video_count ?? null;
    case 'updated':
      return p.modified_date || null;
    case 'created':
      return p.created_at ? p.created_at.slice(0, 19) : null;
    case 'newest':
      return p.newest_save ? p.newest_save.slice(0, 19) : null;
    case 'triage':
      return p.enabled && p.synced !== undefined ? p.inbox : null;
  }
}

/** A sorted copy; missing values always last. */
export function sortPlaylists(rows: Playlist[], s: PlaylistSort, dir: 'asc' | 'desc'): Playlist[] {
  const sign = dir === 'asc' ? 1 : -1;
  return rows
    .map((p, i) => ({ p, i, k: key(p, s) }))
    .sort((x, y) => {
      if (x.k === null && y.k === null) return x.i - y.i;
      if (x.k === null) return 1;
      if (y.k === null) return -1;
      if (x.k < y.k) return -sign;
      if (x.k > y.k) return sign;
      return x.i - y.i;
    })
    .map((x) => x.p);
}

export function filterPlaylists(
  rows: Playlist[],
  f: { show: PlaylistShow; owner: PlaylistOwner; q: string; me?: string | null },
): Playlist[] {
  const q = f.q.trim().toLowerCase();
  return rows.filter(
    (p) =>
      (f.show === 'all' || p.enabled) &&
      (f.owner === 'anyone' || (f.owner === 'mine' ? p.owner === f.me : p.owner !== f.me)) &&
      (!q || (p.title ?? '').toLowerCase().includes(q)),
  );
}
