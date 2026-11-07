// localStorage, falling back to memory when it's blocked (private mode, etc).
import { MemoryStorage, type KVStorage } from '../lib/queue';

function pick(): KVStorage {
  try {
    const ls = window.localStorage;
    const probe = '__vm_probe__';
    ls.setItem(probe, '1');
    ls.removeItem(probe);
    return ls;
  } catch {
    return new MemoryStorage();
  }
}

export const storage: KVStorage = pick();

export function readJSON<T>(key: string, fallback: T): T {
  try {
    const raw = storage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function writeJSON(key: string, value: unknown): void {
  try {
    storage.setItem(key, JSON.stringify(value));
  } catch {
    // quota or blocked; fine to lose a cache write
  }
}
