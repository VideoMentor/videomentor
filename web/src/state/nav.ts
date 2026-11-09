// Lets a sheet send the app to another tab (for example "Swipe this playlist").
import type { Tab } from '../components/TabBar';
import type { TagItemStatus } from '../lib/types';

const EVENT = 'vm:navigate';

export function navigate(tab: Tab): void {
  window.dispatchEvent(new CustomEvent<Tab>(EVENT, { detail: tab }));
}

export function onNavigate(fn: (tab: Tab) => void): () => void {
  const handler = (e: Event) => fn((e as CustomEvent<Tab>).detail);
  window.addEventListener(EVENT, handler);
  return () => window.removeEventListener(EVENT, handler);
}

/** A Tag page to open. `from` says where its Back button goes. */
export interface TagTarget {
  tag: string;
  status?: TagItemStatus;
  from?: 'list' | 'insights';
}

const TAG_EVENT = 'vm:open-tag';

/** Open the Tags screen on one tag's page (from the tag sheet, Insights, anywhere). */
export function openTag(target: TagTarget): void {
  window.dispatchEvent(new CustomEvent<TagTarget>(TAG_EVENT, { detail: target }));
}

export function onOpenTag(fn: (target: TagTarget) => void): () => void {
  const handler = (e: Event) => fn((e as CustomEvent<TagTarget>).detail);
  window.addEventListener(TAG_EVENT, handler);
  return () => window.removeEventListener(TAG_EVENT, handler);
}
