import { describe, expect, it } from 'vitest';
import { MemoryStorage } from './queue';
import { LAST_BATCH_KEY, archiveQuestion, broughtBackLine, clearLastBatch, consumeLegacyDeckKey, nlLine, readLastBatch, saveLastBatch } from './notForLearning';

describe('not for learning text', () => {
  it('says how many are waiting and how many are older', () => {
    expect(nlLine({ inbox: 462, older: 410 }, 30)).toBe('462 waiting, 410 older than 30 days');
    expect(nlLine({ inbox: 1, older: 0 }, 30)).toBe('1 waiting, 0 older than 30 days');
  });

  it('asks for confirmation with the count and the way back', () => {
    expect(archiveQuestion(410)).toBe('Archive 410 videos? You can undo this.');
    expect(archiveQuestion(1)).toBe('Archive 1 video? You can undo this.');
  });
});

describe('last batch', () => {
  it('survives a reload until cleared', () => {
    const store = new MemoryStorage();
    expect(LAST_BATCH_KEY).toBe('vm.nlLastBatch.v1');
    expect(readLastBatch(store)).toBeNull();
    saveLastBatch(store, { batch: 'nl-1', archived: 410 });
    expect(readLastBatch(store)).toEqual({ batch: 'nl-1', archived: 410 });
    clearLastBatch(store);
    expect(readLastBatch(store)).toBeNull();
  });

  it('ignores junk', () => {
    const store = new MemoryStorage();
    store.setItem(LAST_BATCH_KEY, '{"batch":5}');
    expect(readLastBatch(store)).toBeNull();
    store.setItem(LAST_BATCH_KEY, 'nope');
    expect(readLastBatch(store)).toBeNull();
  });
});

describe('undo message', () => {
  it('says how many came back and how many stayed', () => {
    expect(broughtBackLine(410, 0)).toBe('Brought back 410.');
    expect(broughtBackLine(9, 3)).toBe('Brought back 9. 3 were decided again since and stayed as they are.');
    expect(broughtBackLine(0, 1)).toBe('Brought back 0. 1 was decided again since and stayed as they are.');
    expect(broughtBackLine(0, 0)).toBe('Nothing left to bring back.');
  });
});

describe('old Music deck preference', () => {
  it('moves a device that was on Music to Not for learning and removes the key', () => {
    const store = new MemoryStorage();
    store.setItem('vm.deckKey', '"music"');
    expect(consumeLegacyDeckKey(store)).toEqual({ key: 'nl', label: 'Not for learning' });
    expect(store.getItem('vm.deckKey')).toBeNull();
    expect(consumeLegacyDeckKey(store)).toBeNull();
  });

  it('removes the key but changes nothing for the main deck', () => {
    const store = new MemoryStorage();
    store.setItem('vm.deckKey', '"main"');
    expect(consumeLegacyDeckKey(store)).toBeNull();
    expect(store.getItem('vm.deckKey')).toBeNull();
  });
});
