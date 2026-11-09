// Pick which saves the deck draws from.
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import type { DeckSource, NotForLearning, Playlist, PulledChannel } from '../lib/types';
import { navigate } from '../state/nav';
import { sourceList } from '../lib/deck';
import { DEFAULT_ORDER, playlistSource, setOrder, setSource, useDeckOrder, useDeckSource } from '../state/source';
import type { DeckOrder } from '../lib/types';

export function SourceSheet({ onClose }: { onClose(): void }) {
  const current = useDeckSource();
  const order = useDeckOrder();
  const change = (patch: Partial<DeckOrder>) => setOrder({ ...order, ...patch });
  const [lists, setLists] = useState<Playlist[] | null>(null);
  const [error, setError] = useState(false);
  const [pulled, setPulled] = useState<PulledChannel[]>([]);
  const [nl, setNl] = useState<NotForLearning | null>(null);

  useEffect(() => {
    const ctl = new AbortController();
    api
      .playlists(ctl.signal)
      .then((r) => setLists(r.playlists.filter((p) => p.enabled)))
      .catch(() => {
        if (!ctl.signal.aborted) setError(true);
      });
    api
      .pulledChannels(ctl.signal)
      .then((r) => setPulled(r.channels))
      .catch(() => {});
    api
      .notForLearning(ctl.signal)
      .then(setNl)
      .catch(() => {});
    return () => ctl.abort();
  }, []);

  const pick = (s: DeckSource) => {
    setSource(s);
    onClose();
  };

  const option = (s: DeckSource, detail?: string, text = s.label) => (
    <li key={s.key}>
      <button className={`source-opt${current.key === s.key ? ' on' : ''}`} onClick={() => pick(s)}>
        <span>{text}</span>
        {detail && <small>{detail}</small>}
        {current.key === s.key && <span className="check" aria-label="selected">✓</span>}
      </button>
    </li>
  );

  return (
    <div className="info-backdrop" role="presentation" onClick={onClose}>
      <div className="info-sheet" role="dialog" aria-modal="true" aria-label="Deck source" onClick={(e) => e.stopPropagation()}>
        <div className="info-head">
          <span />
          <span className="info-kind">Swipe from</span>
          <button className="link-btn" onClick={onClose}>
            Done
          </button>
        </div>
        <div className="info-body scroll">
          <ul className="source-list">
            {sourceList(nl ? nl.inbox : null).map(({ source, text }) =>
              option(
                source,
                {
                  all: 'Watch Later, bookmarks and playlists that are on',
                  playlists: lists ? `${lists.length} on, newest saves first` : undefined,
                  nl: 'Music and entertainment',
                }[source.key],
                text,
              ),
            )}
          </ul>
          {lists && lists.length > 0 && (
            <>
              <h4>One playlist</h4>
              <ul className="source-list">
                {lists.map((p) => option(playlistSource(p.id, p.title), `${p.inbox} to triage`))}
              </ul>
            </>
          )}
          {lists && lists.length === 0 && (
            <p className="note">
              No playlists are on yet.{' '}
              <button
                className="inline-link"
                onClick={() => {
                  onClose();
                  navigate('playlists');
                }}
              >
                Choose playlists
              </button>
            </p>
          )}
          {error && <p className="note">Playlists load when you have signal.</p>}
          {pulled.length > 0 && (
            <>
              <h4>Pulled channels</h4>
              <ul className="source-list">
                {pulled.map((c) => option({ key: `ch:${c.channel_id}`, label: `Channel: ${c.channel ?? c.channel_id}` }, `${c.inbox} to triage · ${c.videos} pulled`))}
              </ul>
            </>
          )}

          <h4>Order</h4>
          <div className="order-grid">
            <span className="order-label">Sort by</span>
            <div className="segmented" role="tablist" aria-label="Sort by">
              {(
                [
                  ['default', 'Default'],
                  ['posted', 'Posted'],
                  ['saved', 'Saved'],
                ] as const
              ).map(([k, label]) => (
                <button key={k} role="tab" aria-selected={order.sort === k} className={order.sort === k ? 'on' : ''} onClick={() => change({ sort: k })}>
                  {label}
                </button>
              ))}
            </div>
            {order.sort !== 'default' && (
              <>
                <span className="order-label">{order.start ? 'Go' : 'Show'}</span>
                <div className="segmented" role="tablist" aria-label="Direction">
                  <button role="tab" aria-selected={order.dir === 'desc'} className={order.dir === 'desc' ? 'on' : ''} onClick={() => change({ dir: 'desc' })}>
                    {order.start ? '← Backward' : 'Newest first'}
                  </button>
                  <button role="tab" aria-selected={order.dir === 'asc'} className={order.dir === 'asc' ? 'on' : ''} onClick={() => change({ dir: 'asc' })}>
                    {order.start ? 'Forward →' : 'Oldest first'}
                  </button>
                </div>
                <label className="order-label" htmlFor="order-start">
                  Start from
                </label>
                <div className="order-date">
                  <input
                    id="order-start"
                    type="date"
                    value={order.start ?? ''}
                    onChange={(e) => change({ start: e.target.value || null })}
                  />
                  {order.start && (
                    <button className="link-btn small" onClick={() => change({ start: null })}>
                      Clear
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
          <p className="note small">
            {order.sort === 'default'
              ? 'Default: each source’s own order (newest saves first where known).'
              : order.sort === 'posted'
                ? 'By when the video was posted on YouTube.'
                : 'By when you saved it. Known for playlists and bookmarks; Watch Later-only videos come last.'}
          </p>
          {order.sort !== 'default' && (
            <button className="link-btn small" onClick={() => setOrder(DEFAULT_ORDER)}>
              Reset to default order
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
