import { describe, expect, it } from 'vitest';
import { MemoryStorage } from './queue';
import { LAST_BATCH_KEY, archiveQuestion, clearLastBatch, nlLine, readLastBatch, saveLastBatch } from './notForLearning';

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
