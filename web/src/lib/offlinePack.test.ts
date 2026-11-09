import { describe, expect, it } from 'vitest';
import { itemUrl, libraryUrl } from './api';
import { MemoryOfflineStore } from './offlineStore';
import { readPackSummary, savePack, type OfflinePack } from './offlinePack';

const card = (id: string) => ({ id, title: id });
const PACK: OfflinePack = {
  generated_at: '2026-11-07T21:00:00+00:00',
  library: { kept: [card('yt:k1'), card('yt:k2')], archived: [card('yt:a1')] },
  ready: [card('yt:k2')],
  actions: { all: [{ id: 1 }], open: [{ id: 1 }], done: [], skipped: [], counts: { open: 1, done: 0, skipped: 0, done_this_week: 0 } },
  training: { modules: [{ id: 3, title: 'T' }], details: { '3': { id: 3, module: { lessons: [] } } } },
  items: { 'yt:k1': { id: 'yt:k1', analysis: { core_idea: 'x' } }, 'yt:d1': { id: 'yt:d1' } },
  decks: { main: [card('yt:d1')] },
} as unknown as OfflinePack;

describe('offline pack', () => {
  it('saves each part under the path its screen asks for', async () => {
    const store = new MemoryOfflineStore();
    await savePack(store, PACK, 'all');
    expect(await store.get(libraryUrl('', 'kept'))).toEqual({ items: PACK.library.kept });
    expect(await store.get(libraryUrl('', 'processed'))).toEqual({ items: [...PACK.library.kept, ...PACK.library.archived] });
    expect(await store.get('/api/ready')).toEqual({ items: PACK.ready });
    expect(await store.get('/api/actions?status=open')).toEqual({ actions: PACK.actions.open, counts: PACK.actions.counts });
    expect(await store.get('/api/training/3')).toEqual(PACK.training.details['3']);
    expect(await store.get(itemUrl('yt:k1'))).toEqual(PACK.items['yt:k1']);
    expect(await store.get('pack:decks')).toEqual({ source: 'all', decks: PACK.decks });
  });

  it('summarizes what is saved', async () => {
    const store = new MemoryOfflineStore();
    expect(await readPackSummary(store)).toBeNull();
    await savePack(store, PACK, 'all');
    expect(await readPackSummary(store)).toEqual({ cards: 1, items: 2, modules: 1, actions: 1, at: PACK.generated_at });
  });
});
