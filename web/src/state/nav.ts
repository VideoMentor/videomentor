// Lets a sheet send the app to another tab (for example "Swipe this playlist").
import type { Tab } from '../components/TabBar';

const EVENT = 'vm:navigate';

export function navigate(tab: Tab): void {
  window.dispatchEvent(new CustomEvent<Tab>(EVENT, { detail: tab }));
}

export function onNavigate(fn: (tab: Tab) => void): () => void {
  const handler = (e: Event) => fn((e as CustomEvent<Tab>).detail);
  window.addEventListener(EVENT, handler);
  return () => window.removeEventListener(EVENT, handler);
}
