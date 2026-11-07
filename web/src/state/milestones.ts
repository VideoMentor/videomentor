// Ask the server for new milestones and hand them to the kit's overlay.
import { api } from '../lib/api';
import { milestones, type Milestone } from '../kit/delight/celebrate';

let timer: ReturnType<typeof setTimeout> | null = null;

function detail(kind: string, p: { kept: number; archived: number; hours: number; today: number }): string {
  if (kind === 'videos') return `${p.kept} kept · ${p.archived} archived · ${p.hours} hours of video`;
  if (kind === 'hours') return `That's ${(p.hours / 24).toFixed(1)} days of video, sorted.`;
  if (kind === 'streak') return `${p.today} decisions today. See you tomorrow.`;
  return '';
}

export async function checkMilestones(): Promise<void> {
  if (!navigator.onLine) return;
  try {
    const p = await api.progress();
    milestones(p.unseen.map((m: Milestone) => ({ ...m, detail: detail(m.kind, p) })));
  } catch {
    // not important enough to report
  }
}

/** Check a moment later, after queued swipes have reached the server. */
export function scheduleMilestoneCheck(delayMs = 1500): void {
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => void checkMilestones(), delayMs);
}
