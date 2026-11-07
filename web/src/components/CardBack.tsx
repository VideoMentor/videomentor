import { useEffect, useState } from 'react';
import { AuthError, api, isNetworkError } from '../lib/api';
import { excerpt, formatMinutes, normalizeAnalysis, relativeTime, sourceLabel } from '../lib/format';
import type { Card, ItemDetail } from '../lib/types';
import { TagChips } from './InfoSheet';

// Details fetched for card backs this session, so flipping again is instant.
const cache = new Map<string, ItemDetail>();

const STATUS_NOTE: Record<string, string> = {
  none: 'Not analyzed yet. Swipe down to analyze it first.',
  queued: 'Waiting for analysis.',
  running: 'Being analyzed now.',
  failed: 'Analysis failed. It will retry.',
};

export function CardBack({ card, active }: { card: Card; active: boolean }) {
  const [detail, setDetail] = useState<ItemDetail | null>(() => cache.get(card.id) ?? null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!active || detail) return;
    const ctl = new AbortController();
    setError(null);
    api
      .item(card.id, ctl.signal)
      .then((d) => {
        cache.set(card.id, d);
        setDetail(d);
      })
      .catch((err) => {
        if (ctl.signal.aborted || err instanceof AuthError) return;
        setError(isNetworkError(err) ? 'Offline. Details load when you have signal.' : 'Couldn’t load details.');
      });
    return () => ctl.abort();
  }, [active, detail, card.id]);

  const d: Card & Partial<ItemDetail> = detail ? { ...card, ...detail } : card;
  const tags = Array.isArray(d.tags) && d.tags.length ? d.tags : (card.tags ?? []);
  const sources = Array.isArray(d.sources) ? d.sources : card.sources;
  const analysis = d.analysis_status === 'done' ? normalizeAnalysis(d.analysis) : null;
  const desc = excerpt(d.description, 260);

  return (
    <div className="body back">
      <h3 className="title">{d.title}</h3>
      <div className="meta">
        {[d.channel, formatMinutes(d.duration_s), d.added_at && `saved ${relativeTime(d.added_at)}`].filter(Boolean).join(' · ')}
      </div>

      {analysis && (analysis.summary || analysis.key_points.length > 0) ? (
        <>
          <h4>Summary</h4>
          {analysis.summary && <p className="clamp-3">{analysis.summary}</p>}
          {analysis.try_this_week.length > 0 ? (
            <>
              <h4>Try this week</h4>
              <ul>
                {analysis.try_this_week.slice(0, 2).map((k, i) => (
                  <li key={i}>{k}</li>
                ))}
              </ul>
            </>
          ) : (
            analysis.key_points.length > 0 && (
              <ul>
                {analysis.key_points.slice(0, 3).map((k, i) => (
                  <li key={i}>{k}</li>
                ))}
              </ul>
            )
          )}
          {analysis.skills.length > 0 && <div className="meta">Builds: {analysis.skills.join(' · ')}</div>}
        </>
      ) : (
        <>
          {d.summary_short && <p className="clamp-3">{d.summary_short}</p>}
          <p className="note">{STATUS_NOTE[d.analysis_status] ?? ''}</p>
        </>
      )}

      {!analysis && desc && (
        <>
          <h4>Description</h4>
          <p className="clamp-4">{desc}</p>
        </>
      )}

      {tags.length > 0 && (
        <>
          <h4>Tags</h4>
          <TagChips tags={tags} />
        </>
      )}

      {sources.length > 0 && (
        <>
          <h4>Saved from</h4>
          <div className="meta">{(d.saved_in_labels?.length ? d.saved_in_labels : sources.map(sourceLabel)).join(' · ')}</div>
        </>
      )}

      {!detail && !error && active && <p className="note">Loading details…</p>}
      {error && <p className="note">{error}</p>}
      <div className="hint">Tap to flip back · hold to open on YouTube</div>
    </div>
  );
}
