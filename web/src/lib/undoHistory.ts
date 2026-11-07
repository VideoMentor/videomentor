// Undo history rules: the last 20 steps (two decks of 10), kept across sessions, and
// a plain description of each step for the "Undid: …" message.

/** Exactly two decks of 10. A group decision counts as one step. */
export const UNDO_LIMIT = 20;

export interface UndoStep {
  kind: 'decision' | 'group';
  action: string;
  card?: { title: string };
  cards?: unknown[];
  label?: string;
}

export function pushCapped<T>(history: T[], entry: T, limit = UNDO_LIMIT): T[] {
  return [...history, entry].slice(-limit);
}

function isStep(x: unknown): boolean {
  if (!x || typeof x !== 'object') return false;
  const e = x as Record<string, unknown>;
  if (e.kind === 'decision') return typeof e.action === 'string' && !!e.card && typeof e.card === 'object';
  if (e.kind === 'group') return typeof e.action === 'string' && Array.isArray(e.cards);
  return false;
}

/** Run on load: drop malformed entries, and shrink histories saved by older versions (which kept 30). */
export function trimHistory<T>(history: unknown, limit = UNDO_LIMIT): T[] {
  return Array.isArray(history) ? (history.filter(isStep) as T[]).slice(-limit) : [];
}

/** Remove one entry by identity, so a swipe made while an undo was waiting is kept. */
export function removeEntry<T>(history: T[], entry: T): T[] {
  const i = history.lastIndexOf(entry);
  return i < 0 ? history : [...history.slice(0, i), ...history.slice(i + 1)];
}

const VERB: Record<string, string> = { keep: 'Kept', archive: 'Archived', prioritize: 'Kept, analyze first' };

function short(title: string, max = 48): string {
  const t = title.trim() || 'Untitled video';
  return t.length > max ? `${t.slice(0, max - 1).trimEnd()}…` : t;
}

/** "Kept “Title”", or for a group "Archived 12 in “pricing”". */
export function describeStep(step: UndoStep): string {
  const verb = VERB[step.action] ?? step.action;
  if (step.kind === 'group') {
    const n = step.cards?.length ?? 0;
    return `${verb} ${n} in “${short(step.label ?? 'group', 32)}”`;
  }
  return `${verb} “${short(step.card?.title ?? '')}”`;
}

/** The toast after an undo: what was undone, and whether more steps remain. */
export function undoneMessage(step: UndoStep, remaining: number): { message: string; undoLabel?: string } {
  return { message: `Undid: ${describeStep(step)}`, undoLabel: remaining > 0 ? 'Undo previous' : undefined };
}

/** The toast when the server can't undo a step because it was decided again since. */
export function conflictMessage(step: UndoStep, remaining: number): { message: string; undoLabel?: string } {
  return { message: `Can’t undo ${describeStep(step)}: it changed since`, undoLabel: remaining > 0 ? 'Undo previous' : undefined };
}
