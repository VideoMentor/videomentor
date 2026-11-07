// The one decision queue for the app, wired to the real API.
import { useSyncExternalStore } from 'react';
import { DecisionQueue } from '../lib/queue';
import { queueTransport } from '../lib/api';
import { storage } from './storage';

export const queue = new DecisionQueue({ storage, transport: queueTransport });

const subscribe = (fn: () => void) => queue.subscribe(fn);

/** Number of ops waiting to reach the server; re-renders on change. */
export function useQueueLength(): number {
  return useSyncExternalStore(subscribe, () => queue.length);
}

export function useQueueFlushing(): boolean {
  return useSyncExternalStore(subscribe, () => queue.isFlushing);
}
