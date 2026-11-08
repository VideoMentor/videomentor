// Saved copies of what the screens loaded, so the app keeps working when the Mac can't
// be reached. IndexedDB holds far more than localStorage (whose ~5 MB fills up fast);
// if IndexedDB isn't available (private browsing, tests), copies live in memory.

export interface OfflineStore {
  get(key: string): Promise<unknown | undefined>;
  set(key: string, value: unknown): Promise<void>;
  clear(): Promise<void>;
}

export class MemoryOfflineStore implements OfflineStore {
  private map = new Map<string, unknown>();
  async get(key: string) {
    return this.map.get(key);
  }
  async set(key: string, value: unknown) {
    this.map.set(key, value);
  }
  async clear() {
    this.map.clear();
  }
}

const DB = 'vm-offline';
const STORE = 'responses';

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export function idbOfflineStore(): OfflineStore {
  if (typeof indexedDB === 'undefined') return new MemoryOfflineStore();
  const fallback = new MemoryOfflineStore();
  let db: Promise<IDBDatabase | null> | null = null;
  const conn = () => (db ??= openDb().catch(() => null));
  const run = async <T>(mode: IDBTransactionMode, op: (s: IDBObjectStore) => IDBRequest<T>): Promise<T | undefined> => {
    const d = await conn();
    if (!d) return undefined;
    return new Promise((resolve) => {
      try {
        const req = op(d.transaction(STORE, mode).objectStore(STORE));
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => resolve(undefined);
      } catch {
        resolve(undefined); // quota, a closed database: saved copies are a bonus, never an error
      }
    });
  };
  return {
    async get(key) {
      return (await conn()) ? run('readonly', (s) => s.get(key)) : fallback.get(key);
    },
    async set(key, value) {
      if (await conn()) await run('readwrite', (s) => s.put(value, key));
      else await fallback.set(key, value);
    },
    async clear() {
      if (await conn()) await run('readwrite', (s) => s.clear());
      await fallback.clear();
    },
  };
}

let current: OfflineStore | null = null;

export function offlineStore(): OfflineStore {
  return (current ??= idbOfflineStore());
}

/** For tests. */
export function setOfflineStore(s: OfflineStore): void {
  current = s;
}

/** Screens worth reading offline: the library (not searches), ready, notes, actions, training. */
export function isCacheable(path: string): boolean {
  if (path.startsWith('/api/library?')) return !/[?&]q=/.test(path);
  return (
    path === '/api/ready' ||
    /^\/api\/items\/[^/]+$/.test(path) ||
    path.startsWith('/api/actions?') ||
    path === '/api/training' ||
    /^\/api\/training\/\d+$/.test(path)
  );
}
