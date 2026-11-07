// Home: the launch screen. The logo, a greeting and big shortcuts to what's waiting.
import { useEffect, useState } from 'react';
import { Logo } from '../components/Logo';
import { LAST_LESSON_KEY } from '../components/LessonPlayer';
import type { Tab } from '../components/TabBar';
import { api } from '../lib/api';
import { formatDateTime } from '../lib/format';
import { LOGIN_LOST, loginLost, syncErrors } from '../lib/syncHealth';
import type { StatusResponse } from '../lib/types';
import { navigate } from '../state/nav';
import { START_CHOICES, readStartChoice, saveStartChoice, type StartChoice } from '../state/startScreen';
import { readJSON, writeJSON } from '../state/storage';
import { OPEN_MODULE_KEY } from './TrainScreen';

interface LastLesson {
  id: number;
  title: string;
  step: number;
  steps: number;
  done: boolean;
}

function greeting(d = new Date()): string {
  const h = d.getHours();
  return h < 5 ? 'Up late' : h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
}

const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`;

export function HomeScreen({ status, readyCount, online }: { status: StatusResponse | null; readyCount: number; online: boolean }) {
  const [openActions, setOpenActions] = useState<number | null>(null);
  const [start, setStart] = useState<StartChoice>(readStartChoice);
  const last = readJSON<LastLesson | null>(LAST_LESSON_KEY, null);
  const c = status?.counts ?? {};
  const toTriage = (c.inbox ?? 0) + (c.music_inbox ?? 0);
  const sync = status?.last_sync as { finished_at?: string; started_at?: string } | null | undefined;
  const lost = loginLost(syncErrors(status?.last_sync));

  useEffect(() => {
    if (!online) return;
    const ctl = new AbortController();
    api
      .actions('open', ctl.signal)
      .then((r) => setOpenActions(r.counts.open))
      .catch(() => {});
    return () => ctl.abort();
  }, [online]);

  const go = (tab: Tab) => navigate(tab);
  const continueLesson = () => {
    if (last) writeJSON(OPEN_MODULE_KEY, { id: last.id, play: !last.done });
    navigate('train');
  };

  return (
    <section className="page home" aria-label="Home">
      <div className="scroll page-body home-body">
        <header className="home-hero">
          <Logo size={88} />
          <div>
            <h1 className="home-name">
              Video<span>Mentor</span>
            </h1>
            <p className="home-greeting">{greeting()}. Here's what's waiting.</p>
          </div>
        </header>

        <div className="home-tiles">
          <button className="home-tile tile-deck" onClick={() => go('deck')}>
            <span className="tile-kicker">Swipe</span>
            <b>{status ? plural(toTriage, 'video') : '…'}</b>
            <span>to triage, ten at a time</span>
          </button>
          <button className="home-tile tile-ready" onClick={() => go('ready')}>
            <span className="tile-kicker">Ready to read</span>
            <b>{status ? plural(readyCount, 'video') : '…'}</b>
            <span>with notes you can act on</span>
          </button>
          <button className="home-tile tile-train" onClick={continueLesson}>
            <span className="tile-kicker">{last && !last.done ? 'Continue training' : 'Train'}</span>
            <b>{last ? last.title : 'Build a lesson'}</b>
            <span>
              {last && !last.done && last.steps > 1
                ? `${Math.round((last.step / (last.steps - 1)) * 100)}% through`
                : 'clips from many videos, one lesson'}
            </span>
          </button>
          <button className="home-tile tile-actions" onClick={() => go('actions')}>
            <span className="tile-kicker">Actions</span>
            <b>{openActions === null ? '…' : plural(openActions, 'step')}</b>
            <span>to try this week</span>
          </button>
        </div>

        <button className={`home-sync${lost ? ' warn' : ''}`} onClick={() => go('status')}>
          {lost
            ? LOGIN_LOST
            : `Last sync ${sync?.finished_at || sync?.started_at ? formatDateTime((sync.finished_at || sync.started_at) as string) : 'not yet'}. Tap for Status.`}
        </button>

        <label className="lib-select home-start">
          <span>Open the app on</span>
          <select
            value={start}
            onChange={(e) => {
              const v = e.target.value as StartChoice;
              setStart(v);
              saveStartChoice(v);
            }}
          >
            {START_CHOICES.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>
    </section>
  );
}
