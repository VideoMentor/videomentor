// Touch events (card flips, YouTube opens, info opens) for tag history.
// Fire and forget: buffered in storage, sent in batches, deduped by client_id on
// the server, so a lost reply or a reload never double counts.
import type { KVStorage } from './queue';

export type TouchKind = 'flip' | 'open' | 'info';

export interface TouchEvent {
  client_id: string;
  item_id: string;
  kind: TouchKind;
  at: string;
}

export type EventTransport = (events: TouchEvent[]) => Promise<void>;

function newId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  }
}

export class EventBuffer {
  /** Oldest events are dropped beyond this; they're nice to have, not critical. */
  static readonly MAX = 500;

  private readonly storage: KVStorage;
  private readonly transport: EventTransport;
  private readonly key: string;
  private events: TouchEvent[];
  private flushing: Promise<void> | null = null;

  constructor(opts: { storage: KVStorage; transport: EventTransport; key?: string }) {
    this.storage = opts.storage;
    this.transport = opts.transport;
    this.key = opts.key ?? 'vm.events.v1';
    this.events = this.load();
  }

  get length(): number {
    return this.events.length;
  }

  track(kind: TouchKind, itemId: string): void {
    this.events.push({ client_id: newId(), item_id: itemId, kind, at: new Date().toISOString() });
    if (this.events.length > EventBuffer.MAX) this.events = this.events.slice(-EventBuffer.MAX);
    this.save();
  }

  /** Send everything buffered. Network errors keep the events for next time. */
  flush(): Promise<void> {
    if (this.flushing) return this.flushing;
    if (!this.events.length) return Promise.resolve();
    const batch = this.events.slice();
    this.flushing = this.transport(batch)
      .then(() => {
        const sent = new Set(batch.map((e) => e.client_id));
        this.events = this.events.filter((e) => !sent.has(e.client_id));
        this.save();
      })
      .catch(() => {
        // Offline or server hiccup: try again on the next flush.
      })
      .finally(() => {
        this.flushing = null;
      });
    return this.flushing;
  }

  private load(): TouchEvent[] {
    try {
      const raw = this.storage.getItem(this.key);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }

  private save(): void {
    try {
      this.storage.setItem(this.key, JSON.stringify(this.events));
    } catch {
      // storage full or blocked; keep in memory
    }
  }
}
