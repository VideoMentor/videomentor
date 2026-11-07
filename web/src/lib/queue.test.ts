import { beforeEach, describe, expect, it } from 'vitest';
import { DecisionQueue, MemoryStorage, type BatchResult, type QueueTransport } from './queue';
import { ApiError, NetworkError, toBatchResult } from './api';
import type { DecisionPayload } from './types';

/** A fake server that dedupes on client_id like the real one. */
class FakeServer implements QueueTransport {
  decisions: (DecisionPayload & { id: number; undone: boolean })[] = [];
  batches: string[][] = [];
  undoCalls: (string | number)[] = [];
  online = true;
  /** Process the batch, then drop the response (simulates a lost reply). */
  loseNextResponse = false;
  /** Reject item ids with a permanent error at the batch level. */
  rejectItems = new Set<string>();
  private nextId = 1;

  async sendBatch(decisions: DecisionPayload[]): Promise<BatchResult[]> {
    if (!this.online) throw new NetworkError();
    this.batches.push(decisions.map((d) => d.client_id));
    if (decisions.some((d) => this.rejectItems.has(d.item_id))) throw new ApiError(422, 'bad item');
    const results = decisions.map((d) => {
      let row = this.decisions.find((x) => x.client_id === d.client_id);
      if (!row) {
        row = { ...d, id: this.nextId++, undone: false };
        this.decisions.push(row);
      }
      return { client_id: d.client_id, decision_id: row.id };
    });
    if (this.loseNextResponse) {
      this.loseNextResponse = false;
      throw new NetworkError('response lost');
    }
    return results;
  }

  async undo(decisionId: string | number): Promise<void> {
    if (!this.online) throw new NetworkError();
    this.undoCalls.push(decisionId);
    const row = this.decisions.find((d) => d.id === decisionId);
    if (!row) throw new ApiError(404, 'no such decision');
    row.undone = true;
  }

  live(): string[] {
    return this.decisions.filter((d) => !d.undone).map((d) => `${d.item_id}:${d.action}`);
  }
}

let ids = 0;
const newId = () => `c${++ids}`;

function makeQueue(server: FakeServer, storage = new MemoryStorage()) {
  return new DecisionQueue({ storage, transport: server, newId, now: () => new Date('2026-10-25T12:00:00Z') });
}

beforeEach(() => {
  ids = 0;
});

describe('ordering', () => {
  it('flushes decisions in the order they were made', async () => {
    const server = new FakeServer();
    const q = makeQueue(server);
    q.enqueue('yt:a', 'keep');
    q.enqueue('yt:b', 'archive');
    q.enqueue('yt:c', 'prioritize');
    const r = await q.flush();
    expect(r).toEqual({ sent: 3, failed: 0, remaining: 0 });
    expect(server.decisions.map((d) => d.item_id)).toEqual(['yt:a', 'yt:b', 'yt:c']);
    expect(q.length).toBe(0);
  });

  it('keeps order across offline swipes and an undo of a sent one', async () => {
    const server = new FakeServer();
    const q = makeQueue(server);
    const a = q.enqueue('yt:a', 'keep');
    await q.flush();
    server.online = false;
    expect(await q.undo(a.client_id)).toBe('queued'); // undo of a sent one waits
    q.enqueue('yt:a', 'archive'); // then re-decided while still offline
    expect(q.length).toBe(2);
    server.online = true;
    await q.flush();
    // The undo must land before the new decision, or the archive would be undone.
    expect(server.undoCalls).toEqual([1]);
    expect(server.live()).toEqual(['yt:a:archive']);
  });

  it('sends in batches of the configured size, still in order', async () => {
    const server = new FakeServer();
    const q = new DecisionQueue({ storage: new MemoryStorage(), transport: server, newId, batchSize: 2 });
    ['a', 'b', 'c', 'd', 'e'].forEach((x) => q.enqueue(`yt:${x}`, 'keep'));
    await q.flush();
    expect(server.batches).toEqual([['c1', 'c2'], ['c3', 'c4'], ['c5']]);
  });

  it('survives a reload: the queue is persisted and resumes in order', async () => {
    const storage = new MemoryStorage();
    const server = new FakeServer();
    server.online = false;
    const q1 = makeQueue(server, storage);
    q1.enqueue('yt:a', 'keep');
    q1.enqueue('yt:b', 'archive');
    await q1.flush();
    expect(q1.length).toBe(2);

    server.online = true;
    const q2 = makeQueue(server, storage);
    expect(q2.length).toBe(2);
    expect(q2.pendingItemIds()).toEqual(['yt:a', 'yt:b']);
    await q2.flush();
    expect(server.live()).toEqual(['yt:a:keep', 'yt:b:archive']);
  });
});

