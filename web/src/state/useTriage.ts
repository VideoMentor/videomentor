// Deck controller: local deck state, fetching and prefetching, optimistic
// decisions through the queue, groups, the undo history, and the toast.
import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { ApiError, AuthError, api, groupDecisionId, isNetworkError } from '../lib/api';
import { UNDO_LIMIT, conflictMessage, pushCapped, removeEntry, trimHistory, undoneMessage } from '../lib/undoHistory';
import { deckReducer, excludeIds, reviveDecks, type DeckState, type RoundAction } from '../lib/deck';
import { offlineStore } from '../lib/offlineStore';
import { removeFromPack, takeFromPack } from '../lib/packDeck';
import type { PackDecks } from '../lib/offlinePack';

/** Take a round from the saved pack and save back what's left, so no card is dealt twice. */
async function dealFromPack(key: DeckKey, d: DeckState, source: string): Promise<Card[]> {
  const store = offlineStore();
  const saved = (await store.get('pack:decks')) as PackDecks | undefined;
  if (!saved || saved.source !== source) return [];
  const skip = new Set(excludeIds(d, queue.pendingItemIds()));
  const { round, rest } = takeFromPack(saved.decks[key] ?? [], DECK_SIZE, skip);
  if (round.length) await store.set('pack:decks', { ...saved, decks: { ...saved.decks, [key]: rest } });
  return round;
}
import { normalizeCard } from '../lib/format';
import type { Card, DeckKey, Group, GroupAction } from '../lib/types';
import { queue } from './queue';
import { readJSON, storage, writeJSON } from './storage';
import { decision as celebrateDecision } from '../kit/delight/celebrate';
import { scheduleMilestoneCheck } from './milestones';
import { useDeckOrder, useDeckSource } from './source';

const DECKS_KEY = 'vm.decks.v1';
const DECK_KEY = 'vm.deckKey';
const HISTORY_KEY = 'vm.history.v1';
const HISTORY_LIMIT = UNDO_LIMIT;
export const DECK_SIZE = 10;
const PREFETCH_AT = 3;

