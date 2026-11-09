// Insights: reports by skill, the path from saved to analyzed, keep rates, sources,
// processing time and token use. Plain CSS bars; readable on a phone.
import { useEffect, useState } from 'react';
import { AuthError, api, isNetworkError } from '../lib/api';
import { compactNumber, formatMinutes, sourceLabel } from '../lib/format';
import { formatCost, formatHours, fraction, keepRateRows, percent, tokenTotal } from '../lib/insightsView';
import type { Insights, UsageTotals } from '../lib/types';
import type { Tab } from '../components/TabBar';
import { navigate, openTag } from '../state/nav';
import { backLabel } from './TagsScreen';

export const COST_NOTE =
  "API key calls are billed to your Anthropic account at this cost. Claude Code calls show the API-equivalent cost; they count toward your Claude plan's usage limits.";
const BACKEND_LABELS: Record<string, string> = { api: 'API key (billed)', claude_code: 'Claude Code (plan)' };

const num = (n: number | null | undefined) => (n ?? 0).toLocaleString();
const minutes = (m: number | null | undefined) => formatMinutes((m ?? 0) * 60);
const words = (s: string) => {
  const t = s.replace(/[_-]+/g, ' ').trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
};

function day(iso: string): string {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? iso : new Date(t).toLocaleDateString(undefined, { dateStyle: 'medium' });
}

function Bar({ value, tone }: { value: number; tone?: 'keep' | 'muted' }) {
  return (
    <span className={`ins-bar${tone ? ` ${tone}` : ''}`} aria-hidden="true">
      <span style={{ width: `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%` }} />
    </span>
  );
}

export function InsightsScreen({ online, backTab }: { online: boolean; backTab: Tab }) {
  const [data, setData] = useState<Insights | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctl = new AbortController();
    api
      .insights(ctl.signal)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((err) => {
        if (ctl.signal.aborted || err instanceof AuthError) return;
        setError(isNetworkError(err) ? 'Insights need a connection the first time.' : (err as Error).message);
      });
    return () => ctl.abort();
  }, [online]);

  return (
    <section className="page" aria-label="Insights">
      <header className="page-head">
        <button className="link-btn" onClick={() => navigate(backTab)}>
          {backLabel(backTab)}
        </button>
        <h1>Insights</h1>
        <span />
      </header>
      <div className="scroll page-body">
        {error && <p className="note">{error}</p>}
        {!data && !error && <p className="note">Loading…</p>}
        {data && (
          <div className="ins-grid">
            <Skills data={data} />
            <Funnel data={data} />
            <KeepRates data={data} />
            <Sources data={data} />
            <Latency data={data} />
            <Usage data={data} />
            <InboxByTag data={data} />
          </div>
        )}
      </div>
    </section>
  );
}

