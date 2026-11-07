// Plays a training module as one lesson: cards between clips from different videos,
// each clip from its start to its end time in YouTube's own player (nothing downloaded).
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { buildSteps, clampStep, spoken, videoIdOf, where, type CardStep, type Step } from '../lib/lessonPlan';
import { formatDuration } from '../lib/format';
import type { TrainingModuleBody } from '../lib/types';
import { loadYouTubeApi, type YTPlayer } from '../lib/youtubeApi';

const POS_KEY = (id: number) => `vm.lessonPos.v1.${id}`;
const VOICE_KEY = 'vm.lessonVoice.v1';
export const LAST_LESSON_KEY = 'vm.lastLesson.v1';

function read<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
}
function write(key: string, v: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* private mode: position just isn't remembered */
  }
}

export function LessonPlayer({
  moduleId,
  body,
  startAt,
  onClose,
}: {
  moduleId: number;
  body: TrainingModuleBody;
  /** A step index to start from; otherwise resume where you left off. */
  startAt?: number;
  onClose(): void;
}) {
  const steps = useMemo(() => buildSteps(body), [body]);
  const [i, setI] = useState(() => {
    if (startAt !== undefined) return clampStep(steps, startAt);
    // A saved position only counts if the module still has the same shape (it may be rebuilt).
    const saved = read<{ i?: number; n?: number } | null>(POS_KEY(moduleId), null);
    return saved?.n === steps.length ? clampStep(steps, saved.i) : 0;
  });
  const [voice, setVoice] = useState(() => read(VOICE_KEY, false) && 'speechSynthesis' in window);
  const step = steps[i];

  const go = useCallback((n: number) => setI(clampStep(steps, n)), [steps]);
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => write(POS_KEY(moduleId), { i: step.kind === 'done' ? 0 : i, n: steps.length }), [moduleId, i, step.kind, steps.length]);
  // Home offers "Continue training" from here.
  useEffect(
    () => write(LAST_LESSON_KEY, { id: moduleId, title: body.title, step: i, steps: steps.length, done: step.kind === 'done' }),
    [moduleId, body.title, i, steps.length, step.kind],
  );
  useEffect(() => write(VOICE_KEY, voice), [voice]);

  // Arrow keys and Escape on the Mac and iPad keyboards.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Leave browser shortcuts (Cmd+Left is Back in Safari) and text fields alone.
      const t = e.target as HTMLElement | null;
      if (e.metaKey || e.ctrlKey || e.altKey || t?.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t?.tagName ?? '')) return;
      if (e.key === 'ArrowRight') go(i + 1);
      else if (e.key === 'ArrowLeft') go(i - 1);
      else if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [go, i, onClose]);

  // Move focus into the player, and give it back to whatever opened it on close.
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    dialog.current?.focus();
    return () => before?.focus?.();
  }, []);

  // Read cards aloud when the voice is on; stop speaking when the step changes or the player closes.
  useEffect(() => {
    if (!('speechSynthesis' in window) || !voice || step.kind === 'clip') return;
    // A short gap after the previous card's cancel: Safari can drop an utterance queued right after cancel().
    const t = setTimeout(() => window.speechSynthesis.speak(new SpeechSynthesisUtterance(spoken(step))), 80);
    return () => {
      clearTimeout(t);
      window.speechSynthesis.cancel();
    };
  }, [voice, step]);

  const progress = steps.length > 1 ? (i / (steps.length - 1)) * 100 : 100;

  return (
    <div className="lesson-player" role="dialog" aria-modal="true" aria-label={`Lesson player: ${body.title}`} ref={dialog} tabIndex={-1}>
      <header className="lp-head">
        <button className="link-btn" onClick={onClose}>
          Close
        </button>
        <span className="lp-where" aria-live="polite">
          {where(steps, i)}
        </span>
        {'speechSynthesis' in window ? (
          <button className={`link-btn lp-voice${voice ? ' on' : ''}`} onClick={() => setVoice((v) => !v)} aria-pressed={voice}>
            {voice ? 'Voice on' : 'Voice off'}
          </button>
        ) : (
          <span />
        )}
      </header>
      <div className="lp-progress" aria-hidden="true">
        <div style={{ width: `${progress}%` }} />
      </div>
      <div className="lp-stage">
        {step.kind === 'clip' ? <ClipStage key={i} step={step} onEnded={() => go(i + 1)} /> : <CardStage step={step} />}
      </div>
      <footer className="lp-controls">
        <button className="secondary" onClick={() => go(i - 1)} disabled={i === 0}>
          ‹ Back
        </button>
        {step.kind === 'done' ? (
          <button className="primary" onClick={onClose}>
            Finish
          </button>
        ) : (
          <button className="primary" onClick={() => go(i + 1)}>
            {step.kind === 'cue' ? 'Play clip ›' : step.kind === 'clip' ? 'Skip clip ›' : 'Next ›'}
          </button>
        )}
      </footer>
    </div>
  );
}

function CardStage({ step }: { step: CardStep }) {
  return (
    <div className={`lp-card lp-${step.kind}`}>
      <h2>{step.title}</h2>
      {step.lines.map((l, k) => (
        <p key={k} className={k === 0 ? 'lp-lead' : 'muted'}>
          {l}
        </p>
      ))}
    </div>
  );
}

function ClipStage({ step, onEnded }: { step: Extract<Step, { kind: 'clip' }>; onEnded(): void }) {
  const host = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  const ended = useRef(onEnded);
  ended.current = onEnded;
  const c = step.data;

  useEffect(() => {
    let player: YTPlayer | null = null;
    let gone = false;
    loadYouTubeApi()
      .then((YT) => {
        if (gone || !host.current) return;
        const el = document.createElement('div');
        host.current.replaceChildren(el);
        player = new YT.Player(el, {
          videoId: videoIdOf(c),
          playerVars: { start: c.start, end: c.end, autoplay: 1, playsinline: 1, rel: 0, origin: window.location.origin },
          events: {
            // The embed stops at `end` and reports ENDED: move on to the next card.
            onStateChange: (e) => e.data === YT.PlayerState.ENDED && ended.current(),
            onError: () => setFailed(true),
          },
        });
      })
      .catch(() => setFailed(true));
    return () => {
      gone = true;
      player?.destroy();
    };
  }, [c.video, c.start, c.end]);

  return (
    <div className="lp-clip">
      <div className="lp-video" ref={host} />
      {failed && (
        <p className="note small">
          This clip can't play here.{' '}
          <a href={`https://www.youtube.com/watch?v=${encodeURIComponent(videoIdOf(c))}&t=${c.start}s`} target="_blank" rel="noopener noreferrer">
            Open it on YouTube
          </a>
          , then tap Skip clip.
        </p>
      )}
      <p className="lp-clip-meta">
        <b>{c.title}</b>
        <span className="muted">
          {[c.channel, `${formatDuration(c.start) || '0:00'} to ${formatDuration(c.end)}`].filter(Boolean).join(' · ')}
        </span>
      </p>
      <p className="muted small">Watch for: {c.watch_for}</p>
    </div>
  );
}
