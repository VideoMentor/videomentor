// Not for learning: the card text and the remembered batch that Undo reverses.
import type { KVStorage } from './queue';
import { NOT_FOR_LEARNING } from './deck';
import type { DeckSource, NotForLearning } from './types';

export const LAST_BATCH_KEY = 'vm.nlLastBatch.v1';
export const OLDER_THAN_DAYS = 30;

export interface LastBatch {
  batch: string;
  archived: number;
}

export function nlLine(c: NotForLearning, days: number): string {
  return `${c.inbox.toLocaleString()} waiting, ${c.older.toLocaleString()} older than ${days} days`;
}

export function archiveQuestion(n: number): string {
  return `Archive ${n.toLocaleString()} ${n === 1 ? 'video' : 'videos'}? You can undo this.`;
}

export function readLastBatch(store: KVStorage): LastBatch | null {
  try {
    const raw = store.getItem(LAST_BATCH_KEY);
    const v = raw ? (JSON.parse(raw) as Partial<LastBatch>) : null;
    return v && typeof v.batch === 'string' && typeof v.archived === 'number' ? { batch: v.batch, archived: v.archived } : null;
  } catch {
    return null;
  }
}

export function saveLastBatch(store: KVStorage, b: LastBatch): void {
  try {
    store.setItem(LAST_BATCH_KEY, JSON.stringify(b));
  } catch {
    // storage blocked: Undo works until the page is reloaded
  }
}

export function clearLastBatch(store: KVStorage): void {
  try {
    if (store.removeItem) store.removeItem(LAST_BATCH_KEY);
    else store.setItem(LAST_BATCH_KEY, '');
  } catch {
    // nothing to clear
  }
}

/** "Brought back 12. 3 were decided again since and stayed as they are." */
export function broughtBackLine(undone: number, skipped: number): string {
  if (undone === 0 && skipped === 0) return 'Nothing left to bring back.';
  const back = `Brought back ${undone.toLocaleString()}.`;
  return skipped === 0 ? back : `${back} ${skipped.toLocaleString()} ${skipped === 1 ? 'was' : 'were'} decided again since and stayed as they are.`;
}

const LEGACY_DECK_KEY = 'vm.deckKey';

/** The Music deck is gone. A device that last used it starts on Not for learning; the old key is removed. */
export function consumeLegacyDeckKey(store: KVStorage): DeckSource | null {
  try {
    const raw = store.getItem(LEGACY_DECK_KEY);
    if (raw === null) return null;
    if (store.removeItem) store.removeItem(LEGACY_DECK_KEY);
    else store.setItem(LEGACY_DECK_KEY, '');
    return raw.replace(/"/g, '') === 'music' ? NOT_FOR_LEARNING : null;
  } catch {
    return null;
  }
}
