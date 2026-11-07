// Review the tag merge list: tick the merges to apply, untick to skip. Applied
// merges can be undone.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AuthError, api, isNetworkError } from '../lib/api';
import type { TagMerge } from '../lib/types';

export function TidyTagsScreen({ onBack, online }: { onBack(): void; online: boolean }) {
  const [merges, setMerges] = useState<TagMerge[] | null>(null);
  const [skip, setSkip] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.tagMerges();
      setMerges(r.merges);
    } catch (err) {
      if (!(err instanceof AuthError)) setError(isNetworkError(err) ? 'This needs a connection.' : (err as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const proposed = useMemo(() => (merges ?? []).filter((m) => m.status === 'proposed'), [merges]);
  const applied = useMemo(() => (merges ?? []).filter((m) => m.status === 'applied'), [merges]);
  const chosen = proposed.filter((m) => !skip.has(m.id));

  const toggle = (id: number) =>
    setSkip((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const apply = async () => {
    setBusy(true);
    setNote(null);
    try {
      const r = await api.applyTagMerges(
        chosen.map((m) => m.id),
        proposed.filter((m) => skip.has(m.id)).map((m) => m.id),
      );
      setNote(`Merged ${r.applied} and skipped ${r.rejected}. ${r.videos} videos now use the tidier tags.`);
      setSkip(new Set());
      await load();
    } catch (err) {
      setNote(isNetworkError(err) ? 'Offline. Try again with signal.' : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const undo = async (m: TagMerge) => {
    setBusy(true);
    try {
      await api.undoTagMerge(m.id);
      setNote(`Undid “${m.keep}”. Its videos have their old tags back.`);
      await load();
    } catch (err) {
      setNote((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="page" aria-label="Tidy tags">
      <header className="page-head">
        <button className="link-btn" onClick={onBack}>
          ‹ Status
        </button>
        <span className="muted small">Tidy tags</span>
      </header>
      <div className="scroll page-body">
        {error && <p className="note">{error}</p>}
        {!merges && !error && <p className="note">Loading…</p>}
        {note && (
          <p className="api-banner" role="status">
            {note}
          </p>
        )}
        {merges && proposed.length === 0 && (
          <p className="note">No merges waiting. New ones are drafted on the Mac with vm tags --draft.</p>
        )}
        {proposed.length > 0 && (
          <>
            <p className="note">
              Each merge keeps the tag on the left and folds the others into it. Untick any you disagree with; they're
              skipped. Every merge can be undone.
            </p>
            <div className="merge-bar">
              <button className="link-btn small" onClick={() => setSkip(new Set())}>
                Tick all
              </button>
              <button className="link-btn small" onClick={() => setSkip(new Set(proposed.map((m) => m.id)))}>
                Untick all
              </button>
            </div>
            <ul className="merge-list">
              {proposed.map((m) => (
                <li key={m.id}>
                  <label className="merge-row">
                    <input type="checkbox" checked={!skip.has(m.id)} onChange={() => toggle(m.id)} />
                    <span>
                      <b>{m.keep}</b> <span className="muted">←</span> {m.fold.join(', ')}
                      <small>
                        {m.videos} video{m.videos === 1 ? '' : 's'}
                        {m.reason ? ` · ${m.reason}` : ''}
                      </small>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
            <button className="primary merge-apply" onClick={() => void apply()} disabled={busy || !online}>
              {busy ? 'Applying…' : `Apply ${chosen.length} merge${chosen.length === 1 ? '' : 's'}`}
            </button>
          </>
        )}
        {applied.length > 0 && (
          <>
            <h4 className="merge-h">Applied</h4>
            <ul className="merge-list">
              {applied.map((m) => (
                <li key={m.id} className="merge-row done">
                  <span>
                    <b>{m.keep}</b> <span className="muted">←</span> {m.fold.join(', ')}
                  </span>
                  <button className="link-btn small" onClick={() => void undo(m)} disabled={busy || !online}>
                    Undo
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}
