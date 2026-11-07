// Which saves the deck draws from: everything, Watch Later, all chosen playlists,
// or one playlist. Remembered on this device.
import { useSyncExternalStore } from 'react';
import type { DeckOrder, DeckSource } from '../lib/types';
import { readJSON, writeJSON } from './storage';

const KEY = 'vm.source.v1';
export const ALL: DeckSource = { key: 'all', label: 'All saves' };
export const WATCH_LATER: DeckSource = { key: 'wl', label: 'Watch Later' };
export const ALL_PLAYLISTS: DeckSource = { key: 'playlists', label: 'All my playlists' };

function valid(s: unknown): s is DeckSource {
  if (!s || typeof s !== 'object') return false;
  const o = s as DeckSource;
  return typeof o.key === 'string' && typeof o.label === 'string' && /^(all|wl|playlists|pl:.+|ch:.+)$/.test(o.key);
}

let current: DeckSource = (() => {
  const saved = readJSON<unknown>(KEY, ALL);
  return valid(saved) ? saved : ALL;
})();
const listeners = new Set<() => void>();

export function getSource(): DeckSource {
  return current;
}

export function setSource(next: DeckSource): void {
  if (next.key === current.key && next.label === current.label) return;
  current = next;
  writeJSON(KEY, next);
  listeners.forEach((fn) => fn());
}

export function playlistSource(id: string, title: string | null): DeckSource {
  return { key: `pl:${id}`, label: title || 'Playlist' };
}

export function useDeckSource(): DeckSource {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    () => current,
  );
}

// ---- order: default, or by posted / saved date, optionally from a start day ----

const ORDER_KEY = 'vm.order.v1';
export const DEFAULT_ORDER: DeckOrder = { sort: 'default', dir: 'desc', start: null };

function validOrder(o: unknown): o is DeckOrder {
  if (!o || typeof o !== 'object') return false;
  const x = o as DeckOrder;
  return (
    ['default', 'posted', 'saved'].includes(x.sort) &&
    ['asc', 'desc'].includes(x.dir) &&
    (x.start === null || /^\d{4}-\d{2}-\d{2}$/.test(String(x.start)))
  );
}

let order: DeckOrder = (() => {
  const saved = readJSON<unknown>(ORDER_KEY, DEFAULT_ORDER);
  return validOrder(saved) ? saved : DEFAULT_ORDER;
})();

export function setOrder(next: DeckOrder): void {
  const clean: DeckOrder = next.sort === 'default' ? DEFAULT_ORDER : next;
  if (JSON.stringify(clean) === JSON.stringify(order)) return;
  order = clean;
  writeJSON(ORDER_KEY, clean);
  listeners.forEach((fn) => fn());
}

export function useDeckOrder(): DeckOrder {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    () => order,
  );
}

/** "posted, oldest first from Mar 4, 2024" or '' for the default order. */
export function orderLabel(o: DeckOrder, formatDay: (d: string) => string): string {
  if (o.sort === 'default') return '';
  if (o.start) return `${o.sort}, ${o.dir === 'asc' ? 'forward' : 'back'} from ${formatDay(o.start)}`;
  return `${o.sort}, ${o.dir === 'asc' ? 'oldest' : 'newest'} first`;
}