describe('idempotent flush', () => {
  it('keeps everything queued when offline and sends it once when back', async () => {
    const server = new FakeServer();
    server.online = false;
    const q = makeQueue(server);
    q.enqueue('yt:a', 'keep');
    const r = await q.flush();
    expect(r.remaining).toBe(1);
    expect(r.error).toBeInstanceOf(NetworkError);
    server.online = true;
    await q.flush();
    await q.flush();
    expect(server.decisions).toHaveLength(1);
  });

  it('resends the same client_ids after a lost response, and the server dedupes', async () => {
    const server = new FakeServer();
    const q = makeQueue(server);
    q.enqueue('yt:a', 'keep');
    q.enqueue('yt:b', 'archive');
    server.loseNextResponse = true;
    const first = await q.flush();
    expect(first.remaining).toBe(2); // we never heard back, so they stay queued
    await q.flush();
    expect(server.batches).toEqual([
      ['c1', 'c2'],
      ['c1', 'c2'],
    ]);
    expect(server.decisions).toHaveLength(2); // not 4
    expect(q.length).toBe(0);
  });

  it('shares one run between concurrent flush calls', async () => {
    const server = new FakeServer();
    const q = makeQueue(server);
    q.enqueue('yt:a', 'keep');
    await Promise.all([q.flush(), q.flush(), q.flush()]);
    expect(server.batches).toHaveLength(1);
  });

  it('isolates a permanently rejected decision without losing the others', async () => {
    const server = new FakeServer();
    server.rejectItems.add('yt:bad');
    const q = makeQueue(server);
    q.enqueue('yt:a', 'keep');
    q.enqueue('yt:bad', 'keep');
    q.enqueue('yt:c', 'keep');
    const r = await q.flush();
    expect(r.failed).toBe(1);
    expect(r.remaining).toBe(0);
    expect(server.live()).toEqual(['yt:a:keep', 'yt:c:keep']);
  });

  it('drops a decision the batch response marks as an error', async () => {
    const transport: QueueTransport = {
      sendBatch: async (ds) => ds.map((d) => (d.item_id === 'yt:gone' ? { client_id: d.client_id, error: 'not found' } : { client_id: d.client_id, decision_id: 9 })),
      undo: async () => {},
    };
    const q = new DecisionQueue({ storage: new MemoryStorage(), transport, newId });
    q.enqueue('yt:gone', 'keep');
    q.enqueue('yt:ok', 'keep');
    const r = await q.flush();
    expect(r).toEqual({ sent: 1, failed: 1, remaining: 0 });
  });

  it('matches results by position when the server does not echo client_id', async () => {
    const transport: QueueTransport = {
      sendBatch: async (ds) => ds.map((_, i) => ({ decision_id: 100 + i })),
      undo: async () => {},
    };
    const q = new DecisionQueue({ storage: new MemoryStorage(), transport, newId });
    const a = q.enqueue('yt:a', 'keep');
    const b = q.enqueue('yt:b', 'keep');
    await q.flush();
    expect(q.decisionIdOf(a.client_id)).toBe(100);
    expect(q.decisionIdOf(b.client_id)).toBe(101);
  });
});

describe('undo', () => {
  it('drops a decision that is still queued, so the server never sees it', async () => {
    const server = new FakeServer();
    server.online = false;
    const q = makeQueue(server);
    const a = q.enqueue('yt:a', 'keep');
    const b = q.enqueue('yt:b', 'archive');
    expect(await q.undo(b.client_id)).toBe('dropped');
    expect(q.pendingItemIds()).toEqual(['yt:a']);
    server.online = true;
    await q.flush();
    expect(server.live()).toEqual(['yt:a:keep']);
    expect(server.undoCalls).toEqual([]);
    expect(q.stateOf(a.client_id)).toBe('sent');
  });

  it('calls /api/undo with the server decision_id for one already sent', async () => {
    const server = new FakeServer();
    const q = makeQueue(server);
    q.enqueue('yt:a', 'keep');
    const b = q.enqueue('yt:b', 'archive');
    await q.flush();
    expect(q.stateOf(b.client_id)).toBe('sent');
    expect(await q.undo(b.client_id)).toBe('undone');
    expect(server.undoCalls).toEqual([2]);
    expect(server.live()).toEqual(['yt:a:keep']);
    expect(q.stateOf(b.client_id)).toBe('undone');
  });

  it('does not undo the same decision twice', async () => {
    const server = new FakeServer();
    const q = makeQueue(server);
    const a = q.enqueue('yt:a', 'keep');
    await q.flush();
    await q.undo(a.client_id);
    expect(await q.undo(a.client_id)).toBe('unknown');
    expect(server.undoCalls).toEqual([1]);
  });

  it('waits for an in-flight send, then undoes it on the server', async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const server = new FakeServer();
    const slow: QueueTransport = {
      sendBatch: async (ds) => {
        await gate;
        return server.sendBatch(ds);
      },
      undo: (id) => server.undo(id),
    };
    const q = new DecisionQueue({ storage: new MemoryStorage(), transport: slow, newId });
    const a = q.enqueue('yt:a', 'keep');
    const flushing = q.flush();
    expect(q.stateOf(a.client_id)).toBe('in-flight');
    const undoing = q.undo(a.client_id);
    release();
    await flushing;
    expect(await undoing).toBe('undone');
    expect(server.live()).toEqual([]);
  });

  it('treats a permanent error from /api/undo as done', async () => {
    const server = new FakeServer();
    const q = makeQueue(server);
    const a = q.enqueue('yt:a', 'keep');
    await q.flush();
    server.decisions = []; // the server no longer knows this decision
    expect(await q.undo(a.client_id)).toBe('undone');
    expect(q.length).toBe(0);
  });

  it('returns unknown for a client_id it never saw', async () => {
    const q = makeQueue(new FakeServer());
    expect(await q.undo('nope')).toBe('unknown');
  });
});

describe('toBatchResult', () => {
  it('reads decision_id or id, and error flags', () => {
    expect(toBatchResult({ client_id: 'x', decision_id: 3 })).toEqual({ client_id: 'x', decision_id: 3, error: null });
    expect(toBatchResult({ id: 4 })).toEqual({ client_id: undefined, decision_id: 4, error: null });
    expect(toBatchResult({ client_id: 'y', error: 'not found' }).error).toBe('not found');
    expect(toBatchResult({ client_id: 'z', ok: false }).error).toBe('rejected');
    expect(toBatchResult(null)).toEqual({});
  });
});
