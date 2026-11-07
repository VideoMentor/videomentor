// Sorting and grouping for the Library (the processed list). Pure, so it's tested
// without a browser; the screen keeps the choices per device.
import { formatPosted } from './format';
import type { Card } from './types';

export interface LibraryCard extends Card {
  decided_at?: string | null;
  analyzed_at?: string | null;
}

export type LibrarySort = 'decided' | 'analyzed' | 'posted' | 'saved' | 'signal' | 'title';
export type LibraryGroup = 'none' | 'playlist' | 'tag' | 'channel';
/** How groups are ordered: by how many items they hold, or by name. */
export type GroupOrder = 'most' | 'fewest' | 'name';
export type LibraryStatus = 'kept' | 'archived' | 'processed';

export const SORT_LABELS: Record<LibrarySort, string> = {
  decided: 'Recently decided',
  analyzed: 'Recently analyzed',
  posted: 'Posted date',
  saved: 'Saved date',
  signal: 'Signal',
  title: 'Title',
};

function key(c: LibraryCard, s: LibrarySort): string | number | null {
  switch (s) {
    case 'decided':
      return c.decided_at ? c.decided_at.slice(0, 19) : null;
    case 'analyzed':
      return c.analyzed_at ? c.analyzed_at.slice(0, 19) : null;
    case 'posted':
      return c.posted_at ? c.posted_at.slice(0, 19) : null;
    case 'saved':
      return c.saved_at ? c.saved_at.slice(0, 19) : null;
    case 'signal':
      return c.signal ?? null;
    case 'title':
      return (c.title || '').toLocaleLowerCase();
  }
}

/** A sorted copy. Missing values (no save date, no signal) always go last. */
export function sortCards<T extends LibraryCard>(cards: T[], s: LibrarySort, dir: 'asc' | 'desc'): T[] {
  const sign = dir === 'asc' ? 1 : -1;
  return cards
    .map((c, i) => ({ c, i, k: key(c, s) }))
    .sort((x, y) => {
      if (x.k === null && y.k === null) return x.i - y.i;
      if (x.k === null) return 1;
      if (y.k === null) return -1;
      if (x.k < y.k) return -sign;
      if (x.k > y.k) return sign;
      return x.i - y.i;
    })
    .map((x) => x.c);
}

export interface CardGroup<T> {
  key: string;
  label: string;
  items: T[];
  /** For channel groups: the channel's id, when known. */
  channelId?: string | null;
}

/** Groups in a stable order: biggest first, the catch-all group last. Items keep their order. */
export function groupCards<T extends LibraryCard>(cards: T[], by: LibraryGroup, groupOrder: GroupOrder = 'most'): CardGroup<T>[] {
  if (by === 'none') return [{ key: 'all', label: '', items: cards }];
  const rest = by === 'tag' ? 'Untagged' : by === 'channel' ? 'Unknown channel' : 'Not in a list';
  const groups = new Map<string, CardGroup<T>>();
  const order: string[] = [];
  for (const c of cards) {
    // Channel groups: the owner plus any collaborators, so a two-channel video shows under both.
    const entries: { label: string; id: string | null }[] =
      by === 'channel'
        ? [
            ...(c.channel ? [{ label: c.channel, id: c.channel_id ?? null }] : []),
            ...(c.collaborators ?? []).map((x) => ({ label: x.name, id: x.channel_id })),
          ]
        : (by === 'tag' ? (c.tags ?? []) : (c.saved_in_labels ?? [])).map((label) => ({ label, id: null }));
    for (const { label, id } of entries.length ? entries : [{ label: rest, id: null }]) {
      // Channels group by id when known, so two channels with the same name stay apart.
      const k = id ? `id:${id}` : label.toLocaleLowerCase();
      if (!groups.has(k)) {
        groups.set(k, { key: k, label, items: [], ...(by === 'channel' ? { channelId: id } : {}) });
        order.push(k);
      }
      const g = groups.get(k)!;
      if (g.items[g.items.length - 1] !== c) g.items.push(c); // a name listed twice counts once
    }
  }
  const restKey = rest.toLocaleLowerCase();
  return order
    .map((k, i) => ({ g: groups.get(k)!, i }))
    .sort((a, b) => {
      if (a.g.key === restKey) return 1;
      if (b.g.key === restKey) return -1;
      if (groupOrder === 'name') return a.g.label.localeCompare(b.g.label, undefined, { sensitivity: 'base' }) || a.i - b.i;
      const diff = b.g.items.length - a.g.items.length;
      return (groupOrder === 'fewest' ? -diff : diff) || a.i - b.i;
    })
    .map((x) => x.g);
}

export interface ListView {
  status: LibraryStatus;
  sort: LibrarySort;
  dir: 'asc' | 'desc';
  group: LibraryGroup;
  groupOrder: GroupOrder;
  /** Sort, group and filter controls shown under the title. */
  controls: boolean;
}

/** Words for the direction button: [descending, ascending]. */
export const DIR_WORDS: Record<LibrarySort, [string, string]> = {
  decided: ['Newest', 'Oldest'],
  analyzed: ['Newest', 'Oldest'],
  posted: ['Newest', 'Oldest'],
  saved: ['Newest', 'Oldest'],
  signal: ['Highest', 'Lowest'],
  title: ['Z to A', 'A to Z'],
};

/** A row's small line: status (when showing both), the sorted-by value, analysis state. */
export function rowNote(c: LibraryCard, view: Pick<ListView, 'sort' | 'status'>, analysisNote = true): string {
  const day = (iso?: string | null) => (iso ? formatPosted(iso.slice(0, 10), false) : '');
  const value: Record<LibrarySort, string> = {
    decided: c.decided_at ? `${c.status === 'archived' ? 'archived' : 'kept'} ${day(c.decided_at)}` : '',
    analyzed: c.analyzed_at ? `analyzed ${day(c.analyzed_at)}` : '',
    posted: c.posted_at ? `posted ${day(c.posted_at)}` : '',
    saved: c.saved_at ? `saved ${day(c.saved_at)}` : '',
    signal: c.signal ? `signal ${c.signal}/5` : '',
    title: '',
  };
  const status = view.status === 'processed' && view.sort !== 'decided' ? (c.status === 'kept' ? 'kept' : 'archived') : '';
  const notes: Record<string, string> = { done: 'analyzed', queued: 'queued', running: 'analyzing', failed: 'analysis failed' };
  const analysis = analysisNote && view.sort !== 'analyzed' ? notes[c.analysis_status] : '';
  return [status, value[view.sort], analysis].filter(Boolean).join(' · ');
}
