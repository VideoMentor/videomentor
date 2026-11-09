// Not for learning: the card text and the remembered batch that Undo reverses.
import type { KVStorage } from './queue';
import type { NotForLearning } from './types';

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
    store.setItem(LAST_BATCH_KEY, '');
  } catch {
    // nothing to clear
  }
}
