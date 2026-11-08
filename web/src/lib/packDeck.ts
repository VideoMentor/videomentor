// Dealing a round from the offline pack when the Mac can't be reached.
import type { OfflineStore } from './offlineStore';
import type { PackDecks } from './offlinePack';
import type { Card } from './types';

/** The next `n` pack cards not in `skip` (decided, queued, or already in hand), and what's left. */
export function takeFromPack(cards: Card[], n: number, skip: Set<string>): { round: Card[]; rest: Card[] } {
  const fresh = cards.filter((c) => !skip.has(c.id));
  return { round: fresh.slice(0, n), rest: fresh.slice(n) };
}

/** Take a decided card out of the saved pack, so it is never dealt again offline. */
export async function removeFromPack(store: OfflineStore, id: string): Promise<void> {
  const saved = (await store.get('pack:decks')) as PackDecks | undefined;
  if (!saved) return;
  const strip = (cs: Card[] = []) => cs.filter((c) => c.id !== id);
  const decks = { main: strip(saved.decks.main), music: strip(saved.decks.music) };
  if (decks.main.length === (saved.decks.main ?? []).length && decks.music.length === (saved.decks.music ?? []).length) return;
  await store.set('pack:decks', { ...saved, decks });
}
