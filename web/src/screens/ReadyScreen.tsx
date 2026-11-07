import { useCallback, useEffect, useMemo, useState } from 'react';
import { AuthError, api, isNetworkError } from '../lib/api';
import { normalizeCard } from '../lib/format';
import { groupCards, rowNote, sortCards, type LibraryCard, type LibrarySort } from '../lib/libraryView';
import { ItemDetailView } from '../components/ItemDetailView';
import { useInfo } from '../state/info';
import { GroupedRows, ListControls, ToggleTitle, useListView } from '../components/ListControls';
import { readJSON, writeJSON } from '../state/storage';
import { WIDE, useMediaQuery } from '../state/hooks';

const CACHE_KEY = 'vm.ready.v1';
const SORTS: LibrarySort[] = ['analyzed', 'decided', 'posted', 'saved', 'signal', 'title'];

export function ReadyScreen({ online, onSeen }: { online: boolean; onSeen(id: string): void }) {
  const [items, setItems] = useState<LibraryCard[]>(() => readJSON<LibraryCard[]>(CACHE_KEY, []).map(normalizeCard));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<LibraryCard | null>(null);
  const wide = useMediaQuery(WIDE);
  const info = useInfo();
  const [view, change] = useListView(
    'vm.readyView.v1',
    { status: 'kept', sort: 'analyzed', dir: 'desc', group: 'none', groupOrder: 'most', controls: true },
    SORTS,
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = (await api.ready()).map((c) => normalizeCard(c as LibraryCard));
      setItems(list);
      writeJSON(CACHE_KEY, list);
    } catch (err) {
      if (!(err instanceof AuthError)) setError(isNetworkError(err) ? 'Offline. Showing the last list.' : (err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, online]);

  const groups = useMemo(
    () => groupCards(sortCards(items, view.sort, view.dir), view.group, view.groupOrder),
    [items, view.sort, view.dir, view.group, view.groupOrder],
  );

  const openItem = (c: LibraryCard) => {
    setOpen(c);
    api
      .seen(c.id)
      .then(() => onSeen(c.id))
      .catch(() => {
        // Not critical; it stays in Ready and gets marked next time.
      });
  };

  const back = () => {
    if (open) {
      const rest = items.filter((i) => i.id !== open.id);
      setItems(rest);
      writeJSON(CACHE_KEY, rest);
    }
    setOpen(null);
  };

  if (open && !wide) return <ItemDetailView card={open} onBack={back} />;

  const list = (
    <section className="page" aria-label="Ready">
      <header className="page-head">
        <ToggleTitle title="Ready" open={view.controls} onToggle={() => change({ controls: !view.controls })} />
        <button className="link-btn" onClick={() => void load()} disabled={loading || !online}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </header>
      {view.controls && items.length > 0 && <ListControls view={view} change={change} sorts={SORTS} showStatus={false} />}
      <div className="scroll page-body">
        {error && <p className="note">{error}</p>}
        {items.length === 0 && !loading ? (
          <div className="empty">
            <h2>Nothing new</h2>
            <p className="note">Swipe a card down to have it analyzed first. It shows up here when it’s done.</p>
          </div>
        ) : (
          <GroupedRows
            key={view.group}
            groups={groups}
            grouped={view.group !== 'none'}
            onOpen={openItem}
            note={(c) => rowNote(c, view, false)}
            selectedId={wide ? open?.id : null}
            onGroupInfo={
              view.group === 'channel'
                ? (g) => info.open({ kind: 'channel', channel_id: g.channelId ?? null, name: g.label })
                : undefined
            }
          />
        )}
      </div>
    </section>
  );

  // Side by side: opening marks it read, but it stays in the list until the next refresh.
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
            <p className="note">Newly analyzed notes show here.</p>
          </div>
        )}
      </div>
    </div>
  );
}
