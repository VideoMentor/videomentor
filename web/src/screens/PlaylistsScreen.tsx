// Every playlist in the YouTube library, with a switch to sync it into the deck.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AuthError, api, isNetworkError } from '../lib/api';
import { formatPosted, formatYmd } from '../lib/format';
import type { Playlist, YouTubeApiState } from '../lib/types';
import { useInfo } from '../state/info';
import { SearchBox } from '../components/SearchBox';
import { useDebounced } from '../state/hooks';
import { ToggleTitle } from '../components/ListControls';
import { readJSON, writeJSON } from '../state/storage';
import {
  PLAYLIST_DIR_WORDS,
  PLAYLIST_SORT_LABELS,
  filterPlaylists,
  sortPlaylists,
  type PlaylistOwner,
  type PlaylistShow,
  type PlaylistSort,
} from '../lib/playlistView';

interface PlaylistsView {
  show: PlaylistShow;
  owner: PlaylistOwner;
  sort: PlaylistSort;
  dir: 'asc' | 'desc';
  controls: boolean;
}
const VIEW_KEY = 'vm.playlistsView.v1';
const DEFAULT_VIEW: PlaylistsView = { show: 'all', owner: 'anyone', sort: 'order', dir: 'asc', controls: true };

function loadView(): PlaylistsView {
  const v = readJSON<Partial<PlaylistsView>>(VIEW_KEY, {});
  return {
    show: v.show === 'on' ? 'on' : 'all',
    owner: v.owner === 'mine' || v.owner === 'others' ? v.owner : 'anyone',
    sort: v.sort && v.sort in PLAYLIST_SORT_LABELS ? v.sort : DEFAULT_VIEW.sort,
    dir: v.dir === 'desc' ? 'desc' : 'asc',
    controls: typeof v.controls === 'boolean' ? v.controls : true,
  };
}

