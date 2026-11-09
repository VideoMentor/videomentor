import { useEffect, useMemo, useState } from 'react';
import { AuthError, api, isNetworkError } from '../lib/api';
import { normalizeCard } from '../lib/format';
import { groupCards, rowNote, sortCards, type LibraryCard, type LibrarySort } from '../lib/libraryView';
import { ItemDetailView } from '../components/ItemDetailView';
import { useInfo } from '../state/info';
import { SearchBox } from '../components/SearchBox';
import { GroupedRows, ListControls, ToggleTitle, useListView } from '../components/ListControls';
import { WIDE, useDebounced, useMediaQuery } from '../state/hooks';
import { navigate } from '../state/nav';

const SORTS: LibrarySort[] = ['decided', 'posted', 'saved', 'signal', 'title', 'analyzed'];

export function LibraryScreen({ online }: { online: boolean }) {
  const [q, setQ] = useState('');
  const query = useDebounced(q, 300);
  const [view, change] = useListView(
    'vm.libraryView.v1',
    { status: 'kept', sort: 'decided', dir: 'desc', group: 'none', groupOrder: 'most', controls: true },
    SORTS,
  );
  const [items, setItems] = useState<LibraryCard[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<LibraryCard | null>(null);
  const wide = useMediaQuery(WIDE);
  const info = useInfo();

  useEffect(() => {
    const ctl = new AbortController();
    setLoading(true);
    setError(null);
    api
      .library(query, ctl.signal, view.status)
      .then((list) => setItems(list.map((c) => normalizeCard(c as LibraryCard))))
      .catch((err) => {
        if (ctl.signal.aborted || err instanceof AuthError) return;
        setError(isNetworkError(err) ? 'The library needs a connection.' : (err as Error).message);
      })
      .finally(() => {
        if (!ctl.signal.aborted) setLoading(false);
      });
    return () => ctl.abort();
  }, [query, online, view.status]);

  const groups = useMemo(
    () => groupCards(sortCards(items, view.sort, view.dir), view.group, view.groupOrder),
    [items, view.sort, view.dir, view.group, view.groupOrder],
  );

  if (open && !wide) return <ItemDetailView card={open} onBack={() => setOpen(null)} />;

  const what = view.status === 'kept' ? 'kept' : view.status === 'archived' ? 'archived' : 'processed';

  const list = (
    <section className="page" aria-label="Library">
      <header className="page-head">
        <ToggleTitle title="Library" open={view.controls} onToggle={() => change({ controls: !view.controls })} />
        <span className="head-links">
          <span className="muted small">{items.length ? `${items.length} ${what}` : ''}</span>
          <button className="link-btn small" onClick={() => navigate('tags')}>
            Tags
          </button>
          <button className="link-btn small" onClick={() => navigate('insights')}>
            Insights
          </button>
        </span>
      </header>
      <div className="search">
        <SearchBox value={q} onChange={setQ} placeholder={`Search ${what} videos`} label={`Search ${what} videos`} />
      </div>
      {view.controls && <ListControls view={view} change={change} sorts={SORTS} showStatus />}
      <div className="scroll page-body">
        {error && <p className="note">{error}</p>}
        {loading && items.length === 0 && <p className="note">Loading…</p>}
        {!loading && !error && items.length === 0 && (
          <div className="empty">
            <h2>{query ? 'No matches' : `No ${what} videos yet`}</h2>
            <p className="note">{query ? 'Try another word.' : 'Swipe right on a card to keep it, left to archive it.'}</p>
          </div>
        )}
        <GroupedRows
          key={view.group}
          groups={groups}
          grouped={view.group !== 'none'}
          onOpen={setOpen}
          note={(c) => rowNote(c, view)}
          selectedId={wide ? open?.id : null}
          onGroupInfo={
            view.group === 'channel'
              ? (g) => info.open({ kind: 'channel', channel_id: g.channelId ?? null, name: g.label })
              : undefined
          }
        />
      </div>
    </section>
  );

  if (!wide) return list;
  return (
    <div className="split">
      <div className="split-list">{list}</div>
      <div className="split-detail">
        {open ? (
          <ItemDetailView key={open.id} card={open} embedded />
        ) : (
          <div className="empty">
            <h2>Pick a video</h2>
            <p className="note">Its notes, key idea and moments show here.</p>
          </div>
        )}
      </div>
    </div>
  );
}
