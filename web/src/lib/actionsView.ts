// Group actions under their video, keeping the server's order. Pure, tested.
import type { ActionItem } from './types';

export interface ActionGroup {
  itemId: string;
  actions: ActionItem[];
}

export function groupByVideo(actions: ActionItem[]): ActionGroup[] {
  const out: ActionGroup[] = [];
  const at = new Map<string, ActionGroup>();
  for (const a of actions) {
    let g = at.get(a.item_id);
    if (!g) {
      g = { itemId: a.item_id, actions: [] };
      at.set(a.item_id, g);
      out.push(g);
    }
    g.actions.push(a);
  }
  return out;
}
