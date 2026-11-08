// Action check-offs and notes made while the Mac can't be reached: saved here, sent later
// with the swipe queue. Repeat changes to one action merge, so the latest one wins.
import { readJSON, writeJSON } from '../state/storage';
import { offlineStore } from './offlineStore';
import type { ActionItem, ActionStatus } from './types';

export type ActionPatch = { status?: ActionStatus; note?: string };
type Pending = { id: number; patch: ActionPatch };

const KEY = 'vm.actionQueue.v1';

export function pendingActionUpdates(): Pending[] {
  const v = readJSON<unknown>(KEY, []);
  return Array.isArray(v) ? (v as Pending[]) : [];
}

export function queueActionUpdate(id: number, patch: ActionPatch): void {
  const list = pendingActionUpdates();
  const at = list.findIndex((p) => p.id === id);
  if (at >= 0) list[at] = { id, patch: { ...list[at].patch, ...patch } };
  else list.push({ id, patch });
  writeJSON(KEY, list);
}

/** Send queued changes in order; keep the ones that fail for the next try. */
export async function flushActionQueue(send: (id: number, patch: ActionPatch) => Promise<unknown>): Promise<number> {
  const list = pendingActionUpdates();
  const left: Pending[] = [];
  let sent = 0;
  for (const p of list) {
    try {
      await send(p.id, p.patch);
      sent++;
    } catch {
      left.push(p);
    }
  }
  writeJSON(KEY, left);
  return sent;
}

/** Apply a change to the saved Actions lists, so it's still there if the app reopens offline. */
export async function applyToSavedActions(id: number, patch: ActionPatch): Promise<void> {
  const store = offlineStore();
  for (const s of ['all', 'open', 'done', 'skipped']) {
    const key = `/api/actions?status=${s}`;
    const saved = (await store.get(key)) as { actions: ActionItem[]; counts: unknown } | undefined;
    if (!saved?.actions) continue;
    const actions = saved.actions.map((a) => (a.id === id ? { ...a, ...patch, note: patch.note ?? a.note } : a));
    await store.set(key, { ...saved, actions });
  }
}
