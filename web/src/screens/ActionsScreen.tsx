// Actions: every "try this week" step from your kept videos, as one checklist.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AuthError, api, isNetworkError } from '../lib/api';
import { groupByVideo } from '../lib/actionsView';
import { sendActionUpdate, type ActionPatch } from '../lib/actionQueue';
import { formatDuration, momentUrl, normalizeCard, relativeTime, thumbnailOf } from '../lib/format';
import type { ActionCounts, ActionItem, ActionStatus } from '../lib/types';
import { useInfo } from '../state/info';

export function ActionsScreen({ online }: { online: boolean }) {
  const [status, setStatus] = useState<ActionStatus>('open');
  const [rows, setRows] = useState<ActionItem[] | null>(null);
  const [counts, setCounts] = useState<ActionCounts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [queuedNote, setQueuedNote] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState('');
  const { open } = useInfo();

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const r = await api.actions(status, signal);
        setRows(r.actions);
        setCounts(r.counts);
        setError(null);
      } catch (err) {
        if (signal?.aborted || err instanceof AuthError) return;
        setError(isNetworkError(err) ? 'Actions need a connection.' : (err as Error).message);
      }
    },
    [status],
  );

  useEffect(() => {
    const ctl = new AbortController();
    setRows(null);
    void load(ctl.signal);
    return () => ctl.abort();
  }, [load, online]);

  const groups = useMemo(() => groupByVideo(rows ?? []), [rows]);

  const set = async (a: ActionItem, next: ActionStatus) => {
    // Optimistic: the row leaves this list right away.
    setRows((rs) => rs?.filter((r) => r.id !== a.id) ?? rs);
    setCounts((c) =>
      c
        ? {
            ...c,
            [a.status]: Math.max(0, c[a.status] - 1),
            [next]: c[next] + 1,
            done_this_week: c.done_this_week + (next === 'done' ? 1 : a.status === 'done' ? -1 : 0),
          }
        : c,
    );
    await change(a.id, { status: next });
  };

  // Offline, the change stays on screen and is saved to sync later with the swipes.
  const change = async (id: number, patch: ActionPatch) => {
    try {
      if ((await sendActionUpdate(id, patch)) === 'queued') setQueuedNote(true);
    } catch {
      void load();
    }
  };

  const saveNote = async (a: ActionItem) => {
    setEditing(null);
    setRows((rs) => rs?.map((r) => (r.id === a.id ? { ...r, note: draft.trim() || null } : r)) ?? rs);
    await change(a.id, { note: draft });
  };

  return (
    <section className="page" aria-label="Actions">
      <header className="page-head">
        <h1>Actions</h1>
        {counts && counts.done_this_week > 0 && <span className="muted small">{counts.done_this_week} done this week</span>}
      </header>
      {queuedNote && <p className="note small actions-queued">Saved on this device; it syncs when your Mac is reachable.</p>}
      <div className="lib-controls">
        <div className="segmented" role="tablist" aria-label="Which actions">
          {(
            [
              ['open', `Open${counts ? ` · ${counts.open}` : ''}`],
              ['done', `Done${counts ? ` · ${counts.done}` : ''}`],
              ['skipped', 'Skipped'],
            ] as const
          ).map(([k, label]) => (
            <button key={k} role="tab" aria-selected={status === k} className={status === k ? 'on' : ''} onClick={() => setStatus(k)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="scroll page-body">
        {error && <p className="note">{error}</p>}
        {!rows && !error && <p className="note">Loading…</p>}
        {rows && rows.length === 0 && (
          <p className="note">
            {status === 'open'
              ? 'Nothing to try right now. Keep videos; their analyses add steps here.'
              : status === 'done'
                ? 'Nothing done yet. Tap a circle when you’ve tried something.'
                : 'Nothing skipped.'}
          </p>
        )}
        <div className="action-groups">
          {groups.map((g) => {
            const c = g.actions[0].item ? normalizeCard(g.actions[0].item) : null;
            return (
              <section key={g.itemId} className="action-group">
                {c && (
                  <button className="action-video" onClick={() => open({ kind: 'video', card: c })}>
                    <img src={thumbnailOf(c)} alt="" loading="lazy" />
                    <span>
                      <b>{c.title}</b>
                      <small>{c.channel}</small>
                    </span>
                  </button>
                )}
                {c?.key_moment && (
                  <a className="action-jump" href={momentUrl(c.url, c.key_moment.t)} target="_blank" rel="noopener noreferrer">
                    ▶ Key idea at {formatDuration(c.key_moment.t) || '0:00'}
                  </a>
                )}
                <ul className="action-list">
                  {g.actions.map((a) => (
                    <li key={a.id} className={`action-row ${a.status}`}>
                      <button
                        className="action-check"
                        aria-label={a.status === 'done' ? `Mark not done: ${a.text}` : `Mark done: ${a.text}`}
                        onClick={() => void set(a, a.status === 'done' ? 'open' : 'done')}
                      >
                        {a.status === 'done' ? '✓' : ''}
                      </button>
                      <div className="action-body">
                        <p>{a.text}</p>
                        {editing === a.id ? (
                          <div className="action-note-edit">
                            <textarea
                              rows={2}
                              value={draft}
                              placeholder="What happened when you tried it?"
                              onChange={(e) => setDraft(e.target.value)}
                              autoFocus
                            />
                            <button className="secondary" onClick={() => void saveNote(a)}>
                              Save note
                            </button>
                          </div>
                        ) : (
                          a.note && <p className="action-note">“{a.note}”</p>
                        )}
                        <div className="action-meta">
                          {a.done_at && <span className="muted small">{a.status === 'done' ? 'done' : 'skipped'} {relativeTime(a.done_at)}</span>}
                          <button
                            className="link-btn small"
                            onClick={() => {
                              setEditing(a.id);
                              setDraft(a.note ?? '');
                            }}
                          >
                            {a.note ? 'Edit note' : 'Add note'}
                          </button>
                          {a.status === 'open' && (
                            <button className="link-btn small" onClick={() => void set(a, 'skipped')}>
                              Skip
                            </button>
                          )}
                          {a.status === 'skipped' && (
                            <button className="link-btn small" onClick={() => void set(a, 'open')}>
                              Bring back
                            </button>
                          )}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      </div>
    </section>
  );
}
