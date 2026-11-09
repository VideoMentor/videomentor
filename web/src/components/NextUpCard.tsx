// Home's "Next up": one practical suggestion. Watch next is the best video in the deck;
// Apply next is an open step from a kept video, with Done and Skip. Status picks which.
import { useCallback, useEffect, useState } from 'react';
import { AuthError, api, isNetworkError } from '../lib/api';
import { pendingActionUpdates, sendActionUpdate } from '../lib/actionQueue';
import { formatMinutes, normalizeCard, thumbnailOf } from '../lib/format';
import { cardFromId } from '../lib/tagView';
import type { ActionStatus, NextUpResponse } from '../lib/types';
import { useInfo } from '../state/info';
import { readNextUpMode, readNextUpSkill, saveNextUpSkill } from '../state/nextUp';

function isPending(r: NextUpResponse | null | undefined): boolean {
  if (!r || r.mode !== 'apply' || !r.action) return false;
  const id = r.action.id;
  return pendingActionUpdates().some((p) => p.id === id);
}

type ApplyAction = Extract<NextUpResponse, { mode: 'apply' }>['action'];

export function NextUpCard({ online }: { online: boolean }) {
  const [mode] = useState(readNextUpMode);
  const [skill, setSkill] = useState(readNextUpSkill);
  const [skills, setSkills] = useState<string[]>([]);
  const [data, setData] = useState<NextUpResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const info = useInfo();

  // The 9 skills, for the picker. Insights is saved for offline use, so this usually answers.
  useEffect(() => {
    const ctl = new AbortController();
    api
      .insights(ctl.signal)
      .then((d) => setSkills((d?.skills ?? []).map((s) => s.skill).filter(Boolean)))
      .catch(() => {});
    return () => ctl.abort();
  }, []);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setError(null);
      try {
        let r = await api.nextUp(mode, skill || undefined, signal);
        // Back online, the queued Done or Skip may not have synced yet: wait for it, briefly.
        for (let tries = 0; tries < 3 && isPending(r); tries++) {
          await new Promise((ok) => setTimeout(ok, 1500));
          if (signal?.aborted) return;
          r = await api.nextUp(mode, skill || undefined, signal);
        }
        if (isPending(r)) r = { mode: 'apply', action: null };
        setData(r ?? null);
      } catch (err) {
        if (signal?.aborted || err instanceof AuthError) return;
        setData(null);
        setError(isNetworkError(err) ? 'Next up shows when your Mac is reachable.' : (err as Error).message);
      }
    },
    [mode, skill],
  );

  useEffect(() => {
    if (!online) {
      setError('Next up shows when your Mac is reachable.');
      return;
    }
    const ctl = new AbortController();
    void load(ctl.signal);
    return () => ctl.abort();
  }, [load, online]);

  // Done and Skip go the same way as on the Actions screen, offline queue included.
  const finish = async (action: NonNullable<ApplyAction>, status: ActionStatus) => {
    setBusy(true);
    setNote(null);
    try {
      const how = await sendActionUpdate(action.id, { status });
      if (how === 'queued') {
        setNote('Saved on this device; it syncs when your Mac is reachable.');
        setData({ mode: 'apply', action: null });
      } else {
        setNote(status === 'done' ? 'Nice. Here is the next one.' : 'Skipped. Here is the next one.');
        await load();
      }
    } catch (err) {
      setNote((err as Error).message);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const pickSkill = (v: string) => {
    setSkill(v);
    saveNextUpSkill(v);
    setNote(null);
  };

  const options = skill && !skills.includes(skill) ? [skill, ...skills] : skills;

  return (
    <section className={`next-up ${mode}`} aria-label="Next up">
      <div className="next-up-head">
        <span className="tile-kicker">{mode === 'watch' ? 'Watch next' : 'Apply next'}</span>
        {options.length > 0 && (
          <label className="lib-select">
            <select value={skill} onChange={(e) => pickSkill(e.target.value)} aria-label="Skill to focus on">
              <option value="">Any skill</option>
              {options.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {error && <p className="note">{error}</p>}
      {!error && !data && <p className="note">Loading…</p>}

      {data?.mode === 'watch' &&
        (data.item ? (
          (() => {
            const c = normalizeCard(data.item);
            return (
              <button className="next-up-video" onClick={() => info.open({ kind: 'video', card: c })}>
                <img src={thumbnailOf(c)} alt="" loading="lazy" />
                <span>
                  <b>{c.title}</b>
                  <small>{[c.channel, formatMinutes(c.duration_s), c.signal ? `signal ${c.signal}/5` : ''].filter(Boolean).join(' · ')}</small>
                </span>
              </button>
            );
          })()
        ) : (
          <p className="note">{skill ? `Nothing in the deck for ${skill}. Try Any skill.` : 'Nothing waiting in the deck.'}</p>
        ))}

      {data?.mode === 'apply' &&
        (data.action ? (
          <div className="next-up-action">
            <p className="next-up-text">{data.action.text}</p>
            <button
              className="inline-link next-up-from"
              onClick={() =>
                info.open({
                  kind: 'video',
                  card: data.action?.item
                    ? normalizeCard(data.action.item)
                    : cardFromId(data.action!.item_id, data.action!.item_title, { analysis_status: 'done' }),
                })
              }
            >
              From: {data.action.item_title}
            </button>
            <div className="next-up-buttons">
              <button className="primary" disabled={busy} onClick={() => void finish(data.action!, 'done')}>
                Done
              </button>
              <button className="secondary" disabled={busy} onClick={() => void finish(data.action!, 'skipped')}>
                Skip
              </button>
            </div>
          </div>
        ) : (
          !note && <p className="note">{skill ? `No open steps for ${skill}. Try Any skill.` : 'No open steps. Keep videos to get new ones.'}</p>
        ))}

      {note && <p className="note small">{note}</p>}
    </section>
  );
}
