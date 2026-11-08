// The offline pack: one request that saves everything the phone needs while the Mac
// can't be reached, under the same paths the screens ask for (see offlineStore.ts).
import { api, itemUrl, libraryUrl } from './api';
import type { OfflineStore } from './offlineStore';
import { readJSON, writeJSON } from '../state/storage';
import type { ActionCounts, ActionItem, Card, ItemDetail, TrainingModule } from './types';

export interface OfflinePack {
  generated_at: string;
  library: { kept: Card[]; archived: Card[] };
  ready: Card[];
  actions: { all: ActionItem[]; open: ActionItem[]; done: ActionItem[]; skipped: ActionItem[]; counts: ActionCounts };
  training: { modules: TrainingModule[]; details: Record<string, TrainingModule> };
  items: Record<string, ItemDetail>;
  decks: { main: Card[]; music: Card[] };
}

export interface PackSummary {
  cards: number;
  items: number;
  modules: number;
  actions: number;
  at: string;
}

export type PackDecks = { source: string; decks: { main: Card[]; music: Card[] } };

export const PACK_SIZES = [50, 100, 200] as const;
const SIZE_KEY = 'vm.offlinePack.v1';
export const STALE_MS = 30 * 60 * 1000;

export function packSize(): number {
  const n = readJSON<number>(SIZE_KEY, 100);
  return (PACK_SIZES as readonly number[]).includes(n) ? n : 100;
}

export function setPackSize(n: number): void {
  writeJSON(SIZE_KEY, n);
}

export async function savePack(store: OfflineStore, p: OfflinePack, source: string): Promise<PackSummary> {
  const writes: Promise<void>[] = [
    store.set(libraryUrl('', 'kept'), { items: p.library.kept }),
    store.set(libraryUrl('', 'archived'), { items: p.library.archived }),
    store.set(libraryUrl('', 'processed'), { items: [...p.library.kept, ...p.library.archived] }),
    store.set('/api/ready', { items: p.ready }),
    store.set('/api/training', { modules: p.training.modules }),
  ];
  for (const s of ['all', 'open', 'done', 'skipped'] as const) {
    writes.push(store.set(`/api/actions?status=${s}`, { actions: p.actions[s], counts: p.actions.counts }));
  }
  for (const [id, m] of Object.entries(p.training.details)) writes.push(store.set(`/api/training/${id}`, m));
  for (const [id, d] of Object.entries(p.items)) writes.push(store.set(itemUrl(id), d));
  const decks: PackDecks = { source, decks: p.decks };
  writes.push(store.set('pack:decks', decks));
  const summary: PackSummary = {
    cards: p.decks.main.length + p.decks.music.length,
    items: Object.keys(p.items).length,
    modules: p.training.modules.length,
    actions: p.actions.all.length,
    at: p.generated_at,
  };
  writes.push(store.set('pack:meta', summary));
  await Promise.all(writes);
  return summary;
}

export async function readPackSummary(store: OfflineStore): Promise<PackSummary | null> {
  return ((await store.get('pack:meta')) as PackSummary | undefined) ?? null;
}

let refreshing: Promise<PackSummary> | null = null;

/** Fetch and save a fresh pack; one at a time. Cards already in hand or queued are left out. */
export function refreshPack(store: OfflineStore, opts: { exclude: string[]; source: string }): Promise<PackSummary> {
  return (refreshing ??= api
    .offlinePack(packSize(), opts.exclude, opts.source)
    .then((p) => savePack(store, p, opts.source))
    .finally(() => {
      refreshing = null;
    }));
}

export function isStale(summary: PackSummary | null, now = Date.now()): boolean {
  return !summary || now - Date.parse(summary.at) > STALE_MS;
}
