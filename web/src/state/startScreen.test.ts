import { beforeEach, describe, expect, it } from 'vitest';
import { initialTab, readStartChoice, rememberTab, saveStartChoice } from './startScreen';
import { storage } from './storage';

describe('start screen', () => {
  beforeEach(() => {
    for (const k of ['vm.startScreen.v1', 'vm.lastTab.v1']) storage.setItem(k, '');
  });

  it('opens Home the first time', () => {
    expect(readStartChoice()).toBe('home');
    expect(initialTab()).toBe('home');
  });

  it('opens the chosen tab', () => {
    saveStartChoice('deck');
    rememberTab('status');
    expect(initialTab()).toBe('deck');
  });

  it('opens where you left off, falling back to Home', () => {
    saveStartChoice('last');
    expect(initialTab()).toBe('home');
    rememberTab('train');
    expect(initialTab()).toBe('train');
  });

  it('ignores junk in storage', () => {
    storage.setItem('vm.startScreen.v1', '"nowhere"');
    expect(initialTab()).toBe('home');
    saveStartChoice('last');
    storage.setItem('vm.lastTab.v1', '42');
    expect(initialTab()).toBe('home');
  });
});
