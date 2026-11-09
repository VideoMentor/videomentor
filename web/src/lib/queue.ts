// Offline-first decision queue.
//
// Swipes are applied optimistically by the UI and recorded here with a
// client_id. The queue persists to storage and flushes in order through
// POST /api/decisions/batch. The server dedupes on client_id, so resending a
// batch whose response was lost is safe.
//
// Undo: a decision still waiting here is simply dropped. One the server has
// already accepted gets an "undo" op appended (POST /api/undo with its
// decision_id), which flushes in order with everything else, so undo also
// works with no signal.
import type { DecisionAction, DecisionPayload } from './types';

export interface KVStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem?(key: string): void;
}

export interface BatchResult {
  client_id?: string;
  decision_id?: string | number | null;
  error?: string | null;
}

export interface QueueTransport {
  sendBatch(decisions: DecisionPayload[]): Promise<BatchResult[]>;
  undo(decisionId: string | number): Promise<void>;
}

/** Errors carrying `permanent: true` (e.g. a 404 or 422) drop the op instead of retrying. */
export function isPermanentError(err: unknown): boolean {
  return !!err && typeof err === 'object' && (err as { permanent?: unknown }).permanent === true;
}

interface PendingDecision extends DecisionPayload {
  type: 'decision';
}

interface PendingUndo {
  type: 'undo';
  client_id: string;
  target_client_id: string;
  decision_id: string | number;
}

type Op = PendingDecision | PendingUndo;

interface SentRecord {
  decision_id: string | number;
  item_id: string;
  undone?: boolean;
}

interface Persisted {
  v: 1;
  pending: Op[];
  sent: Record<string, SentRecord>;
  sentOrder: string[];
}

export type UndoOutcome = 'dropped' | 'undone' | 'queued' | 'unknown';
export type DecisionState = 'pending' | 'in-flight' | 'sent' | 'undone' | 'unknown';

export interface FlushResult {
  sent: number;
  failed: number;
  remaining: number;
  error?: unknown;
}

export interface QueueOptions {
  storage: KVStorage;
  transport: QueueTransport;
  storageKey?: string;
  newId?: () => string;
  now?: () => Date;
  batchSize?: number;
  /** How many accepted decisions to remember for undo. */
  sentLimit?: number;
}

export class DecisionQueue {
  private pending: Op[] = [];
  private sent: Record<string, SentRecord> = {};
  private sentOrder: string[] = [];
  private inFlight = new Set<string>();
  private flushing: Promise<FlushResult> | null = null;
  private listeners = new Set<() => void>();
  private version = 0;
  private readonly key: string;
  private readonly newId: () => string;
  private readonly now: () => Date;
  private readonly batchSize: number;
  private readonly sentLimit: number;
  lastError: unknown = null;

  constructor(private opts: QueueOptions) {
    this.key = opts.storageKey ?? 'vm.queue.v1';
    this.newId = opts.newId ?? (() => crypto.randomUUID());
    this.now = opts.now ?? (() => new Date());
    this.batchSize = opts.batchSize ?? 50;
    this.sentLimit = opts.sentLimit ?? 200;
    this.load();
  }

  // ---- reading ---------------------------------------------------------

  /** Ops not yet confirmed by the server (decisions and undos). */
  get length(): number {
    return this.pending.length;
  }

  get isFlushing(): boolean {
    return this.flushing !== null;
  }

  /** Changes on every mutation; pairs with subscribe() for useSyncExternalStore. */
  getVersion(): number {
    return this.version;
  }

  /** Item ids with a decision still waiting to be sent. */
  pendingItemIds(): string[] {
    return this.pending.filter((o): o is PendingDecision => o.type === 'decision').map((o) => o.item_id);
  }

  pendingDecisions(): DecisionPayload[] {
    return this.pending.filter((o): o is PendingDecision => o.type === 'decision').map(strip);
  }

  stateOf(clientId: string): DecisionState {
    if (this.pending.some((o) => o.type === 'decision' && o.client_id === clientId)) {
      return this.inFlight.has(clientId) ? 'in-flight' : 'pending';
    }
    const rec = this.sent[clientId];
    if (!rec) return 'unknown';
    return rec.undone ? 'undone' : 'sent';
  }

  decisionIdOf(clientId: string): string | number | undefined {
    return this.sent[clientId]?.decision_id;
  }

