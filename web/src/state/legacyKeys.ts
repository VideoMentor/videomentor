// Older installs saved this device's preferences under "ytm." keys. Copy them to the
// current "vm." keys once, so moving to VideoMentor keeps the start screen, undo history,
// lesson positions and views. Existing "vm." values always win; old keys are left alone.
import type { KVStorage } from '../lib/queue';

const OLD = 'ytm.';
const NEW = 'vm.';

export function migrateLegacyKeys(store: KVStorage, keys: string[]): number {
  let copied = 0;
  for (const key of keys) {
    if (!key.startsWith(OLD)) continue;
    const target = NEW + key.slice(OLD.length);
    const value = store.getItem(key);
    if (value === null || store.getItem(target) !== null) continue;
    store.setItem(target, value);
    copied++;
  }
  return copied;
}
