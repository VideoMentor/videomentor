import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushActionQueue, pendingActionUpdates, queueActionUpdate } from './actionQueue';
import { storage } from '../state/storage';

describe('action check-offs made offline', () => {
  beforeEach(() => storage.setItem('vm.actionQueue.v1', ''));

  it('merges repeat updates to the same action, latest wins', () => {
    queueActionUpdate(1, { status: 'done' });
    queueActionUpdate(2, { note: 'call Sam' });
    queueActionUpdate(1, { status: 'open', note: 'not yet' });
    expect(pendingActionUpdates().map(({ id, patch }) => ({ id, patch }))).toEqual([
      { id: 1, patch: { status: 'open', note: 'not yet' } },
      { id: 2, patch: { note: 'call Sam' } },
    ]);
  });

  it('keeps failed sends for later and reports how many went', async () => {
    queueActionUpdate(1, { status: 'done' });
    queueActionUpdate(2, { status: 'skipped' });
    const sent: number[] = [];
    const n = await flushActionQueue(async (id) => {
      if (id === 2) throw new TypeError('Failed to fetch');
      sent.push(id);
    });
    expect(n).toBe(1);
    expect(sent).toEqual([1]);
    expect(pendingActionUpdates().map(({ id, patch }) => ({ id, patch }))).toEqual([{ id: 2, patch: { status: 'skipped' } }]);
  });
});

describe('action queue under a slow connection', () => {
  beforeEach(() => storage.setItem('vm.actionQueue.v1', ''));

  it('keeps changes made while a send is still in flight', async () => {
    queueActionUpdate(1, { status: 'done' });
    let release!: () => void;
    const flushing = flushActionQueue((id) => (id === 1 ? new Promise<void>((r) => (release = r)) : Promise.resolve()));
    await Promise.resolve();
    queueActionUpdate(2, { status: 'done' }); // made during the send
    queueActionUpdate(1, { note: 'newer' }); // a newer change to the one being sent
    release();
    await flushing;
    const left = pendingActionUpdates();
    expect(left.map((p) => p.id).sort()).toEqual([1, 2]);
    expect(left.find((p) => p.id === 1)?.patch).toEqual({ status: 'done', note: 'newer' });
  });

  it('drops changes the Mac permanently rejects', async () => {
    const { ApiError } = await import('./api');
    queueActionUpdate(9, { status: 'done' });
    await flushActionQueue(async () => {
      throw new ApiError(404, 'no such action');
    });
    expect(pendingActionUpdates()).toEqual([]);
  });
});

describe('sending one action change', () => {
  beforeEach(async () => {
    storage.setItem('vm.actionQueue.v1', '');
    const { MemoryOfflineStore, setOfflineStore } = await import('./offlineStore');
    setOfflineStore(new MemoryOfflineStore());
  });

  it('sends it straight away when the Mac answers', async () => {
    const { sendActionUpdate } = await import('./actionQueue');
    const sent: number[] = [];
    expect(await sendActionUpdate(3, { status: 'done' }, async (id) => void sent.push(id))).toBe('sent');
    expect(sent).toEqual([3]);
    expect(pendingActionUpdates()).toEqual([]);
  });

  it('queues it and updates the saved lists when offline', async () => {
    const { sendActionUpdate } = await import('./actionQueue');
    const { NetworkError } = await import('./api');
    const { offlineStore } = await import('./offlineStore');
    await offlineStore().set('/api/actions?status=open', { actions: [{ id: 4, status: 'open', note: null }], counts: {} });
    const r = await sendActionUpdate(4, { status: 'skipped' }, async () => {
      throw new NetworkError();
    });
    expect(r).toBe('queued');
    expect(pendingActionUpdates().map((p) => p.id)).toEqual([4]);
    // The saved lists update in the background, so the screen never waits on IndexedDB.
    await vi.waitFor(async () => {
      const saved = (await offlineStore().get('/api/actions?status=open')) as { actions: { status: string }[] };
      expect(saved.actions[0].status).toBe('skipped');
    });
  });

  it('passes other errors on', async () => {
    const { sendActionUpdate } = await import('./actionQueue');
    const { ApiError } = await import('./api');
    await expect(
      sendActionUpdate(5, { status: 'done' }, async () => {
        throw new ApiError(404, 'gone');
      }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(pendingActionUpdates()).toEqual([]);
  });
});
