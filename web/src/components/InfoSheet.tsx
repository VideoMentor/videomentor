// Bottom sheet with full details for a video, tag or channel (the ⓘ button).
import { useEffect, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { AuthError, api, isNetworkError } from '../lib/api';
import {
  actionLabel,
  byline,
  compactNumber,
  excerpt,
  formatDuration,
  formatMinutes,
  formatPosted,
  formatYmd,
  normalizeCard,
  relativeTime,
  sourceLabel,
  thumbnailOf,
} from '../lib/format';
import type { Card, ChannelSummary, ItemDetail, Playlist, TagHistory } from '../lib/types';
import { navigate, openTag } from '../state/nav';
import { playlistSource, setSource } from '../state/source';
import { useInfo, type InfoTarget } from '../state/info';

/** Load something for the sheet; null while loading, with a friendly error. */
function useLoad<T>(load: (signal: AbortSignal) => Promise<T>, key: string): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    setData(null);
    setError(null);
    load(ctl.signal)
      .then((d) => {
        if (!ctl.signal.aborted) setData(d);
      })
      .catch((err) => {
        if (ctl.signal.aborted || err instanceof AuthError) return;
        setError(isNetworkError(err) ? 'Offline. Details load when you have signal.' : (err as Error).message);
      });
    return () => ctl.abort();
  }, [key]); // `load` is a fresh closure each render; `key` says when to reload
  return { data, error };
}

const TITLES: Record<InfoTarget['kind'], string> = { video: 'Video info', tag: 'Tag', channel: 'Channel', playlist: 'Playlist' };

export function InfoSheet() {
  const { stack, back, close } = useInfo();
  const top = stack[stack.length - 1];
  if (!top) return null;
  return (
    <div className="info-backdrop" role="presentation" onClick={close}>
      <div
        className="info-sheet"
        role="dialog"
        aria-modal="true"
        aria-label={TITLES[top.kind]}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="info-head">
          {stack.length > 1 ? (
            <button className="link-btn" onClick={back} aria-label="Back">
              ‹ Back
            </button>
          ) : (
            <span />
          )}
          <span className="info-kind">{TITLES[top.kind]}</span>
          <button className="link-btn" onClick={close}>
            Done
          </button>
        </div>
        <div className="info-body scroll">
          {top.kind === 'video' && <VideoInfo card={top.card} />}
          {top.kind === 'tag' && <TagInfo tag={top.tag} />}
          {top.kind === 'channel' && <ChannelInfo channelId={top.channel_id ?? null} name={top.name} />}
          {top.kind === 'playlist' && <PlaylistInfo playlist={top.playlist} />}
        </div>
      </div>
    </div>
  );
}

/** Tag chips that open the tag sheet. Safe inside a swipe card: a press on a chip never starts a swipe. */
export function TagChips({ tags, limit }: { tags: string[]; limit?: number }) {
  const { open } = useInfo();
  if (!tags.length) return null;
  const stop = (e: ReactPointerEvent) => e.stopPropagation();
  return (
    <div className="chips">
      {tags.slice(0, limit ?? tags.length).map((t) => (
        <button
          key={t}
          className="chip chip-btn"
          onPointerDown={stop}
          onPointerUp={stop}
          onClick={(e) => {
            e.stopPropagation();
            open({ kind: 'tag', tag: t });
          }}
        >
          {t}
        </button>
      ))}
    </div>
  );
}

