import { describe, expect, it } from 'vitest';
import { groupByVideo } from './actionsView';
import type { ActionItem } from './types';

const a = (id: number, item: string): ActionItem =>
  ({ id, item_id: item, text: `t${id}`, position: 0, status: 'open', note: null, created_at: '', done_at: null, item: null }) as ActionItem;

describe('groupByVideo', () => {
  it('keeps first-seen video order and action order', () => {
    const g = groupByVideo([a(1, 'x'), a(2, 'y'), a(3, 'x')]);
    expect(g.map((x) => [x.itemId, x.actions.map((y) => y.id)])).toEqual([
      ['x', [1, 3]],
      ['y', [2]],
    ]);
  });
});
