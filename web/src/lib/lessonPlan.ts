// A training module as one playable sequence: cards between clips from different videos.
import type { TrainingClip, TrainingModuleBody } from './types';

export type Step =
  | { kind: 'intro'; title: string; lines: string[] }
  | { kind: 'lesson'; lesson: number; title: string; lines: string[] }
  | { kind: 'cue'; lesson: number; clip: number; title: string; lines: string[] }
  | { kind: 'clip'; lesson: number; clip: number; data: TrainingClip }
  | { kind: 'exercise'; lesson: number; title: string; lines: string[] }
  | { kind: 'done'; title: string; lines: string[] };

export type CardStep = Exclude<Step, { kind: 'clip' }>;

const mins = (s: number) => Math.max(1, Math.round(s / 60));

/** Seconds of video in the module (clip lengths only, not cards). */
export function watchSeconds(m: TrainingModuleBody): number {
  return m.lessons.reduce((t, l) => t + l.clips.reduce((u, c) => u + Math.max(0, c.end - c.start), 0), 0);
}

/** Opening card, then per lesson: its card, a cue and the clip for each clip, its exercise; then a finish card. */
export function buildSteps(m: TrainingModuleBody): Step[] {
  const videos = new Set(m.lessons.flatMap((l) => l.clips.map((c) => c.video)));
  const clips = m.lessons.reduce((n, l) => n + l.clips.length, 0);
  const steps: Step[] = [
    {
      kind: 'intro',
      title: m.title,
      lines: [
        m.outcome,
        `${m.lessons.length} ${m.lessons.length === 1 ? 'lesson' : 'lessons'} · ${clips} ${clips === 1 ? 'clip' : 'clips'} from ${videos.size} ${videos.size === 1 ? 'video' : 'videos'} · about ${mins(watchSeconds(m))} min of video`,
        ...(m.goal ? [`Your goal: ${m.goal}`] : []),
      ],
    },
  ];
  m.lessons.forEach((l, i) => {
    steps.push({ kind: 'lesson', lesson: i, title: `Lesson ${i + 1}: ${l.title}`, lines: [l.goal] });
    l.clips.forEach((c, j) => {
      steps.push({
        kind: 'cue',
        lesson: i,
        clip: j,
        title: c.title ?? 'Next clip',
        lines: [c.why, `Watch for: ${c.watch_for}`, ...(c.channel ? [`From ${c.channel}`] : [])],
      });
      steps.push({ kind: 'clip', lesson: i, clip: j, data: c });
    });
    if (l.exercise) steps.push({ kind: 'exercise', lesson: i, title: 'Try it', lines: [l.exercise] });
  });
  steps.push({
    kind: 'done',
    title: 'Lesson complete',
    lines: m.quiz.length ? [`Check yourself with the ${m.quiz.length}-question quiz below the lessons.`] : ['Nice work.'],
  });
  return steps;
}

/** Index of a lesson's opening card, for "Play from here". */
export function lessonStart(steps: Step[], lesson: number): number {
  const i = steps.findIndex((s) => s.kind === 'lesson' && s.lesson === lesson);
  return i < 0 ? 0 : i;
}

/** A saved position, kept inside the plan (a module can change shape after a rebuild). */
export function clampStep(steps: Step[], saved: unknown): number {
  const n = typeof saved === 'number' && Number.isInteger(saved) ? saved : 0;
  return Math.min(Math.max(0, n), steps.length - 1);
}

/** Text the read-aloud voice says for a card. */
export function spoken(step: CardStep): string {
  return [step.title, ...step.lines].join('. ').replace(/\.\./g, '.');
}

/** "Lesson 2 · clip 3 of 9" style label; clip numbers count across the whole module. */
export function where(steps: Step[], i: number): string {
  const s = steps[i];
  const totalClips = steps.filter((x) => x.kind === 'clip').length;
  if (s.kind === 'intro' || s.kind === 'done') return s.kind === 'intro' ? 'Start' : 'Finish';
  const clipNo = steps.slice(0, i + 1).filter((x) => x.kind === 'clip').length + (s.kind === 'cue' ? 1 : 0);
  const lesson = `Lesson ${s.lesson + 1}`;
  return s.kind === 'cue' || s.kind === 'clip' ? `${lesson} · clip ${clipNo} of ${totalClips}` : lesson;
}

/** YouTube's video id for a clip (modules store the app's item id, "yt:<videoId>"). */
export function videoIdOf(c: Pick<TrainingClip, 'video'>): string {
  return c.video.replace(/^yt:/, '');
}
