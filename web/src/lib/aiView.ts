import type { AiChoice, StatusResponse } from './types';

export const AI_CHOICES: { value: AiChoice; label: string }[] = [
  { value: 'auto', label: 'Auto' },
  { value: 'claude_code', label: 'Claude Code' },
  { value: 'api', label: 'API key' },
  { value: 'off', label: 'Off' },
];

export const AI_OFF_ADDS = 'Turning AI on adds card summaries, tags, scores, notes, actions and training.';

const OFF_PREFIX = 'AI is off: ';
const usd = (n: number) => `$${n.toFixed(2)}`;

/** The one-line AI summary on Status. Empty when the engine sends nothing about AI. */
export function aiLine(status: StatusResponse | null | undefined): string {
  const ai = status?.ai;
  if (!ai) return '';
  if (ai.backend === 'off') {
    // Off by choice says just that; off because the chosen backend is missing says why.
    const why =
      ai.choice !== 'off' && ai.reason?.startsWith(OFF_PREFIX) ? ` (${ai.reason.slice(OFF_PREFIX.length)})` : '';
    return `AI: off${why} · cards show without summaries or notes`;
  }
  if (ai.paused && ai.reason) return ai.reason;
  if (ai.backend === 'api') return `AI: API key · ${usd(ai.month_cost_usd)} of ${usd(ai.cap_usd)} this month`;
  return 'AI: Claude Code';
}

/** The monthly cap only matters when the API key may be used. */
export function capShown(choice: AiChoice): boolean {
  return choice === 'api' || choice === 'auto';
}

/** With AI off or paused, unprepped videos are dealt and counted in the inbox already. */
export function hidesUnprepped(status: StatusResponse | null | undefined): boolean {
  const ai = status?.ai;
  return !!ai && (ai.paused || ai.backend === 'off');
}