export function PlaylistsScreen({ online }: { online: boolean }) {
  const [rows, setRows] = useState<Playlist[] | null>(null);
  const [apiState, setApiState] = useState<YouTubeApiState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [view, setView] = useState<PlaylistsView>(loadView);
  const change = (patch: Partial<PlaylistsView>) =>
    setView((v) => {
      const next = { ...v, ...patch };
      writeJSON(VIEW_KEY, next);
      return next;
    });
  const [q, setQ] = useState('');
  const query = useDebounced(q, 150);
  const { open } = useInfo();

  const load = useCallback(async (signal?: AbortSignal) => {
    setError(null);
    try {
      const r = await api.playlists(signal);
      setRows(r.playlists);
      setApiState(r.youtube_api);
    } catch (err) {
      if (signal?.aborted || err instanceof AuthError) return;
      setError(isNetworkError(err) ? 'Playlists need a connection.' : (err as Error).message);
    }
  }, []);

  useEffect(() => {
    const ctl = new AbortController();
    void load(ctl.signal);
    return () => ctl.abort();
  }, [load, online]);

  // Most playlists are your own; only show the owner for the ones that aren't.
  const me = useMemo(() => {
    const counts = new Map<string, number>();
    for (const r of rows ?? []) if (r.owner) counts.set(r.owner, (counts.get(r.owner) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
  }, [rows]);

  const shown = useMemo(
    () => sortPlaylists(filterPlaylists(rows ?? [], { show: view.show, owner: view.owner, q: query, me }), view.sort, view.dir),
    [rows, view.show, view.owner, view.sort, view.dir, query, me],
  );
  const [descWord, ascWord] = PLAYLIST_DIR_WORDS[view.sort];
  const onCount = (rows ?? []).filter((r) => r.enabled).length;

  const toggle = async (p: Playlist) => {
    const next = !p.enabled;
    setRows((rs) => rs?.map((r) => (r.id === p.id ? { ...r, enabled: next } : r)) ?? rs);
    try {
      const updated = await api.setPlaylist(p.id, next);
      setRows((rs) => rs?.map((r) => (r.id === p.id ? { ...r, ...updated } : r)) ?? rs);
      setNote(
        next
          ? `Syncing “${p.title}”. Its videos reach the deck in a few minutes, after they're tagged.`
          : `“${p.title}” won't sync any more. Videos already pulled in stay in your library.`,
      );
    } catch (err) {
      setRows((rs) => rs?.map((r) => (r.id === p.id ? { ...r, enabled: p.enabled } : r)) ?? rs);
      setNote(isNetworkError(err) ? 'Offline. Try the switch again when you have signal.' : (err as Error).message);
    }
  };

  return (
    <section className="page" aria-label="Playlists">
      <header className="page-head">
        <ToggleTitle title="Playlists" open={view.controls} onToggle={() => change({ controls: !view.controls })} />
        <button className="link-btn" onClick={() => void load()} disabled={!online}>
          Refresh
        </button>
      </header>
      {apiState && apiState.state !== 'ok' && (
        <p className={`api-banner ${apiState.state === 'expired' ? 'warn' : ''}`}>
          {apiState.state === 'expired'
            ? 'YouTube sign-in expired (it lasts 7 days). On the Mac, run vm youtube-login. Created and save dates pause until then.'
            : apiState.state === 'signed_out'
              ? 'Created and save dates appear after you run vm youtube-login on the Mac.'
              : 'Created and save dates need the YouTube API set up on the Mac.'}
        </p>
      )}
      <div className="search pl-tools">
        <SearchBox
          value={q}
          onChange={setQ}
          placeholder={rows ? `Search ${rows.length} playlists` : 'Search playlists'}
          label="Search playlists"
        />
      </div>
      {view.controls && (
        <div className="lib-controls">
          <div className="lib-row">
            <div className="segmented" role="tablist" aria-label="Which playlists">
              <button role="tab" aria-selected={view.show === 'all'} className={view.show === 'all' ? 'on' : ''} onClick={() => change({ show: 'all' })}>
                All
              </button>
              <button role="tab" aria-selected={view.show === 'on'} className={view.show === 'on' ? 'on' : ''} onClick={() => change({ show: 'on' })}>
                On · {onCount}
              </button>
            </div>
            <label className="lib-select">
              <span>Owner</span>
              <select value={view.owner} onChange={(e) => change({ owner: e.target.value as PlaylistOwner })}>
                <option value="anyone">Anyone</option>
                <option value="mine">Mine</option>
                <option value="others">Saved from others</option>
              </select>
            </label>
          </div>
          <div className="lib-row">
            <label className="lib-select">
              <span>Sort</span>
              <select value={view.sort} onChange={(e) => change({ sort: e.target.value as PlaylistSort })}>
                {(Object.keys(PLAYLIST_SORT_LABELS) as PlaylistSort[]).map((k) => (
                  <option key={k} value={k}>
                    {PLAYLIST_SORT_LABELS[k]}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="dir-btn"
              onClick={() => change({ dir: view.dir === 'desc' ? 'asc' : 'desc' })}
              aria-label={`Order: ${view.dir === 'desc' ? descWord : ascWord} first. Tap to flip.`}
            >
              {view.dir === 'desc' ? `↓ ${descWord}` : `↑ ${ascWord}`}
            </button>
            <span className="muted small">{shown.length} shown</span>
          </div>
        </div>
      )}
      <div className="scroll page-body">
        {note && (
          <p className="api-banner" role="status">
            {note}
          </p>
        )}
        {error && <p className="note">{error}</p>}
        {!rows && !error && <p className="note">Loading…</p>}
        {rows && rows.length === 0 && (
          <div className="empty">
            <h2>No playlists yet</h2>
            <p className="note">They appear after the next sync, or run vm playlists --refresh on the Mac.</p>
          </div>
        )}
        {rows && rows.length > 0 && shown.length === 0 && (
          <p className="note">{view.show === 'on' && onCount === 0 ? 'No playlists are on yet. Switch some on under All.' : 'No matches.'}</p>
        )}
        <ul className="rows">
          {shown.map((p) => (
            <li key={p.id} className="pl-row">
              <button className="pl-main" onClick={() => open({ kind: 'playlist', playlist: p })}>
                <span className="row-title">{p.title || 'Untitled playlist'}</span>
                <small>
                  {[
                    p.video_count !== null ? `${p.video_count} video${p.video_count === 1 ? '' : 's'}` : '',
                    p.modified_date ? `updated ${formatYmd(p.modified_date)}` : '',
                    p.created_at ? `created ${formatPosted(p.created_at, false)}` : '',
                    p.owner && p.owner !== me ? `by ${p.owner}` : '',
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </small>
                {p.enabled && p.synced > 0 && (
                  <small className="pl-synced">
                    {[
                      p.newest_save ? `newest save ${formatPosted(p.newest_save, false)}${p.dates_known ? '' : ' (first seen)'}` : '',
                      `${p.inbox} to triage`,
                      p.kept ? `${p.kept} kept` : '',
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </small>
                )}
              </button>
              <label className="switch" aria-label={`Sync ${p.title}`}>
                <input type="checkbox" checked={p.enabled} onChange={() => void toggle(p)} disabled={!online} />
                <span aria-hidden="true" />
              </label>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
