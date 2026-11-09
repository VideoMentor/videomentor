// Deck controller: local deck state, fetching and prefetching, optimistic
// decisions through the queue, groups, the undo history, and the toast.
import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { ApiError, AuthError, api, groupDecisionId, isNetworkError } from '../lib/api';
import { UNDO_LIMIT, conflictMessage, pushCapped, removeEntry, trimHistory, undoneMessage } from '../lib/undoHistory';
import { deckReducer, excludeIds, reviveDeck, type DeckState, type RoundAction } from '../lib/deck';
import { offlineStore } from '../lib/offlineStore';
import { removeFromPack, takeFromPack } from '../lib/packDeck';
import type { PackDecks } from '../lib/offlinePack';

/** Take a round from the saved pack and save back what's left, so no card is dealt twice. */
async function dealFromPack(d: DeckState, source: string): Promise<Card[]> {
  const store = offlineStore();
  const saved = (await store.get('pack:decks')) as PackDecks | undefined;
  if (!saved || saved.source !== source) return [];
  const skip = new Set(excludeIds(d, queue.pendingItemIds()));
  const { round, rest } = takeFromPack(saved.decks.main ?? [], DECK_SIZE, skip);
  if (round.length) await store.set('pack:decks', { ...saved, decks: { ...saved.decks, main: rest } });
  return round;
}
import { normalizeCard } from '../lib/format';
import type { Card, Group, GroupAction } from '../lib/types';
import { queue } from './queue';
import { readJSON, storage, writeJSON } from './storage';
import { decision as celebrateDecision } from '../kit/delight/celebrate';
import { scheduleMilestoneCheck } from './milestones';
import { useDeckOrder, useDeckSource } from './source';

const DECK_KEY = 'vm.decks.v1';
const HISTORY_KEY = 'vm.history.v1';
const HISTORY_LIMIT = UNDO_LIMIT;
export const DECK_SIZE = 10;
const PREFETCH_AT = 3;

export type HistoryEntry =
  | { kind: 'decision'; client_id: string; action: RoundAction; card: Card }
  | {
      kind: 'group';
      action: GroupAction;
      cards: Card[];
      label: string;
      decision_id?: string | number;
    };

export interface ToastState {
  id: number;
  message: string;
  undo: boolean;
  /** Button text; "Undo" after a decision, "Undo previous" after an undo. */
  undoLabel?: string;
}

export interface GroupSheetState {
  anchor: Card;
  group: Group;
  items: Card[];
  busy: boolean;
  error: string | null;
}

const LABELS: Record<RoundAction, string> = {
  keep: 'Kept',
  archive: 'Archived',
  prioritize: 'Kept · analyzing first',
};

/** Where swipe sparks start: the middle of the deck. */
function deckCenter(): { x: number; y: number } | undefined {
  const el = document.querySelector('.deck');
  if (!el) return undefined;
  const r = el.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height * 0.4 };
}

