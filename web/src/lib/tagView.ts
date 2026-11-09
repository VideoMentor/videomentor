// The Tags screen's filter and the Tag page's sorts. Pure, so they're tested without a browser.
import { normalizeCard } from './format';
import type { Card, TagItem, TagItemStatus, TagRow } from './types';

export type { TagItem, TagRow } from './types';

export type TagSort = 'signal' | 'length' | 'words' | 'notes' | 'actions' | 'newest';

export const TAG_SORTS: TagSort[] = ['signal', 'length', 'words', 'notes', 'actions', 'newest'];

export const TAG_SORT_LABELS: Record<TagSort, string> = {
  signal: 'Signal',
  length: 'Length',
  words: 'Words',
  notes: 'Notes',
  actions: 'Open actions',
  newest: 'Date added',
};

/** What the direction button says for [descending, ascending]. */
export const TAG_DIR_WORDS: Record<TagSort, [string, string]> = {
  signal: ['Highest', 'Lowest'],
  length: ['Longest', 'Shortest'],
  words: ['Most', 'Fewest'],
  notes: ['Most', 'Fewest'],
  actions: ['Most', 'Fewest'],
  newest: ['Newest', 'Oldest'],
};

const DAY_S = 24 * 3600;

function key(x: TagItem, s: TagSort): number | string | null {
  switch (s) {
    case 'signal':
      return x.signal ?? null;
    case 'length':
      return x.duration_s && x.duration_s > 0 && x.duration_s <= DAY_S ? x.duration_s : null;
    case 'words':
      return x.words ?? null;
    case 'notes':
      return x.notes ?? 0;
    case 'actions':
      return x.actions_open ?? 0;
    case 'newest':
      return x.added_at ? x.added_at.slice(0, 19) : null;
  }
}

/** A sorted copy. Missing values (no signal, no transcript) always go last; ties keep their order. */
export function sortTagItems<T extends TagItem>(items: T[], s: TagSort, dir: 'asc' | 'desc'): T[] {
  const sign = dir === 'asc' ? 1 : -1;
  return items
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

/** How many of a tag's videos have the chosen status. */
export function tagCount(t: TagRow, status: TagItemStatus): number {
  if (status === 'all') return t.total ?? 0;
  return t[status] ?? 0;
}

export const MIN_VIDEOS = 3;

/** Tags to list: a search matches any tag with a video of that status; otherwise only tags
 *  with 3+ (or, with `all`, 1+). Most videos first, then A to Z. */
export function filterTags(tags: TagRow[], opts: { q: string; status: TagItemStatus; all: boolean }): TagRow[] {
  const q = opts.q.trim().toLocaleLowerCase();
  const min = q || opts.all ? 1 : MIN_VIDEOS;
  return tags
    .filter((t) => tagCount(t, opts.status) >= min && (!q || t.tag.toLocaleLowerCase().includes(q)))
    .map((t, i) => ({ t, i }))
    .sort((a, b) => tagCount(b.t, opts.status) - tagCount(a.t, opts.status) || a.i - b.i)
    .map((x) => x.t);
}

/** The smallest Card the info sheet and detail view can open (they load the rest). */
export function cardFromId(id: string, title: string, extra: Partial<Card> = {}): Card {
  const videoId = id.startsWith('yt:') ? id.slice(3) : id;
  return normalizeCard({
    id,
    video_id: videoId,
    url: `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`,
    title,
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
    summary_short: null,
    ...extra,
  });
}

/** A tag page row as a Card, so the existing info sheet and detail view can open it. */
export function tagItemCard(x: TagItem): Card {
  return cardFromId(x.id, x.title, {
    channel: x.channel,
    duration_s: x.duration_s && x.duration_s <= DAY_S ? x.duration_s : null,
    added_at: x.added_at,
    status: x.status,
    analysis_status: x.analyzed_at ? 'done' : 'none',
    signal: x.signal,
  });
}

/** A row's small line: the numbers the page sorts by. */
export function tagItemNote(x: TagItem, showStatus: boolean): string {
  const n = (v: number, one: string, many = `${one}s`) => `${v.toLocaleString()} ${v === 1 ? one : many}`;
  return [
    showStatus ? (x.status === 'inbox' ? 'in the deck' : x.status) : '',
    x.signal ? `signal ${x.signal}/5` : '',
    x.words ? n(x.words, 'word') : '',
    x.notes ? n(x.notes, 'note') : '',
    x.actions_open ? `${n(x.actions_open, 'open action')}` : '',
  ]
    .filter(Boolean)
    .join(' · ');
}
