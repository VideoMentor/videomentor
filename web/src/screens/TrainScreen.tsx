// Training modules built from your own kept videos: lessons of clips, exercises, a quiz.
import { useCallback, useEffect, useState } from 'react';
import { AuthError, api, isNetworkError } from '../lib/api';
import { formatDuration, relativeTime } from '../lib/format';
import type { RenderStatus, TrainingModule } from '../lib/types';
import { LessonPlayer } from '../components/LessonPlayer';
import { readJSON, writeJSON } from '../state/storage';
import { buildSteps, lessonStart } from '../lib/lessonPlan';
import { LAST_LESSON_KEY } from '../components/LessonPlayer';

/** Home's "Continue training" leaves {id, play} here for the Train tab to open. */
export const OPEN_MODULE_KEY = 'vm.trainOpen.v1';
type OpenRequest = { id: number; play: boolean };

function readOpenRequest(): OpenRequest | null {
  const r = readJSON<unknown>(OPEN_MODULE_KEY, null);
  if (r && typeof r === 'object' && typeof (r as OpenRequest).id === 'number') return { id: (r as OpenRequest).id, play: !!(r as OpenRequest).play };
  return null;
}

const stamp = (s: number) => formatDuration(s) || '0:00';

export function TrainScreen({ online }: { online: boolean }) {
  const [list, setList] = useState<TrainingModule[] | null>(null);
  const [request] = useState(readOpenRequest);
  const [openId, setOpenId] = useState<number | null>(request?.id ?? null);
  useEffect(() => writeJSON(OPEN_MODULE_KEY, null), []); // consumed
  const [error, setError] = useState<string | null>(null);
  const [tag, setTag] = useState('');
  const [goal, setGoal] = useState('');
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setList((await api.trainingList()).modules);
      setError(null);
    } catch (err) {
      if (!(err instanceof AuthError)) setError(isNetworkError(err) ? 'Training needs a connection.' : (err as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, online]);

  // While a module is building, check every few seconds.
  const building = list?.some((m) => m.status === 'building');
  useEffect(() => {
    if (!building) return;
    const t = setInterval(() => void load(), 4000);
    return () => clearInterval(t);
  }, [building, load]);

  const build = async () => {
    setNote(null);
    try {
      await api.buildTraining(tag.trim(), goal.trim());
      setTag('');
      setGoal('');
      setNote('Building. It takes a minute or two; it shows up below.');
      void load();
    } catch (err) {
      setNote((err as Error).message);
    }
  };

  if (openId !== null) {
    return <ModuleView id={openId} autoPlay={request?.id === openId && request.play} onBack={() => setOpenId(null)} />;
  }

  return (
    <section className="page" aria-label="Train">
      <header className="page-head">
        <h1>Train</h1>
      </header>
      <div className="scroll page-body train-body">
        <div className="card-block train-new">
          <h4>New module</h4>
          <p className="note small">Built from the videos you kept with this tag. Or tap a tag anywhere and choose “Build training”.</p>
          <input value={tag} placeholder="Tag, e.g. communication skills" aria-label="Tag" onChange={(e) => setTag(e.target.value)} />
          <input value={goal} placeholder="Goal (optional), e.g. a hard talk on Thursday" aria-label="Goal" onChange={(e) => setGoal(e.target.value)} />
          <button className="primary" onClick={() => void build()} disabled={!tag.trim() || !online}>
            Build training
          </button>
          {note && <p className="note small">{note}</p>}
        </div>
        {error && <p className="note">{error}</p>}
        {list && list.length === 0 && <p className="note">No modules yet.</p>}
        <ul className="rows">
          {(list ?? []).map((m) => (
            <li key={m.id}>
              <button className="row train-row" onClick={() => m.status === 'ready' && setOpenId(m.id)} disabled={m.status !== 'ready'}>
                <span className="row-text">
                  <span className="row-title">{m.title || m.tag}</span>
                  <small>
                    {m.status === 'building'
                      ? 'Building…'
                      : m.status === 'failed'
                        ? `Failed: ${m.error ?? ''}`
                        : `${m.lessons} lessons · ${m.clips} clips · ${m.tag} · ${relativeTime(m.created_at)}`}
                  </small>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function ModuleView({ id, onBack, autoPlay = false }: { id: number; onBack(): void; autoPlay?: boolean }) {
  const [m, setM] = useState<TrainingModule | null>(null);
  const [missing, setMissing] = useState<string | null>(null);
  const [shown, setShown] = useState<Set<number>>(new Set());
  // undefined: player closed; null: resume where you left off; a number: start at that step.
  const [playing, setPlaying] = useState<number | null | undefined>(autoPlay ? null : undefined);
  useEffect(() => {
    const ctl = new AbortController();
    api
      .training(id, ctl.signal)
      .then(setM)
      .catch((err) => {
        if (ctl.signal.aborted) return;
        if (isNetworkError(err)) setMissing('This lesson needs a connection.');
        else {
          // Deleted or rebuilt: stop offering it on Home.
          if (readJSON<{ id?: number } | null>(LAST_LESSON_KEY, null)?.id === id) writeJSON(LAST_LESSON_KEY, null);
          setMissing('This lesson is no longer here.');
        }
      });
    return () => ctl.abort();
  }, [id]);
  const body = m?.module;
  if (body && playing !== undefined) {
    return <LessonPlayer moduleId={id} body={body} startAt={playing ?? undefined} onClose={() => setPlaying(undefined)} />;
  }
  return (
    <section className="page" aria-label="Training module">
      <header className="page-head">
        <button className="link-btn" onClick={onBack}>
          ‹ Train
        </button>
        {body?.minutes ? <span className="muted small">about {body.minutes} min</span> : null}
      </header>
      <div className="scroll page-body train-body">
        {!body && <p className="note">{missing ?? 'Loading…'}</p>}
        {body && (
          <>
            <h2 className="train-title">{body.title}</h2>
            <p className="train-outcome">{body.outcome}</p>
            {body.goal && <p className="note small">Your goal: {body.goal}</p>}
            <button className="primary train-play" onClick={() => setPlaying(null)}>
              ▶ Play lesson
            </button>
            <VideoBlock id={id} initial={m?.video} />
            {body.lessons.map((lesson, i) => (
              <section key={i} className="card-block lesson">
                <div className="lesson-num">
                  Lesson {i + 1}
                  <button className="link-btn small" onClick={() => setPlaying(lessonStart(buildSteps(body), i))}>
                    ▶ Play from here
                  </button>
                </div>
                <h3>{lesson.title}</h3>
                <p className="note">{lesson.goal}</p>
                <ul className="clips">
                  {lesson.clips.map((c, j) => (
                    <li key={j}>
                      <a className="clip" href={c.url} target="_blank" rel="noopener noreferrer">
                        <img src={c.thumbnail} alt="" loading="lazy" />
                        <span className="clip-time">
                          ▶ {stamp(c.start)} to {stamp(c.end)}
                        </span>
                      </a>
                      <div className="clip-text">
                        <b>{c.title}</b>
                        <p>{c.why}</p>
                        <p className="muted small">Watch for: {c.watch_for}</p>
                      </div>
                    </li>
                  ))}
                </ul>
                <div className="why exercise">
                  <span>Try it</span>
                  {lesson.exercise}
                </div>
              </section>
            ))}
            {body.quiz.length > 0 && (
              <section className="card-block">
                <h4>Quiz</h4>
                <ol className="quiz">
                  {body.quiz.map((q, i) => (
                    <li key={i}>
                      <p>{q.question}</p>
                      {shown.has(i) ? (
                        <p className="quiz-answer">
                          {q.answer}{' '}
                          <a href={q.url} target="_blank" rel="noopener noreferrer">
                            ▶ {stamp(q.t)}
                          </a>
                        </p>
                      ) : (
                        <button className="link-btn small" onClick={() => setShown((s) => new Set(s).add(i))}>
                          Show answer
                        </button>
                      )}
                    </li>
                  ))}
                </ol>
              </section>
            )}
            {body.gaps.length > 0 && (
              <section className="card-block">
                <h4>Not covered yet</h4>
                <div className="chips">
                  {body.gaps.map((g) => (
                    <a key={g} className="chip" href={`https://www.youtube.com/results?search_query=${encodeURIComponent(g)}`} target="_blank" rel="noopener noreferrer">
                      {g} ↗
                    </a>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </section>
  );
}

/** One narrated video of the whole module, rendered on the Mac. Personal use only. */
function VideoBlock({ id, initial }: { id: number; initial?: RenderStatus }) {
  const [v, setV] = useState<RenderStatus>(initial ?? { state: 'none' });
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (initial) setV(initial);
  }, [initial]);

  // While it renders, check every few seconds.
  useEffect(() => {
    if (v.state !== 'rendering') return;
    const t = setInterval(() => {
      api
        .renderStatus(id)
        .then(setV)
        .catch(() => {});
    }, 4000);
    return () => clearInterval(t);
  }, [id, v.state]);

  const start = async () => {
    setNote(null);
    try {
      setV(await api.renderTraining(id));
    } catch (err) {
      setNote(isNetworkError(err) ? 'Rendering needs a connection.' : (err as Error).message);
    }
  };

  return (
    <section className="card-block train-video">
      <h4>Training video</h4>
      {v.state === 'ready' ? (
        <>
          <a className="primary train-watch" href={`/api/training/${id}/video`} target="_blank" rel="noopener">
            ▶ Watch video{v.seconds ? ` (${Math.max(1, Math.round(v.seconds / 60))} min)` : ''}
          </a>
          <button className="link-btn small" onClick={() => void start()}>
            Render again
          </button>
        </>
      ) : v.state === 'rendering' ? (
        <p className="note small">
          Rendering on the Mac{v.total ? `: ${v.done ?? 0} of ${v.total} parts` : '…'}. Clips download the first time, so this takes a few minutes.
        </p>
      ) : (
        <>
          <p className="note small">
            {v.state === 'failed' ? `Last render failed: ${v.error ?? 'unknown error'}` : 'One narrated video of this module: cards, clips and credits, rendered on your Mac.'}
          </p>
          <button className="secondary" onClick={() => void start()}>
            {v.state === 'failed' ? 'Try again' : 'Render video'}
          </button>
        </>
      )}
      <p className="muted small">Personal use only: clips belong to their creators, so don't share the video.</p>
      {note && <p className="note small pull-error">{note}</p>}
    </section>
  );
}
