// Action check-offs and notes made while the Mac can't be reached: saved here, sent later
// with the swipe queue. Repeat changes to one action merge, so the latest one wins.
import { readJSON, writeJSON } from '../state/storage';
import { ApiError, api, isNetworkError } from './api';
import { offlineStore } from './offlineStore';
import type { ActionItem, ActionStatus } from './types';

export type ActionPatch = { status?: ActionStatus; note?: string };
type Pending = { id: number; patch: ActionPatch; at: number };

const KEY = 'vm.actionQueue.v1';
let stamp = 0;

export function pendingActionUpdates(): Pending[] {
  const v = readJSON<unknown>(KEY, []);
  return Array.isArray(v) ? (v as Pending[]) : [];
}

export function queueActionUpdate(id: number, patch: ActionPatch): void {
  const list = pendingActionUpdates();
  const at = Math.max(Date.now(), stamp + 1); // strictly increasing, so a newer change is always "different"
  stamp = at;
  const i = list.findIndex((p) => p.id === id);
  if (i >= 0) list[i] = { id, patch: { ...list[i].patch, ...patch }, at };
  else list.push({ id, patch, at });
  writeJSON(KEY, list);
}

let running: Promise<number> | null = null;

/** Send queued changes in order, one flush at a time. Changes made during the send stay
 *  queued; changes the Mac permanently rejects (for example a deleted step) are dropped. */
export function flushActionQueue(send: (id: number, patch: ActionPatch) => Promise<unknown>): Promise<number> {
  return (running ??= (async () => {
    const snapshot = pendingActionUpdates();
    const done = new Set<string>();
    for (const p of snapshot) {
      try {
        await send(p.id, p.patch);
        done.add(`${p.id}:${p.at}`);
      } catch (err) {
        if (err instanceof ApiError && err.permanent) done.add(`${p.id}:${p.at}`);
      }
    }
    // Re-read: anything queued or changed while sending has a new stamp and stays.
    writeJSON(KEY, pendingActionUpdates().filter((p) => !done.has(`${p.id}:${p.at}`)));
    return [...done].length;
  })().finally(() => {
    running = null;
  }));
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

/** One action change, the way every screen makes it: sent now, or (with no connection)
 *  saved for later and applied to the saved Actions lists. Other errors are passed on. */
export async function sendActionUpdate(
  id: number,
  patch: ActionPatch,
  send: (id: number, patch: ActionPatch) => Promise<unknown> = (i, p) => api.updateAction(i, p),
): Promise<'sent' | 'queued'> {
  try {
    await send(id, patch);
    return 'sent';
  } catch (err) {
    if (!isNetworkError(err)) throw err;
    queueActionUpdate(id, patch);
    void applyToSavedActions(id, patch); // IndexedDB can be slow on iOS; never hold the screen
    return 'queued';
  }
}