  subscribe(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  // ---- writing ---------------------------------------------------------

  enqueue(itemId: string, action: DecisionAction): DecisionPayload {
    const op: PendingDecision = {
      type: 'decision',
      client_id: this.newId(),
      item_id: itemId,
      action,
      at: this.now().toISOString(),
    };
    this.pending.push(op);
    this.changed();
    return strip(op);
  }

  /**
   * Undo one decision by client_id.
   * - 'dropped': it was still local, nothing reached the server.
   * - 'undone':  the server accepted it and has now reverted it.
   * - 'queued':  the server has it; the undo will be sent when online.
   * - 'unknown': not a decision this queue knows (or already undone).
   */
  async undo(clientId: string): Promise<UndoOutcome> {
    const idx = this.pending.findIndex((o) => o.type === 'decision' && o.client_id === clientId);
    if (idx >= 0) {
      if (this.inFlight.has(clientId)) {
        // It's on the wire. Wait for the answer, then decide.
        await this.flushing;
        return this.undo(clientId);
      }
      this.pending.splice(idx, 1);
      this.changed();
      return 'dropped';
    }

    const rec = this.sent[clientId];
    if (!rec || rec.undone) return 'unknown';
    rec.undone = true;
    const op: PendingUndo = {
      type: 'undo',
      client_id: this.newId(),
      target_client_id: clientId,
      decision_id: rec.decision_id,
    };
    this.pending.push(op);
    this.changed();
    await this.flush();
    return this.pending.some((o) => o.client_id === op.client_id) ? 'queued' : 'undone';
  }

  /** Send everything pending, in order. Concurrent calls share one run. */
  flush(): Promise<FlushResult> {
    if (this.flushing) {
      return this.flushing.then((r) => (this.pending.length && !r.error ? this.flush() : r));
    }
    if (!this.pending.length) return Promise.resolve({ sent: 0, failed: 0, remaining: 0 });
    this.flushing = this.run().finally(() => {
      this.flushing = null;
      this.changed();
    });
    this.changed();
    return this.flushing;
  }

  // ---- internals -------------------------------------------------------

  private async run(): Promise<FlushResult> {
    let sent = 0;
    let failed = 0;
    let isolate = false; // after a batch-level permanent error, send one at a time
    try {
      while (this.pending.length) {
        const head = this.pending[0];

        if (head.type === 'undo') {
          this.inFlight.add(head.client_id);
          try {
            await this.opts.transport.undo(head.decision_id);
            sent++;
          } catch (err) {
            if (!isPermanentError(err)) throw err;
            failed++; // e.g. already undone elsewhere; nothing left to do
          } finally {
            this.inFlight.delete(head.client_id);
          }
          this.remove(head.client_id);
          continue;
        }

        const limit = isolate ? 1 : this.batchSize;
        const batch: PendingDecision[] = [];
        for (const op of this.pending) {
          if (op.type !== 'decision' || batch.length >= limit) break;
          batch.push(op);
        }
        batch.forEach((op) => this.inFlight.add(op.client_id));
        this.changed();

        let results: BatchResult[];
        try {
          results = await this.opts.transport.sendBatch(batch.map(strip));
        } catch (err) {
          batch.forEach((op) => this.inFlight.delete(op.client_id));
          if (!isPermanentError(err)) throw err;
          if (batch.length > 1) {
            isolate = true; // find the bad one without losing the good ones
            continue;
          }
          this.remove(batch[0].client_id);
          failed++;
          continue;
        }
        batch.forEach((op) => this.inFlight.delete(op.client_id));
        isolate = false;

        let progressed = false;
        batch.forEach((op, i) => {
          const r = matchResult(results, op.client_id, i);
          if (!r) return;
          if (r.decision_id !== undefined && r.decision_id !== null) {
            this.recordSent(op, r.decision_id);
            this.remove(op.client_id);
            sent++;
            progressed = true;
          } else if (r.error) {
            this.remove(op.client_id);
            failed++;
            progressed = true;
          }
        });
        if (!progressed) throw new Error('Batch response did not confirm any decision');
      }
      this.lastError = null;
      return { sent, failed, remaining: 0 };
    } catch (err) {
      this.lastError = err;
      return { sent, failed, remaining: this.pending.length, error: err };
    }
  }

  private recordSent(op: PendingDecision, decisionId: string | number): void {
    this.sent[op.client_id] = { decision_id: decisionId, item_id: op.item_id };
    this.sentOrder.push(op.client_id);
    while (this.sentOrder.length > this.sentLimit) {
      const old = this.sentOrder.shift();
      if (old) delete this.sent[old];
    }
  }

  private remove(clientId: string): void {
    this.pending = this.pending.filter((o) => o.client_id !== clientId);
    this.changed();
  }

  private changed(): void {
    this.version++;
    this.save();
    this.listeners.forEach((fn) => fn());
  }

  private load(): void {
    try {
      const raw = this.opts.storage.getItem(this.key);
      if (!raw) return;
      const data = JSON.parse(raw) as Persisted;
      if (data.v !== 1) return;
      this.pending = Array.isArray(data.pending) ? data.pending : [];
      this.sent = data.sent ?? {};
      this.sentOrder = Array.isArray(data.sentOrder) ? data.sentOrder : [];
    } catch {
      // Corrupt or unavailable storage: start empty rather than crash.
    }
  }

  private save(): void {
    const data: Persisted = { v: 1, pending: this.pending, sent: this.sent, sentOrder: this.sentOrder };
    try {
      this.opts.storage.setItem(this.key, JSON.stringify(data));
    } catch {
      // Storage full or blocked; the in-memory queue still works this session.
    }
  }
}

function strip(op: PendingDecision): DecisionPayload {
  return { client_id: op.client_id, item_id: op.item_id, action: op.action, at: op.at };
}

/** Match by client_id when the server echoes it, else by position. */
function matchResult(results: BatchResult[], clientId: string, index: number): BatchResult | undefined {
  const byId = results.find((r) => r && r.client_id === clientId);
  if (byId) return byId;
  const atIndex = results[index];
  return atIndex && !atIndex.client_id ? atIndex : undefined;
}

/** In-memory storage for tests and for browsers that block localStorage. */
export class MemoryStorage implements KVStorage {
  private map = new Map<string, string>();
  getItem(key: string): string | null {
    return this.map.has(key) ? (this.map.get(key) as string) : null;
  }
  setItem(key: string, value: string): void {
    this.map.set(key, value);
  }
  removeItem(key: string): void {
    this.map.delete(key);
  }
}
