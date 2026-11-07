// Local deck state for both decks (main and music). Pure reducer, persisted by
// the caller. A "round" is one 10-card deck; stats reset when the next round
// starts.
import type { Card, DeckKey } from './types';

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

export type DecksState = Record<DeckKey, DeckState>;

export type DeckEvent =
  | { type: 'reset' }
  | { type: 'loaded'; deck: DeckKey; cards: Card[] }
  | { type: 'prefetched'; deck: DeckKey; cards: Card[] }
  | { type: 'advance'; deck: DeckKey }
  | { type: 'removed'; deck: DeckKey; ids: string[]; action: RoundAction }
  | { type: 'restored'; deck: DeckKey; cards: Card[]; action: RoundAction }
  | { type: 'front'; deck: DeckKey; cards: Card[] };

const SHOWN_LIMIT = 200;

export function emptyDeck(): DeckState {
  return { cards: [], next: null, shown: [], decided: 0, stats: { keep: 0, archive: 0, prioritize: 0 }, loaded: false };
}

export function initialDecks(): DecksState {
  return { main: emptyDeck(), music: emptyDeck() };
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

export function deckReducer(state: DecksState, ev: DeckEvent): DecksState {
  // The deck source changed: both decks start over.
  if (ev.type === 'reset') return initialDecks();
  const d = state[ev.deck];
  let out: DeckState;
  switch (ev.type) {
    case 'loaded':
      out = freshRound(d, dedupeFront(ev.cards, []));
      break;
    case 'prefetched': {
      const current = new Set(d.cards.map((c) => c.id));
      out = { ...d, next: ev.cards.filter((c) => !current.has(c.id)) };
      break;
    }
    case 'advance':
      out = freshRound(d, d.next ?? []);
      break;
    case 'removed': {
      const ids = new Set(ev.ids);
      const n = ev.ids.length;
      out = {
        ...d,
        cards: d.cards.filter((c) => !ids.has(c.id)),
        next: d.next ? d.next.filter((c) => !ids.has(c.id)) : d.next,
        shown: remember(d.shown, ev.ids),
        decided: d.decided + n,
        stats: { ...d.stats, [ev.action]: d.stats[ev.action] + n },
      };
      break;
    }
    case 'restored': {
      const n = ev.cards.length;
      out = {
        ...d,
        cards: dedupeFront(ev.cards, d.cards),
        decided: Math.max(0, d.decided - n),
        stats: { ...d.stats, [ev.action]: Math.max(0, d.stats[ev.action] - n) },
      };
      break;
    }
    case 'front':
      out = {
        ...d,
        cards: dedupeFront(ev.cards, d.cards),
        next: d.next ? d.next.filter((c) => !ev.cards.some((x) => x.id === c.id)) : d.next,
        shown: remember(d.shown, ev.cards.map((c) => c.id)),
      };
      break;
    default:
      return state;
  }
  return { ...state, [ev.deck]: out };
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

/** Restore persisted state, tolerating old or partial shapes. */
export function reviveDecks(raw: string | null): DecksState {
  const base = initialDecks();
  if (!raw) return base;
  try {
    const parsed = JSON.parse(raw) as Partial<DecksState>;
    for (const key of ['main', 'music'] as DeckKey[]) {
      const p = parsed[key];
      if (p && Array.isArray(p.cards)) {
        base[key] = {
          ...emptyDeck(),
          ...p,
          stats: { ...emptyDeck().stats, ...(p.stats ?? {}) },
          shown: Array.isArray(p.shown) ? p.shown : [],
          next: Array.isArray(p.next) ? p.next : null,
        };
      }
    }
  } catch {
    // ignore corrupt cache
  }
  return base;
}