export type HistoryEntry =
  | { kind: 'decision'; deck: DeckKey; client_id: string; action: RoundAction; card: Card }
  | {
      kind: 'group';
      deck: DeckKey;
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
  deck: DeckKey;
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
  const [decks, dispatch] = useReducer(deckReducer, undefined, () => reviveDecks(storage.getItem(DECKS_KEY)));
  const [deck, setDeck] = useState<DeckKey>(() => (readJSON<string>(DECK_KEY, 'main') === 'music' ? 'music' : 'main'));
  const [history, setHistory] = useState<HistoryEntry[]>(() => trimHistory<HistoryEntry>(readJSON<unknown>(HISTORY_KEY, []), HISTORY_LIMIT));
  const [loading, setLoading] = useState<Record<DeckKey, boolean>>({ main: false, music: false });
  const [error, setError] = useState<Record<DeckKey, string | null>>({ main: null, music: null });
  const [toast, setToast] = useState<ToastState | null>(null);
  const [sheet, setSheet] = useState<GroupSheetState | null>(null);

  const decksRef = useRef(decks);
  decksRef.current = decks;
  const historyRef = useRef(history);
  historyRef.current = history;
  const prefetching = useRef<Record<DeckKey, boolean>>({ main: false, music: false });
  const autoTried = useRef<Record<DeckKey, boolean>>({ main: false, music: false });
  const undoBusy = useRef(false);
  const decisionsSinceCheck = useRef(0);
  const source = useDeckSource();
  const order = useDeckOrder();
  const sourceRef = useRef(source.key);
  const orderRef = useRef(order);
  const viewKey = `${source.key}|${order.sort}|${order.dir}|${order.start ?? ''}`;
  const viewRef = useRef(viewKey);

  useEffect(() => writeJSON(DECKS_KEY, decks), [decks]);
  useEffect(() => writeJSON(DECK_KEY, deck), [deck]);
  useEffect(() => writeJSON(HISTORY_KEY, history.slice(-HISTORY_LIMIT)), [history]);

  const showToast = useCallback((message: string, undo = true, undoLabel = 'Undo') => {
    setToast({ id: Date.now() + Math.random(), message, undo, undoLabel });
  }, []);
  const hideToast = useCallback(() => setToast(null), []);

  const pushHistory = (e: HistoryEntry) => setHistory((h) => pushCapped(h, e, HISTORY_LIMIT));

  const fetchDeck = useCallback(async (key: DeckKey) => {
    setLoading((l) => ({ ...l, [key]: true }));
    setError((e) => ({ ...e, [key]: null }));
    try {
      const cards = await api.deck(
        key,
        DECK_SIZE,
        excludeIds(decksRef.current[key], queue.pendingItemIds()),
        sourceRef.current,
        orderRef.current,
      );
      dispatch({ type: 'loaded', deck: key, cards: cards.map(normalizeCard) });
    } catch (err) {
      // The Mac can't be reached: deal the next round from the offline pack, if it was
      // saved for this deck source.
      if (isNetworkError(err)) {
        const round = await dealFromPack(key, decksRef.current[key], sourceRef.current);
        if (round.length) {
          dispatch({ type: 'loaded', deck: key, cards: round.map(normalizeCard) });
          return;
        }
      }
      if (!(err instanceof AuthError)) {
        setError((e) => ({ ...e, [key]: isNetworkError(err) ? 'offline' : (err as Error).message }));
      }
    } finally {
      setLoading((l) => ({ ...l, [key]: false }));
    }
  }, []);

  // A new source: drop both decks and deal from the new source.
  useEffect(() => {
    if (viewRef.current === viewKey) return;
    viewRef.current = viewKey;
    sourceRef.current = source.key;
    orderRef.current = order;
    dispatch({ type: 'reset' });
    autoTried.current = { main: false, music: false };
    prefetching.current = { main: false, music: false };
  }, [viewKey, source.key, order]);

  // First open of a deck (or an empty cached one): fetch once per session.
  const current = decks[deck];
  useEffect(() => {
    if (autoTried.current[deck] || !online) return;
    if (current.cards.length === 0 && current.decided === 0) {
      autoTried.current[deck] = true;
      void fetchDeck(deck);
    }
  }, [deck, online, current.cards.length, current.decided, fetchDeck]);

  // Prefetch the next round when 3 cards remain.
  useEffect(() => {
    const d = current;
    if (!online || prefetching.current[deck] || d.next !== null) return;
    if (d.cards.length === 0 || d.cards.length > PREFETCH_AT) return;
    prefetching.current[deck] = true;
    api
      .deck(deck, DECK_SIZE, excludeIds(d, queue.pendingItemIds()), sourceRef.current, orderRef.current)
      .then((cards) => dispatch({ type: 'prefetched', deck, cards: cards.map(normalizeCard) }))
      .catch(() => {
        // Not fatal: "Next 10" fetches again.
      })
      .finally(() => {
        prefetching.current[deck] = false;
      });
  }, [deck, online, current]);

  const decide = useCallback(
    (card: Card, action: RoundAction) => {
      const d = queue.enqueue(card.id, action);
      void removeFromPack(offlineStore(), card.id); // never dealt again offline
      dispatch({ type: 'removed', deck, ids: [card.id], action });
      pushHistory({ kind: 'decision', deck, client_id: d.client_id, action, card });
      showToast(LABELS[action]);
      celebrateDecision(action, deckCenter());
      if (navigator.onLine) void queue.flush();
      decisionsSinceCheck.current += 1;
      if (decisionsSinceCheck.current % 5 === 0) scheduleMilestoneCheck();
    },
    [deck, showToast],
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
        setSheet({ deck, anchor: card, group: res.group, items, busy: false, error: null });
      } catch (err) {
        if (isNetworkError(err)) offline();
        else if (!(err instanceof AuthError)) showToast(`Couldn't group: ${(err as Error).message}`, false);
      }
    },
    [deck, showToast],
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
        dispatch({ type: 'removed', deck: s.deck, ids: cards.map((c) => c.id), action });
        pushHistory({
          kind: 'group',
          deck: s.deck,
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
    dispatch({ type: 'front', deck: s.deck, cards: s.items.filter((c) => !pending.has(c.id)) });
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
        dispatch({ type: 'restored', deck: entry.deck, cards: [entry.card], action: entry.action });
        setDeck(entry.deck);
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
      dispatch({ type: 'restored', deck: entry.deck, cards: entry.cards, action: entry.action });
      setDeck(entry.deck);
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
    const d = decksRef.current[deck];
    if (d.next && d.next.length) dispatch({ type: 'advance', deck });
    else void fetchDeck(deck);
  }, [deck, fetchDeck]);

  const refresh = useCallback(() => fetchDeck(deck), [deck, fetchDeck]);

  /** Cards in hand (both decks) and swipes waiting to send: the offline pack leaves these out. */
  const packExclude = useCallback(
    () => [
      ...new Set([
        ...excludeIds(decksRef.current.main, queue.pendingItemIds()),
        ...excludeIds(decksRef.current.music, []),
      ]),
    ],
    [],
  );

  return {
    deck,
    setDeck,
    source,
    order,
    state: current,
    loading: loading[deck],
    error: error[deck],
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
