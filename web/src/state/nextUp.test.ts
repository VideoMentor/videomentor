import { beforeEach, describe, expect, it } from 'vitest';
import { readNextUpMode, readNextUpSkill, saveNextUpMode, saveNextUpSkill } from './nextUp';
import { storage } from './storage';

describe('next up setting', () => {
  beforeEach(() => {
    for (const k of ['vm.nextUp.v1', 'vm.nextUpSkill.v1']) storage.setItem(k, '');
  });

  it('shows Apply next until changed', () => {
    expect(readNextUpMode()).toBe('apply');
    saveNextUpMode('watch');
    expect(readNextUpMode()).toBe('watch');
  });

  it('ignores junk in storage', () => {
    storage.setItem('vm.nextUp.v1', '"later"');
    expect(readNextUpMode()).toBe('apply');
    storage.setItem('vm.nextUpSkill.v1', '42');
    expect(readNextUpSkill()).toBe('');
  });

  it('remembers the chosen skill, empty for any skill', () => {
    expect(readNextUpSkill()).toBe('');
    saveNextUpSkill('Negotiation');
    expect(readNextUpSkill()).toBe('Negotiation');
    saveNextUpSkill('');
    expect(readNextUpSkill()).toBe('');
  });
});
