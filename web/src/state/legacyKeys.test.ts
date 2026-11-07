import { describe, expect, it } from 'vitest';
import { MemoryStorage } from '../lib/queue';
import { migrateLegacyKeys } from './legacyKeys';

describe('migrateLegacyKeys', () => {
  it('copies older ytm. preferences to vm. keys once, never overwriting', () => {
    const store = new MemoryStorage();
    store.setItem('ytm.startScreen.v1', '"deck"');
    store.setItem('ytm.history.v1', '[1,2]');
    store.setItem('vm.history.v1', '[9]'); // already has a newer value
    store.setItem('other.key', 'x');
    const keys = ['ytm.startScreen.v1', 'ytm.history.v1', 'vm.history.v1', 'other.key'];

    expect(migrateLegacyKeys(store, keys)).toBe(1);
    expect(store.getItem('vm.startScreen.v1')).toBe('"deck"');
    expect(store.getItem('vm.history.v1')).toBe('[9]');
    expect(store.getItem('ytm.startScreen.v1')).toBe('"deck"'); // the old key stays
    expect(migrateLegacyKeys(store, [...keys, 'vm.startScreen.v1'])).toBe(0);
  });
});