function Skills({ data }: { data: Insights }) {
  const skills = data.skills ?? [];
  const max = Math.max(1, ...skills.map((s) => s.kept ?? 0));
  return (
    <div className="card-block ins-card">
      <h4>Skills</h4>
      {skills.length === 0 && <p className="note">No skills yet. They come from the analysis of kept videos.</p>}
      <ul className="ins-list">
        {skills.map((s) => {
          const actions = (s.actions_open ?? 0) + (s.actions_done ?? 0);
          return (
            <li key={s.skill}>
              <div className="ins-line">
                <b>{s.skill}</b>
                <span>{num(s.kept)} kept</span>
              </div>
              <Bar value={(s.kept ?? 0) / max} />
              <small className="muted">
                {[
                  `${num(s.analyzed)} analyzed`,
                  s.avg_signal ? `signal ${s.avg_signal.toFixed(1)}` : '',
                  minutes(s.minutes),
                  actions ? `${num(s.actions_done)} of ${num(actions)} actions done` : '',
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </small>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Funnel({ data }: { data: Insights }) {
  const f = data.funnel;
  if (!f) return null;
  const decided = (f.kept ?? 0) + (f.archived ?? 0);
  const saved = decided + (f.inbox ?? 0);
  const steps: [string, number][] = [
    ['Saved', saved],
    ['Decided', decided],
    ['Kept', f.kept ?? 0],
    ['Analyzed', f.analyzed ?? 0],
  ];
  return (
    <div className="card-block ins-card">
      <h4>From saved to notes</h4>
      <ul className="ins-list">
        {steps.map(([label, n]) => (
          <li key={label}>
            <div className="ins-line">
              <b>{label}</b>
              <span>
                {num(n)}
                {saved && label !== 'Saved' ? <span className="muted"> · {percent(n / saved)}</span> : null}
              </span>
            </div>
            <Bar value={saved ? n / saved : 0} />
          </li>
        ))}
      </ul>
      <dl className="counts">
        <div>
          <dt>Still in the deck</dt>
          <dd>{num(f.inbox)}</dd>
        </div>
        <div>
          <dt>Analysis failed</dt>
          <dd>{num(f.analysis_failed)}</dd>
        </div>
        <div>
          <dt>Decisions, last 7 days</dt>
          <dd>{num(f.decisions_7d)}</dd>
        </div>
        <div>
          <dt>Undo rate</dt>
          <dd>{percent(f.undo_rate) || '0%'}</dd>
        </div>
      </dl>
    </div>
  );
}

function KeepRates({ data }: { data: Insights }) {
  const rows = keepRateRows(data.signal_keep, data.signal_keep_clean);
  return (
    <div className="card-block ins-card">
      <h4>Keep rate by signal</h4>
      <p className="note small">
        Raw is inflated because kept videos are rescored after their notes; clean uses the signal at the time you decided.
      </p>
      {(data.signal_keep_clean ?? []).length === 0 && rows.length > 0 && <p className="note small">Clean figures: builds up as you swipe.</p>}
      {rows.length === 0 ? (
        <p className="note">No decisions yet.</p>
      ) : (
        <table className="ins-table">
          <thead>
            <tr>
              <th scope="col">Signal</th>
              <th scope="col">Raw</th>
              <th scope="col">Clean</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.signal}>
                <th scope="row">{r.signal}</th>
                <td>
                  <span className="ins-cell">
                    <b>{percent(r.raw) || '–'}</b>
                    <Bar value={fraction(r.raw)} tone="muted" />
                    <small className="muted">{r.rawN ? `of ${num(r.rawN)}` : ''}</small>
                  </span>
                </td>
                <td>
                  <span className="ins-cell">
                    <b>{percent(r.clean) || '–'}</b>
                    <Bar value={fraction(r.clean)} tone="keep" />
                    <small className="muted">{r.cleanN ? `of ${num(r.cleanN)}` : 'Builds up as you swipe'}</small>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Sources({ data }: { data: Insights }) {
  const sources = data.sources ?? [];
  return (
    <div className="card-block ins-card">
      <h4>Sources</h4>
      {sources.length === 0 && <p className="note">No decisions yet.</p>}
      <ul className="ins-list">
        {sources.map((s) => (
          <li key={s.source}>
            <div className="ins-line">
              <b>{s.label || sourceLabel(s.source)}</b>
              <span>{percent(s.rate) || '–'} kept</span>
            </div>
            <Bar value={fraction(s.rate)} tone="keep" />
            <small className="muted">
              {num(s.kept)} kept · {num(s.archived)} archived
            </small>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Latency({ data }: { data: Insights }) {
  const l = data.latency ?? { queue_to_notes_h: null, save_to_notes_h: null };
  return (
    <div className="card-block ins-card">
      <h4>Processing time</h4>
      <dl className="counts">
        <div>
          <dt>Keep to notes</dt>
          <dd>{formatHours(l.queue_to_notes_h)}</dd>
        </div>
        <div>
          <dt>Save to notes</dt>
          <dd>{formatHours(l.save_to_notes_h)}</dd>
        </div>
      </dl>
      <p className="muted small">Medians. Keep to notes starts when a video joins the analysis queue.</p>
    </div>
  );
}

function UsageCell({ label, u }: { label: string; u: UsageTotals | undefined }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{formatCost(u?.cost_usd)}</dd>
      <small className="muted">
        {compactNumber(tokenTotal(u)) || '0'} tokens · {num(u?.calls)} calls
      </small>
    </div>
  );
}

function Usage({ data }: { data: Insights }) {
  const u = data.usage;
  const steps = u?.by_step ?? [];
  const none = !u || (steps.length === 0 && (!u.since || (u.total?.calls ?? 0) === 0));
  return (
    <div className="card-block ins-card">
      <h4>Token use</h4>
      <p className="note small">{none ? 'No calls recorded yet' : u.since ? `Tracking started ${day(u.since)}` : 'Tracking started recently'}</p>
      {!none && (
        <>
          <dl className="counts ins-usage">
            <UsageCell label="All time" u={u.total} />
            <UsageCell label="Last 7 days" u={u.last_7d} />
            {(u.by_backend ?? []).map((b) => (
              <UsageCell key={b.backend} label={BACKEND_LABELS[b.backend] ?? b.backend} u={b} />
            ))}
          </dl>
          {steps.length > 0 && (
            <table className="ins-table">
              <thead>
                <tr>
                  <th scope="col">Step</th>
                  <th scope="col">Calls</th>
                  <th scope="col">Tokens</th>
                  <th scope="col">Cost</th>
                </tr>
              </thead>
              <tbody>
                {steps.map((s) => (
                  <tr key={s.step}>
                    <th scope="row">{words(s.step)}</th>
                    <td>
                      {num(s.calls)}
                      {s.failed ? <small className="muted"> ({num(s.failed)} failed)</small> : null}
                    </td>
                    <td>
                      {compactNumber(tokenTotal(s)) || '0'}
                      <small className="muted ins-sub">
                        in {compactNumber(s.input_tokens ?? 0)} · out {compactNumber(s.output_tokens ?? 0)}
                      </small>
                    </td>
                    <td>{formatCost(s.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
      <p className="muted small">{COST_NOTE}</p>
    </div>
  );
}

function InboxByTag({ data }: { data: Insights }) {
  const tags = data.inbox_by_tag ?? [];
  const max = Math.max(1, ...tags.map((t) => t.inbox ?? 0));
  return (
    <div className="card-block ins-card">
      <h4>Inbox by tag</h4>
      {tags.length === 0 && <p className="note">The deck is empty.</p>}
      <ul className="ins-list">
        {tags.map((t) => (
          <li key={t.tag}>
            <button className="ins-link" onClick={() => openTag({ tag: t.tag, status: 'inbox', from: 'insights' })}>
              <span className="ins-line">
                <b>{t.tag}</b>
                <span>
                  {num(t.inbox)}
                  {t.avg_signal ? <span className="muted"> · signal {t.avg_signal.toFixed(1)}</span> : null}
                  <span aria-hidden="true"> ›</span>
                </span>
              </span>
              <Bar value={(t.inbox ?? 0) / max} />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
