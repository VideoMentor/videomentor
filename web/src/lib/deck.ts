// Local deck state. Pure reducer, persisted by the caller. A "round" is one 10-card deck; stats reset when the next round
// starts.
import type { Card, DeckSource } from './types';

export type RoundAction = 'keep' | 'archive' | 'prioritize';

export interface RoundStats {
  keep: number;
  archive: number;
  prioritize: number;
}

export interface DeckState {
  /** Remaining cards, top first. */
  cards: Card[];
  /** Prefetched next round. null = not fetched yet; [] = server had nothing more. */
  next: Card[] | null;
  /** Ids shown recently (sent as `exclude` so the server doesn't repeat them). */
  shown: string[];
  decided: number;
  stats: RoundStats;
  /** True once a fetch for this deck has succeeded at least once. */
  loaded: boolean;
}

export type DeckEvent =
  | { type: 'reset' }
  | { type: 'loaded'; cards: Card[] }
  | { type: 'prefetched'; cards: Card[] }
  | { type: 'advance' }
  | { type: 'removed'; ids: string[]; action: RoundAction }
  | { type: 'restored'; cards: Card[]; action: RoundAction }
  | { type: 'front'; cards: Card[] };

const SHOWN_LIMIT = 200;

export function emptyDeck(): DeckState {
  return { cards: [], next: null, shown: [], decided: 0, stats: { keep: 0, archive: 0, prioritize: 0 }, loaded: false };
}

export function initialDeck(): DeckState {
  return emptyDeck();
}

function remember(shown: string[], ids: string[]): string[] {
  const merged = [...shown.filter((id) => !ids.includes(id)), ...ids];
  return merged.slice(-SHOWN_LIMIT);
}

function dedupeFront(front: Card[], rest: Card[]): Card[] {
  const ids = new Set(front.map((c) => c.id));
  const seen = new Set<string>();
  return [...front, ...rest.filter((c) => !ids.has(c.id))].filter((c) => (seen.has(c.id) ? false : (seen.add(c.id), true)));
}

function freshRound(d: DeckState, cards: Card[]): DeckState {
  return {
    ...d,
    cards,
    next: null,
    shown: remember(d.shown, cards.map((c) => c.id)),
    decided: 0,
    stats: { keep: 0, archive: 0, prioritize: 0 },
    loaded: true,
  };
}

export function deckReducer(d: DeckState, ev: DeckEvent): DeckState {
  // The deck source changed: the deck starts over.
  if (ev.type === 'reset') return initialDeck();
  switch (ev.type) {
    case 'loaded':
      return freshRound(d, dedupeFront(ev.cards, []));
    case 'prefetched': {
      const current = new Set(d.cards.map((c) => c.id));
      return { ...d, next: ev.cards.filter((c) => !current.has(c.id)) };
    }
    case 'advance':
      return freshRound(d, d.next ?? []);
    case 'removed': {
      const ids = new Set(ev.ids);
      const n = ev.ids.length;
      return {
        ...d,
        cards: d.cards.filter((c) => !ids.has(c.id)),
        next: d.next ? d.next.filter((c) => !ids.has(c.id)) : d.next,
        shown: remember(d.shown, ev.ids),
        decided: d.decided + n,
        stats: { ...d.stats, [ev.action]: d.stats[ev.action] + n },
      };
    }
    case 'restored': {
      const n = ev.cards.length;
      return {
        ...d,
        cards: dedupeFront(ev.cards, d.cards),
        decided: Math.max(0, d.decided - n),
        stats: { ...d.stats, [ev.action]: Math.max(0, d.stats[ev.action] - n) },
      };
    }
    case 'front':
      return {
        ...d,
        cards: dedupeFront(ev.cards, d.cards),
        next: d.next ? d.next.filter((c) => !ev.cards.some((x) => x.id === c.id)) : d.next,
        shown: remember(d.shown, ev.cards.map((c) => c.id)),
      };
  }
}

/** Progress for the header: "3 of 10" and a 0..1 bar. */
export function progress(d: DeckState): { position: number; total: number; fraction: number } {
  const total = d.decided + d.cards.length;
  return {
    position: Math.min(d.decided + 1, Math.max(total, 1)),
    total,
    fraction: total ? d.decided / total : 0,
  };
}

/** Ids to send as `exclude` when fetching more cards. */
export function excludeIds(d: DeckState, pendingItemIds: string[]): string[] {
  return [...new Set([...d.cards.map((c) => c.id), ...(d.next ?? []).map((c) => c.id), ...d.shown, ...pendingItemIds])];
}

/** Restore persisted state, tolerating old or partial shapes (and the old two-deck cache). */
export function reviveDeck(raw: string | null): DeckState {
  const base = emptyDeck();
  if (!raw) return base;
  try {
    const parsed = JSON.parse(raw) as Partial<DeckState> & { main?: Partial<DeckState> };
    const p = Array.isArray(parsed.cards) ? parsed : parsed.main;
    if (p && Array.isArray(p.cards)) {
      return {
        ...base,
        ...p,
        stats: { ...base.stats, ...(p.stats ?? {}) },
        shown: Array.isArray(p.shown) ? p.shown : [],
        next: Array.isArray(p.next) ? p.next : null,
      };
    }
  } catch {
    // ignore corrupt cache
  }
  return base;
}

// ---- deck sources ----------------------------------------------------------

export const ALL: DeckSource = { key: 'all', label: 'All saves' };
export const WATCH_LATER: DeckSource = { key: 'wl', label: 'Watch Later' };
export const ALL_PLAYLISTS: DeckSource = { key: 'playlists', label: 'All my playlists' };
export const NOT_FOR_LEARNING: DeckSource = { key: 'nl', label: 'Not for learning' };

/** The fixed part of the source picker. nl is the number of music and entertainment videos waiting. */
export function sourceList(nl: number | null): { source: DeckSource; text: string }[] {
  return [
    { source: ALL, text: ALL.label },
    { source: WATCH_LATER, text: WATCH_LATER.label },
    { source: ALL_PLAYLISTS, text: ALL_PLAYLISTS.label },
    { source: NOT_FOR_LEARNING, text: nl === null ? NOT_FOR_LEARNING.label : `${NOT_FOR_LEARNING.label} (${nl.toLocaleString()})` },
  ];
}
