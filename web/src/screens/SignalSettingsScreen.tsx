// What the signal score rewards, and the skill map analyses use. Saved on the Mac;
// "Rescore cards" re-runs the quick scores with the new rules.
import { useEffect, useState } from 'react';
import { AuthError, api, isNetworkError } from '../lib/api';
import type { SignalSettings } from '../lib/types';

function ListEditor({ label, items, onChange, placeholder }: { label: string; items: string[]; onChange(v: string[]): void; placeholder: string }) {
  const [draft, setDraft] = useState('');
  const add = () => {
    const v = draft.trim();
    if (v && !items.some((x) => x.toLowerCase() === v.toLowerCase())) onChange([...items, v]);
    setDraft('');
  };
  return (
    <div className="list-editor">
      <h4>{label}</h4>
      <div className="chips">
        {items.map((x) => (
          <span key={x} className="chip edit-chip">
            {x}
            <button aria-label={`Remove ${x}`} onClick={() => onChange(items.filter((i) => i !== x))}>
              ×
            </button>
          </span>
        ))}
      </div>
      <div className="list-add">
        <input
          value={draft}
          placeholder={placeholder}
          aria-label={`Add to ${label}`}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              add();
            }
          }}
        />
        <button className="secondary" onClick={add} disabled={!draft.trim()}>
          Add
        </button>
      </div>
    </div>
  );
}

export function SignalSettingsScreen({ onBack, online }: { onBack(): void; online: boolean }) {
  const [s, setS] = useState<SignalSettings | null>(null);
  const [saved, setSaved] = useState<SignalSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctl = new AbortController();
    api
      .settings(ctl.signal)
      .then((r) => {
        setS(r);
        setSaved(r);
      })
      .catch((err) => {
        if (!ctl.signal.aborted && !(err instanceof AuthError)) setError(isNetworkError(err) ? 'Settings need a connection.' : (err as Error).message);
      });
    return () => ctl.abort();
  }, []);

  const dirty = !!s && !!saved && JSON.stringify(s) !== JSON.stringify(saved);

  const save = async () => {
    if (!s) return;
    setBusy(true);
    setNote(null);
    try {
      const r = await api.saveSettings(s);
      setS(r);
      setSaved(r);
      setNote('Saved. New scores and analyses use these rules. Tap Rescore cards to update the cards you have now.');
    } catch (err) {
      setNote(isNetworkError(err) ? 'Offline. Try again with signal.' : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const rescore = async () => {
    setBusy(true);
    try {
      const r = await api.rescore();
      setNote(`Rescoring ${r.queued} cards in the background. It takes a few minutes; analyzed videos keep their scores until they're re-analyzed.`);
    } catch (err) {
      setNote((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="page" aria-label="Signal settings">
      <header className="page-head">
        <button className="link-btn" onClick={onBack}>
          ‹ Status
        </button>
        <span className="muted small">Signal settings</span>
      </header>
      <div className="scroll page-body settings-body">
        {error && <p className="note">{error}</p>}
        {!s && !error && <p className="note">Loading…</p>}
        {note && (
          <p className="api-banner" role="status">
            {note}
          </p>
        )}
        {s && (
          <>
            <p className="note">
              The signal (1 to 5) on each card says how many clear learnings a video holds that you could apply. These
              rules guide both the quick score and the full analysis.
            </p>
            <div className="list-editor">
              <h4>What a high signal means</h4>
              <textarea
                id="signal-guidance"
                rows={5}
                value={s.signal_guidance}
                onChange={(e) => setS({ ...s, signal_guidance: e.target.value })}
              />
            </div>
            <ListEditor
              label="Areas of life that count"
              items={s.signal_areas}
              onChange={(v) => setS({ ...s, signal_areas: v })}
              placeholder="Add an area, e.g. Parenting"
            />
            <ListEditor
              label="Skill map (skills analyses tag)"
              items={s.skill_map}
              onChange={(v) => setS({ ...s, skill_map: v })}
              placeholder="Add a skill, e.g. Hiring"
            />
            <div className="settings-actions">
              <button className="primary" onClick={() => void save()} disabled={!dirty || busy || !online}>
                {busy ? 'Saving…' : 'Save'}
              </button>
              <button className="secondary" onClick={() => void rescore()} disabled={dirty || busy || !online}>
                Rescore cards
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
