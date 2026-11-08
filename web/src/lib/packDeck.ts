// Dealing a round from the offline pack when the Mac can't be reached.
import type { Card } from './types';

/** The next `n` pack cards not in `skip` (decided, queued, or already in hand), and what's left. */
export function takeFromPack(cards: Card[], n: number, skip: Set<string>): { round: Card[]; rest: Card[] } {
  const fresh = cards.filter((c) => !skip.has(c.id));
  return { round: fresh.slice(0, n), rest: fresh.slice(n) };
}
