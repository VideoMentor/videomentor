// Full analysis view used by the Ready and Library tabs.
import { useEffect, useState } from 'react';
import { AuthError, api, isNetworkError } from '../lib/api';
import {
  byline,
  excerpt,
  formatDuration,
  formatMinutes,
  momentUrl,
  normalizeAnalysis,
  relativeTime,
  sourceLabel,
  thumbnailOf,
} from '../lib/format';
import type { Card, ItemDetail } from '../lib/types';
import { TagChips } from './InfoSheet';
import { useInfo } from '../state/info';

interface Props {
  card: Card;
  onBack?(): void;
  /** In a side pane: no Back button. */
  embedded?: boolean;
}

export function ItemDetailView({ card, onBack, embedded = false }: Props) {
  const [detail, setDetail] = useState<ItemDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctl = new AbortController();
    api
      .item(card.id, ctl.signal)
      .then(setDetail)
      .catch((err) => {
        if (ctl.signal.aborted || err instanceof AuthError) return;
        setError(isNetworkError(err) ? 'You’re offline. The analysis loads when you have signal.' : (err as Error).message);
      });
    return () => ctl.abort();
  }, [card.id]);

  const d: Card & Partial<ItemDetail> = detail ? { ...card, ...detail } : card;
  const a = normalizeAnalysis(d.analysis);
  const sources = Array.isArray(d.sources) ? d.sources : [];
  const { posted, by } = byline(d);
  const { open } = useInfo();

  return (
    <div className={`detail${embedded ? ' embedded' : ''}`}>
      <div className="detail-bar">
        {embedded || !onBack ? (
          <span className="muted small">Details</span>
        ) : (
          <button className="link-btn" onClick={onBack} aria-label="Back to list">
            ‹ Back
          </button>
        )}
        <a className="pill-btn" href={d.url} target="_blank" rel="noopener noreferrer">
          Open on YouTube
        </a>
      </div>
      <div className="scroll detail-body">
        <a className="detail-thumb" href={d.url} target="_blank" rel="noopener noreferrer" aria-label="Play on YouTube">
          <img src={thumbnailOf(d)} alt="" />
          {formatDuration(d.duration_s) && <span className="dur">{formatDuration(d.duration_s)}</span>}
        </a>
        <h2>{d.title}</h2>
        {(posted || by) && (
          <div className="byline">
            {posted && (
              <span>
                <span className="byline-label">Posted</span> {posted}
              </span>
            )}
            {by && (
              <span>
                <span className="byline-label">by</span> <b>{by}</b>
              </span>
            )}
            <button className="info-btn inline" aria-label="Video info" onClick={() => open({ kind: 'video', card: d })}>
              i
            </button>
          </div>
        )}
        <div className="meta">
          {[formatMinutes(d.duration_s), d.added_at && `saved ${relativeTime(d.added_at)}`].filter(Boolean).join(' · ')}
        </div>

        {error && <p className="note">{error}</p>}
        {!detail && !error && <p className="note">Loading…</p>}

        {detail && !a && (
          <p className="note">
            {d.analysis_status === 'done' ? 'The analysis is empty.' : `Analysis: ${d.analysis_status ?? 'none'}.`}
          </p>
        )}

        {a && (
          <>
            {a.core_idea && (
              <div className="why">
                <span>Core idea</span>
                {a.core_idea}
              </div>
            )}
            {(a.skills.length > 0 || a.useful_for || d.signal) && (
              <p className="meta">
                {[
                  d.signal ? `Signal ${d.signal}/5${d.signal_reason ? `: ${d.signal_reason}` : ''}` : '',
                  a.skills.length ? `Builds ${a.skills.join(', ')}` : '',
                  a.useful_for ? `For ${a.useful_for}` : '',
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
            )}
            {a.key_moment && (
              <a
                className="chip key-jump"
                href={momentUrl(d.url, a.key_moment.seconds)}
                target="_blank"
                rel="noopener noreferrer"
              >
                ▶ Key idea at {formatDuration(a.key_moment.seconds) || '0:00'}: {a.key_moment.label}
              </a>
            )}
            {a.try_this_week.length > 0 && (
              <section>
                <h4>Try this week</h4>
                <ul className="todo">
                  {a.try_this_week.map((k, i) => (
                    <li key={i}>{k}</li>
                  ))}
                </ul>
              </section>
            )}
            {a.frameworks.length > 0 && (
              <section>
                <h4>Frameworks</h4>
                <ul>
                  {a.frameworks.map((f, i) => (
                    <li key={i}>
                      <b>{f.name}</b>
                      {f.how ? `: ${f.how}` : ''}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {a.takeaways.length > 0 && (
              <section>
                <h4>Takeaways</h4>
                <ul>
                  {a.takeaways.map((k, i) => (
                    <li key={i}>{k}</li>
                  ))}
                </ul>
              </section>
            )}
            {a.curriculum_topic && (
              <div className="why topic">
                <span>Suggested topic</span>
                {a.curriculum_topic}
              </div>
            )}
            {a.summary && (
              <section>
                <h4>Summary</h4>
                <p>{a.summary}</p>
              </section>
            )}
            {a.key_points.length > 0 && (
              <section>
                <h4>Key points</h4>
                <ul>
                  {a.key_points.map((k, i) => (
                    <li key={i}>{k}</li>
                  ))}
                </ul>
              </section>
            )}
            {a.moments.length > 0 && (
              <section>
                <h4>Jump to</h4>
                <div className="chips moments">
                  {a.moments.map((m, i) => (
                    <a
                      key={i}
                      className="chip"
                      href={momentUrl(d.url, m.seconds)}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      ▶ {formatDuration(m.seconds) || '0:00'} {m.label}
                    </a>
                  ))}
                </div>
              </section>
            )}
            {a.learnings.length > 0 && a.takeaways.length === 0 && (
              <section>
                <h4>Learnings</h4>
                <ul>
                  {a.learnings.map((k, i) => (
                    <li key={i}>{k}</li>
                  ))}
                </ul>
              </section>
            )}
            {a.transcript_source === 'none' && (
              <p className="note">No captions were available, so this is based on the title and description only.</p>
            )}
          </>
        )}

        {d.description && (
          <section>
            <h4>Description</h4>
            <p className="pre">{excerpt(d.description, 1200)}</p>
          </section>
        )}
        {(d.tags?.length ?? 0) > 0 && (
          <section>
            <h4>Tags</h4>
            <TagChips tags={d.tags} />
          </section>
        )}
        {sources.length > 0 && (
          <section>
            <h4>Saved from</h4>
            <div className="meta">{(d.saved_in_labels?.length ? d.saved_in_labels : sources.map(sourceLabel)).join(' · ')}</div>
          </section>
        )}
      </div>
    </div>
  );
}