export function useTriage(online: boolean) {
  const [state, dispatch] = useReducer(deckReducer, undefined, () => reviveDeck(storage.getItem(DECK_KEY)));
  const [history, setHistory] = useState<HistoryEntry[]>(() => trimHistory<HistoryEntry>(readJSON<unknown>(HISTORY_KEY, []), HISTORY_LIMIT));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [sheet, setSheet] = useState<GroupSheetState | null>(null);

  const stateRef = useRef(state);
  stateRef.current = state;
  const historyRef = useRef(history);
  historyRef.current = history;
  const prefetching = useRef(false);
  const autoTried = useRef(false);
  const undoBusy = useRef(false);
  const decisionsSinceCheck = useRef(0);
  const source = useDeckSource();
  const order = useDeckOrder();
  const sourceRef = useRef(source.key);
  const orderRef = useRef(order);
  const viewKey = `${source.key}|${order.sort}|${order.dir}|${order.start ?? ''}`;
  const viewRef = useRef(viewKey);

  useEffect(() => writeJSON(DECK_KEY, state), [state]);
  useEffect(() => writeJSON(HISTORY_KEY, history.slice(-HISTORY_LIMIT)), [history]);

  const showToast = useCallback((message: string, undo = true, undoLabel = 'Undo') => {
    setToast({ id: Date.now() + Math.random(), message, undo, undoLabel });
  }, []);
  const hideToast = useCallback(() => setToast(null), []);

  const pushHistory = (e: HistoryEntry) => setHistory((h) => pushCapped(h, e, HISTORY_LIMIT));

  const fetchDeck = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const cards = await api.deck(
        DECK_SIZE,
        excludeIds(stateRef.current, queue.pendingItemIds()),
        sourceRef.current,
        orderRef.current,
      );
      dispatch({ type: 'loaded', cards: cards.map(normalizeCard) });
    } catch (err) {
      // The Mac can't be reached: deal the next round from the offline pack, if it was
      // saved for this deck source.
      if (isNetworkError(err)) {
        const round = await dealFromPack(stateRef.current, sourceRef.current);
        if (round.length) {
          dispatch({ type: 'loaded', cards: round.map(normalizeCard) });
          return;
        }
      }
      if (!(err instanceof AuthError)) setError(isNetworkError(err) ? 'offline' : (err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  // A new source: drop the deck and deal from the new source.
  useEffect(() => {
    if (viewRef.current === viewKey) return;
    viewRef.current = viewKey;
    sourceRef.current = source.key;
    orderRef.current = order;
    dispatch({ type: 'reset' });
    autoTried.current = false;
    prefetching.current = false;
  }, [viewKey, source.key, order]);

  // First open of the deck (or an empty cached one): fetch once per session.
  useEffect(() => {
    if (autoTried.current || !online) return;
    if (state.cards.length === 0 && state.decided === 0) {
      autoTried.current = true;
      void fetchDeck();
    }
  }, [online, state.cards.length, state.decided, fetchDeck]);

  // Prefetch the next round when 3 cards remain.
  useEffect(() => {
    if (!online || prefetching.current || state.next !== null) return;
    if (state.cards.length === 0 || state.cards.length > PREFETCH_AT) return;
    prefetching.current = true;
    api
      .deck(DECK_SIZE, excludeIds(state, queue.pendingItemIds()), sourceRef.current, orderRef.current)
      .then((cards) => dispatch({ type: 'prefetched', cards: cards.map(normalizeCard) }))
      .catch(() => {
        // Not fatal: "Next 10" fetches again.
      })
      .finally(() => {
        prefetching.current = false;
      });
  }, [online, state]);

  const decide = useCallback(
    (card: Card, action: RoundAction) => {
      const d = queue.enqueue(card.id, action);
      void removeFromPack(offlineStore(), card.id); // never dealt again offline
      dispatch({ type: 'removed', ids: [card.id], action });
      pushHistory({ kind: 'decision', client_id: d.client_id, action, card });
      showToast(LABELS[action]);
      celebrateDecision(action, deckCenter());
      if (navigator.onLine) void queue.flush();
      decisionsSinceCheck.current += 1;
      if (decisionsSinceCheck.current % 5 === 0) scheduleMilestoneCheck();
    },
    [showToast],
  );

  const requestGroup = useCallback(
    async (card: Card) => {
      const offline = () => showToast('Grouping needs a connection', false);
      if (!navigator.onLine) return offline();
      await queue.flush(); // so the server sees earlier swipes first
      try {
        const res = await api.createGroup(card.id);
        let items = (res.items ?? []).map(normalizeCard);
        // Anchor first, even if the server forgot it.
        items = [card, ...items.filter((c) => c.id !== card.id)];
        celebrateDecision('group');
        setSheet({ anchor: card, group: res.group, items, busy: false, error: null });
      } catch (err) {
        if (isNetworkError(err)) offline();
        else if (!(err instanceof AuthError)) showToast(`Couldn't group: ${(err as Error).message}`, false);
      }
    },
    [showToast],
  );

  const groupDecide = useCallback(
    async (action: GroupAction) => {
      const s = sheet;
      if (!s || s.busy) return;
      setSheet({ ...s, busy: true, error: null });
      try {
        const res = await api.decideGroup(s.group.id, crypto.randomUUID(), action);
        const pending = new Set(queue.pendingItemIds());
        const cards = s.items.filter((c) => !pending.has(c.id));
        dispatch({ type: 'removed', ids: cards.map((c) => c.id), action });
        pushHistory({
          kind: 'group',
          action,
          cards,
          label: s.group.label,
          decision_id: groupDecisionId(res),
        });
        celebrateDecision(action, deckCenter());
        scheduleMilestoneCheck();
        setSheet(null);
        showToast(`${action === 'keep' ? 'Kept' : 'Archived'} ${cards.length}`);
      } catch (err) {
        const msg = isNetworkError(err) ? 'This needs a connection. Try again when you have signal.' : (err as Error).message;
        setSheet({ ...s, busy: false, error: msg });
      }
    },
    [sheet, showToast],
  );

  const groupOneByOne = useCallback(() => {
    const s = sheet;
    if (!s) return;
    const pending = new Set(queue.pendingItemIds());
    dispatch({ type: 'front', cards: s.items.filter((c) => !pending.has(c.id)) });
    setSheet(null);
  }, [sheet]);

  const closeSheet = useCallback(() => setSheet(null), []);

  const undo = useCallback(async () => {
    const entry = historyRef.current[historyRef.current.length - 1];
    if (!entry || undoBusy.current) return;
    undoBusy.current = true;
    // While this undo runs, the toast's button would do nothing: hide it.
    setToast((t) => (t ? { ...t, undo: false } : t));
    // Remove by identity, so a swipe made while we wait for the server is kept.
    const drop = () => {
      historyRef.current = removeEntry(historyRef.current, entry);
      setHistory((h) => removeEntry(h, entry));
      return historyRef.current.length;
    };
    const say = (m: { message: string; undoLabel?: string }, suffix = '') =>
      showToast(m.message + suffix, !!m.undoLabel, m.undoLabel);
    try {
      if (entry.kind === 'decision') {
        const remaining = drop();
        dispatch({ type: 'restored', cards: [entry.card], action: entry.action });
        celebrateDecision('undo');
        const outcome = await queue.undo(entry.client_id);
        const suffix =
          outcome === 'queued' ? ' (syncs when you’re back online)' : outcome === 'unknown' ? ' (here only; the server had no record)' : '';
        say(undoneMessage(entry, remaining), suffix);
        return;
      }
      if (entry.decision_id === undefined) {
        // Without the server's id, /api/undo would undo whatever decision is newest.
        const remaining = drop();
        say(conflictMessage(entry, remaining));
        return;
      }
      if (!navigator.onLine) {
        showToast('Undoing a group needs a connection', true, 'Try again');
        return;
      }
      await api.undo(entry.decision_id);
      const remaining = drop();
      dispatch({ type: 'restored', cards: entry.cards, action: entry.action });
      celebrateDecision('undo');
      say(undoneMessage(entry, remaining));
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Decided again since (Library, another device): skip it so older steps stay reachable.
        say(conflictMessage(entry, drop()));
      } else if (!(err instanceof AuthError)) {
        showToast(isNetworkError(err) ? 'Undo needs a connection' : `Undo failed: ${(err as Error).message}`, true, 'Try again');
      }
    } finally {
      undoBusy.current = false;
    }
  }, [showToast]);

  const nextRound = useCallback(() => {
    const d = stateRef.current;
    if (d.next && d.next.length) dispatch({ type: 'advance' });
    else void fetchDeck();
  }, [fetchDeck]);

  const refresh = useCallback(() => fetchDeck(), [fetchDeck]);

  /** Cards in hand and swipes waiting to send: the offline pack leaves these out. */
  const packExclude = useCallback(() => excludeIds(stateRef.current, queue.pendingItemIds()), []);

  return {
    source,
    order,
    state,
    loading,
    error,
    canUndo: history.length > 0,
    undoCount: history.length,
    toast,
    showToast,
    hideToast,
    sheet,
    decide,
    requestGroup,
    groupDecide,
    groupOneByOne,
    closeSheet,
    undo,
    nextRound,
    refresh,
    packExclude,
  };
}

export type Triage = ReturnType<typeof useTriage>;
