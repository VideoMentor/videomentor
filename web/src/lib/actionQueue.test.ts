import { beforeEach, describe, expect, it } from 'vitest';
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
