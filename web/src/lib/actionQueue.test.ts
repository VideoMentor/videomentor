import { beforeEach, describe, expect, it } from 'vitest';
import { flushActionQueue, pendingActionUpdates, queueActionUpdate } from './actionQueue';
import { storage } from '../state/storage';

describe('action check-offs made offline', () => {
  beforeEach(() => storage.setItem('vm.actionQueue.v1', ''));

  it('merges repeat updates to the same action, latest wins', () => {
    queueActionUpdate(1, { status: 'done' });
    queueActionUpdate(2, { note: 'call Sam' });
    queueActionUpdate(1, { status: 'open', note: 'not yet' });
    expect(pendingActionUpdates()).toEqual([
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
    expect(pendingActionUpdates()).toEqual([{ id: 2, patch: { status: 'skipped' } }]);
  });
});