function VideoInfo({ card }: { card: Card }) {
  const { open } = useInfo();
  const { data, error } = useLoad<ItemDetail>((s) => api.item(card.id, s), card.id);
  const d: Card & Partial<ItemDetail> = data ? normalizeCard({ ...card, ...data }) : card;
  const { posted, by } = byline(d);
  const stats = [
    formatMinutes(d.duration_s),
    d.view_count ? `${compactNumber(d.view_count)} views` : '',
  ].filter(Boolean);
  const history = (d.decisions ?? []).filter((x) => x.action !== 'undo');
  const chapters = Array.isArray(d.chapters) ? d.chapters : [];

  return (
    <>
      <img className="info-thumb" src={thumbnailOf(d)} alt="" />
      <h2 className="info-title">{d.title}</h2>
      <dl className="info-facts">
        {posted && (
          <>
            <dt>Posted</dt>
            <dd>{posted}</dd>
          </>
        )}
        {by && (
          <>
            <dt>By</dt>
            <dd>
              <button
                className="inline-link"
                onClick={() => open({ kind: 'channel', channel_id: d.channel_id, name: d.channel })}
              >
                {d.channel}
              </button>
              {(d.collaborators ?? []).map((c, i, all) => (
                <span key={c.channel_id ?? c.name}>
                  {i === 0 ? ' with ' : i === all.length - 1 ? ' and ' : ', '}
                  <button className="inline-link" onClick={() => open({ kind: 'channel', channel_id: c.channel_id, name: c.name })}>
                    {c.name}
                  </button>
                </span>
              ))}
              {d.channel_handle && <span className="muted"> {d.channel_handle}</span>}
              {d.channel_followers ? <span className="muted"> · {compactNumber(d.channel_followers)} subscribers</span> : null}
            </dd>
          </>
        )}
        {stats.length > 0 && (
          <>
            <dt>Length</dt>
            <dd>{stats.join(' · ')}</dd>
          </>
        )}
        <dt>Status</dt>
        <dd>
          {d.status === 'inbox' ? 'In the deck' : d.status === 'kept' ? 'Kept' : 'Archived'}
          {d.analysis_status !== 'none' && ` · analysis ${d.analysis_status}`}
        </dd>
      </dl>

      {d.tags.length > 0 && (
        <section>
          <h4>Tags</h4>
          <TagChips tags={d.tags} />
        </section>
      )}

      {(d.saved_in?.length ?? 0) > 0 && (
        <section>
          <h4>Saved in</h4>
          <ul className="info-list">
            {d.saved_in!.map((s) => (
              <li key={s.source}>
                {s.source.startsWith('playlist:') ? s.source_ref || 'Playlist' : sourceLabel(s.source)}
                <span className="muted"> · first seen {relativeTime(s.first_seen)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {history.length > 0 && (
        <section>
          <h4>Your history</h4>
          <ul className="info-list">
            {history.map((h) => (
              <li key={h.id}>
                {h.reason === 'unavailable' ? 'Archived automatically (unavailable)' : actionLabel(h.action)}
                <span className="muted">
                  {' '}
                  · {relativeTime(h.at)}
                  {h.undone ? ' · undone' : ''}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {chapters.length > 0 && (
        <section>
          <h4>Chapters</h4>
          <ul className="info-list">
            {chapters.slice(0, 12).map((c, i) => (
              <li key={i}>
                <span className="muted">{formatDuration(c.t) || '0:00'}</span> {c.label}
              </li>
            ))}
          </ul>
        </section>
      )}

      {((d.yt_categories?.length ?? 0) > 0 || (d.yt_tags?.length ?? 0) > 0) && (
        <section>
          <h4>From YouTube</h4>
          <p className="muted small">
            {[...(d.yt_categories ?? []), ...(d.yt_tags ?? []).slice(0, 15)].join(' · ')}
          </p>
        </section>
      )}

      {d.description && (
        <section>
          <h4>Description</h4>
          <p className="pre small">{excerpt(d.description, 600)}</p>
        </section>
      )}

      {!data && !error && <p className="note">Loading…</p>}
      {error && <p className="note">{error}</p>}
      <a className="pill-btn info-open" href={d.url} target="_blank" rel="noopener noreferrer">
        Open on YouTube
      </a>
    </>
  );
}

function TagInfo({ tag }: { tag: string }) {
  const { open, close } = useInfo();
  const [building, setBuilding] = useState<string | null>(null);
  const buildTraining = async () => {
    setBuilding('Starting…');
    try {
      await api.buildTraining(data?.tag ?? tag);
      close();
      navigate('train');
    } catch (err) {
      setBuilding((err as Error).message);
    }
  };
  const { data, error } = useLoad<TagHistory>((s) => api.tagHistory(tag, s), tag);
  const items = (data?.items ?? []).map(normalizeCard);
  return (
    <>
      <h2 className="info-title">{data?.tag ?? tag}</h2>
      {data && (
        <p className="muted">
          {data.total} video{data.total === 1 ? '' : 's'} with this tag · {items.length} you’ve touched
        </p>
      )}
      <button
        className="inline-link see-all-tag"
        onClick={() => {
          close();
          openTag({ tag: data?.tag ?? tag, status: 'all' });
        }}
      >
        {data ? `See all ${data.total.toLocaleString()} video${data.total === 1 ? '' : 's'}` : 'See all videos'} ›
      </button>
      <button className="secondary train-from-tag" onClick={() => void buildTraining()} disabled={building === 'Starting…'}>
        🎓 Build training from this tag
      </button>
      {building && building !== 'Starting…' && <p className="note small">{building}</p>}
      {data && data.related.length > 0 && (
        <section>
          <h4>Related tags</h4>
          <TagChips tags={data.related.map((r) => r.tag)} />
        </section>
      )}
      <section>
        <h4>You’ve touched</h4>
        {data && items.length === 0 && (
          <p className="note">Nothing yet. Videos show up here after you swipe, flip, open or check their info.</p>
        )}
        <ul className="rows">
          {items.map((c) => (
            <li key={c.id}>
              <button className="row" onClick={() => open({ kind: 'video', card: c })}>
                <img className="row-thumb" src={thumbnailOf(c)} alt="" loading="lazy" />
                <span className="row-text">
                  <span className="row-title">{c.title}</span>
                  <small>
                    {actionLabel(c.last_action)} · {relativeTime(c.last_at)}
                    {c.channel ? ` · ${c.channel}` : ''}
                  </small>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>
      {!data && !error && <p className="note">Loading…</p>}
      {error && <p className="note">{error}</p>}
    </>
  );
}

function ChannelInfo({ channelId, name }: { channelId: string | null; name: string | null }) {
  const { open } = useInfo();
  const { data, error } = useLoad<ChannelSummary>(
    (s) => api.channel({ channel_id: channelId, name }, s),
    `${channelId}|${name}`,
  );
  const c = data?.counts;
  return (
    <>
      <h2 className="info-title">{data?.channel ?? name ?? 'Channel'}</h2>
      {data && (
        <p className="muted">
          {[data.handle, data.followers ? `${compactNumber(data.followers)} subscribers` : ''].filter(Boolean).join(' · ')}
        </p>
      )}
      {c && (
        <div className="info-counts">
          <div>
            <b>{c.saved}</b>saved
          </div>
          <div>
            <b>{c.kept}</b>kept
          </div>
          <div>
            <b>{c.archived}</b>archived
          </div>
          <div>
            <b>{c.inbox}</b>in deck
          </div>
        </div>
      )}
      {(data?.items?.length ?? 0) > 0 && (
        <section>
          <h4>Your saves from this channel</h4>
          <ul className="rows">
            {data!.items!.map(normalizeCard).map((c) => (
              <li key={c.id}>
                <button className="row" onClick={() => open({ kind: 'video', card: c })}>
                  <img className="row-thumb" src={thumbnailOf(c)} alt="" loading="lazy" />
                  <span className="row-text">
                    <span className="row-title">{c.title}</span>
                    <small>
                      {[
                        c.status === 'inbox' ? 'In the deck' : c.status === 'kept' ? 'Kept' : 'Archived',
                        formatPosted(c.posted_at, false),
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </small>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {data?.channel_id && <ChannelPull channelId={data.channel_id} name={data.channel ?? name ?? 'Channel'} />}
      {data?.handle && (
        <a
          className="pill-btn info-open"
          href={`https://www.youtube.com/${data.handle}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          Open channel on YouTube
        </a>
      )}
      {!data && !error && <p className="note">Loading…</p>}
      {error && <p className="note">{error}</p>}
    </>
  );
}

function PlaylistInfo({ playlist }: { playlist: Playlist }) {
  const { close } = useInfo();
  const { data, error } = useLoad<Playlist>((s) => api.playlist(playlist.id, s), playlist.id);
  const [enabled, setEnabled] = useState(playlist.enabled);
  const [busy, setBusy] = useState(false);
  const p = { ...playlist, ...(data ?? {}), enabled };

  const toggle = async () => {
    setBusy(true);
    try {
      const r = await api.setPlaylist(p.id, !enabled);
      setEnabled(r.enabled);
    } catch {
      // the switch stays where it was
    } finally {
      setBusy(false);
    }
  };

  const swipe = () => {
    setSource(playlistSource(p.id, p.title));
    close();
    navigate('deck');
  };

  return (
    <>
      <h2 className="info-title">{p.title || 'Untitled playlist'}</h2>
      <dl className="info-facts">
        {p.owner && (
          <>
            <dt>Owner</dt>
            <dd>{p.owner}</dd>
          </>
        )}
        <dt>Videos</dt>
        <dd>{p.video_count ?? '?'}</dd>
        {p.modified_date && (
          <>
            <dt>Last updated</dt>
            <dd>{formatYmd(p.modified_date)}</dd>
          </>
        )}
        <dt>Created</dt>
        <dd>{p.created_at ? formatPosted(p.created_at, false) : <span className="muted">needs YouTube sign-in on the Mac</span>}</dd>
        {p.newest_save && (
          <>
            <dt>Newest save</dt>
            <dd>
              {formatPosted(p.newest_save, false)}
              {!p.dates_known && <span className="muted"> (first seen by the app)</span>}
            </dd>
          </>
        )}
        {p.visibility && (
          <>
            <dt>Visibility</dt>
            <dd>{p.visibility}</dd>
          </>
        )}
      </dl>

      <label className="switch-row">
        <span>Sync into the deck</span>
        <span className="switch">
          <input type="checkbox" checked={enabled} onChange={() => void toggle()} disabled={busy} />
          <span aria-hidden="true" />
        </span>
      </label>

      {enabled && p.synced > 0 && (
        <div className="info-counts">
          <div>
            <b>{p.synced}</b>synced
          </div>
          <div>
            <b>{p.inbox}</b>to triage
          </div>
          <div>
            <b>{p.kept}</b>kept
          </div>
          <div>
            <b>{p.archived}</b>archived
          </div>
        </div>
      )}
      {enabled && p.synced === 0 && <p className="note">Syncing. Videos reach the deck in a few minutes, after they're tagged.</p>}

      {enabled && p.inbox > 0 && (
        <button className="primary info-open" onClick={swipe}>
          Swipe this playlist
        </button>
      )}
      {p.error && <p className="note">YouTube couldn't read this playlist: {p.error}</p>}
      {error && <p className="note">{error}</p>}
      <p>
        <a className="pill-btn info-open" href={`https://www.youtube.com/playlist?list=${p.id}`} target="_blank" rel="noopener noreferrer">
          Open on YouTube
        </a>
      </p>
    </>
  );
}

/** Bring in a channel's videos you haven't saved: newest N, oldest N, or a date range. */
function ChannelPull({ channelId, name }: { channelId: string; name: string }) {
  const { close } = useInfo();
  const [mode, setMode] = useState<'newest' | 'oldest' | 'range'>('newest');
  const [count, setCount] = useState(25);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [shorts, setShorts] = useState(false);
  const [lives, setLives] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ text: string; ok: boolean; added: number } | null>(null);
  const ready = mode !== 'range' || (start !== '' && end !== '' && start <= end);

  const run = async () => {
    setBusy(true);
    setResult(null);
    try {
      const kinds = { include_shorts: shorts, include_lives: lives };
      const r = await api.pullChannel(
        mode === 'range'
          ? { channel_id: channelId, mode, start, end, ...kinds }
          : { channel_id: channelId, mode, count, ...kinds },
      );
      const ready = ' They get tagged and scored in a minute or two, then they are ready to swipe.';
      setResult({
        ok: true,
        added: r.added,
        text:
          mode === 'range'
            ? r.seen
              ? `Found ${r.seen} in those dates, ${r.added} new.${r.added ? ready : ''}`
              : 'No videos in those dates.'
            : r.added
              ? `Added ${r.added} ${r.added === 1 ? 'video' : 'videos'} you didn't have.${ready}`
              : 'You already have every video this pull could reach.',
      });
    } catch (err) {
      setResult({ ok: false, added: 0, text: isNetworkError(err) ? 'Pulling needs a connection.' : (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const swipe = () => {
    setSource({ key: `ch:${channelId}`, label: `Channel: ${name}` });
    close();
    navigate('deck');
  };

  return (
    <section className="pull-panel">
      <h4>Pull videos from this channel</h4>
      <p className="note small">Brings in videos you don't have yet, as their own deck. They stay out of All saves.</p>
      <div className="segmented" role="tablist" aria-label="Which videos">
        {(
          [
            ['newest', 'Newest'],
            ['oldest', 'Oldest'],
            ['range', 'Dates'],
          ] as const
        ).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={mode === k} className={mode === k ? 'on' : ''} onClick={() => setMode(k)}>
            {label}
          </button>
        ))}
      </div>
      {mode === 'range' ? (
        <div className="pull-dates">
          <label>
            From <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label>
            To <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </label>
        </div>
      ) : (
        <label className="lib-select pull-count">
          <span>{mode === 'newest' ? 'Next, newest first' : 'Next, from the first video'}</span>
          <select value={count} onChange={(e) => setCount(Number(e.target.value))}>
            {[10, 25, 50, 100, 200].map((n) => (
              <option key={n} value={n}>
                {n} videos
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="pull-kinds">
        <label>
          <input type="checkbox" checked={shorts} onChange={(e) => setShorts(e.target.checked)} /> Shorts
        </label>
        <label>
          <input type="checkbox" checked={lives} onChange={(e) => setLives(e.target.checked)} /> Live streams
        </label>
      </div>
      <div className="pull-actions">
        <button className="primary" onClick={() => void run()} disabled={busy || !ready}>
          {busy ? 'Pulling…' : 'Pull videos'}
        </button>
        {result?.ok && result.added > 0 && (
          <button className="secondary" onClick={swipe}>
            Swipe them
          </button>
        )}
      </div>
      {result && <p className={`note small${result.ok ? '' : ' pull-error'}`}>{result.text}</p>}
    </section>
  );
}
