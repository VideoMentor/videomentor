// Tags: every tag with its counts, and a page per tag listing its videos (sortable).
import { useEffect, useMemo, useState } from 'react';
import { AuthError, api, isNetworkError } from '../lib/api';
import { formatMinutes } from '../lib/format';
import {
  TAG_DIR_WORDS,
  TAG_SORTS,
  TAG_SORT_LABELS,
  filterTags,
  sortTagItems,
  tagCount,
  tagItemCard,
  tagItemNote,
  type TagSort,
} from '../lib/tagView';
import type { Card, TagItemStatus, TagItemsResponse, TagRow } from '../lib/types';
import type { Tab } from '../components/TabBar';
import { ItemRow } from '../components/ItemRow';
import { ItemDetailView } from '../components/ItemDetailView';
import { SearchBox } from '../components/SearchBox';
import { useInfo } from '../state/info';
import { navigate, type TagTarget } from '../state/nav';
import { readJSON, writeJSON } from '../state/storage';
import { WIDE, useDebounced, useMediaQuery } from '../state/hooks';

const LIST_KEY = 'vm.tagsView.v1';
const PAGE_KEY = 'vm.tagPageView.v1';

const STATUS_CHOICES: [TagItemStatus, string][] = [
  ['kept', 'Kept'],
  ['inbox', 'Inbox'],
  ['all', 'All'],
];

const isStatus = (v: unknown): v is TagItemStatus => v === 'kept' || v === 'inbox' || v === 'all';

/** "‹ Home", "‹ Library": where a screen outside the tab bar goes back to. */
export function backLabel(tab: Tab): string {
  return `‹ ${tab.charAt(0).toUpperCase()}${tab.slice(1)}`;
}

const minutes = (m: number | null | undefined) => formatMinutes((m ?? 0) * 60);
const avg = (v: number | null | undefined) => (v === null || v === undefined || !Number.isFinite(v) ? '' : `signal ${v.toFixed(1)}`);

interface Props {
  online: boolean;
  page: TagTarget | null;
  onPage(target: TagTarget | null): void;
  backTab: Tab;
}

export function TagsScreen({ online, page, onPage, backTab }: Props) {
  const wide = useMediaQuery(WIDE);
  const back = () => navigate(backTab);

  if (page && !wide) {
    return (
      <TagPage
        key={`${page.tag}:${page.status ?? ''}`}
        target={page}
        online={online}
        onBack={() => (page.from === 'list' ? onPage(null) : page.from === 'insights' ? navigate('insights') : back())}
        backText={page.from === 'list' ? '‹ Tags' : page.from === 'insights' ? '‹ Insights' : backLabel(backTab)}
      />
    );
  }

  const list = <TagList online={online} onBack={back} backTab={backTab} selected={page?.tag ?? null} onOpen={(tag, status) => onPage({ tag, status, from: 'list' })} />;
  if (!wide) return list;
  return (
    <div className="split">
      <div className="split-list">{list}</div>
      <div className="split-detail">
        {page ? (
          <TagPage key={`${page.tag}:${page.status ?? ''}`} target={page} online={online} embedded />
        ) : (
          <div className="empty">
            <h2>Pick a tag</h2>
            <p className="note">Its videos show here, with ways to sort them.</p>
          </div>
        )}
      </div>
    </div>
  );
}

function TagList({
  online,
  onBack,
  backTab,
  selected,
  onOpen,
}: {
  online: boolean;
  onBack(): void;
  backTab: Tab;
  selected: string | null;
  onOpen(tag: string, status: TagItemStatus): void;
}) {
  const [tags, setTags] = useState<TagRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const query = useDebounced(q, 150);
  const [view, setView] = useState(() => {
    const v = readJSON<{ status?: unknown; all?: unknown }>(LIST_KEY, {});
    return { status: isStatus(v.status) ? v.status : 'kept', all: v.all === true } as { status: TagItemStatus; all: boolean };
  });
  const change = (patch: Partial<typeof view>) =>
    setView((v) => {
      const next = { ...v, ...patch };
      writeJSON(LIST_KEY, next);
      return next;
    });

  useEffect(() => {
    const ctl = new AbortController();
    api
      .tags(ctl.signal)
      .then((t) => {
        setTags(t);
        setError(null);
      })
      .catch((err) => {
        if (ctl.signal.aborted || err instanceof AuthError) return;
        setError(isNetworkError(err) ? 'Tags need a connection the first time.' : (err as Error).message);
      });
    return () => ctl.abort();
  }, [online]);

  const shown = useMemo(() => filterTags(tags ?? [], { q: query, status: view.status, all: view.all }), [tags, query, view.status, view.all]);

  return (
    <section className="page" aria-label="Tags">
      <header className="page-head">
        <button className="link-btn" onClick={onBack}>
          {backLabel(backTab)}
        </button>
        <h1>Tags</h1>
        <span className="muted small">{tags ? `${shown.length} shown` : ''}</span>
      </header>
      <div className="search">
        <SearchBox value={q} onChange={setQ} placeholder="Search tags" label="Search tags" />
      </div>
      <div className="lib-controls">
        <div className="lib-row">
          <div className="segmented" role="tablist" aria-label="Count videos that are">
            {STATUS_CHOICES.map(([k, label]) => (
              <button key={k} role="tab" aria-selected={view.status === k} className={view.status === k ? 'on' : ''} onClick={() => change({ status: k })}>
                {label}
              </button>
            ))}
          </div>
          <div className="segmented" role="tablist" aria-label="Which tags">
            <button role="tab" aria-selected={!view.all} className={!view.all ? 'on' : ''} onClick={() => change({ all: false })}>
              3+ videos
            </button>
            <button role="tab" aria-selected={view.all} className={view.all ? 'on' : ''} onClick={() => change({ all: true })}>
              All
            </button>
          </div>
        </div>
      </div>
      <div className="scroll page-body">
        {error && <p className="note">{error}</p>}
        {!tags && !error && <p className="note">Loading…</p>}
        {tags && shown.length === 0 && (
          <div className="empty">
            <h2>{query ? 'No matching tags' : 'No tags here yet'}</h2>
            <p className="note">{query ? 'Try another word.' : view.all ? 'Tags appear as videos are prepped.' : 'Tap All to see tags with fewer videos.'}</p>
          </div>
        )}
        <ul className="rows tag-rows">
          {shown.map((t) => (
            <li key={t.tag}>
              <button className={`row tag-row${t.tag === selected ? ' selected' : ''}`} onClick={() => onOpen(t.tag, view.status)} aria-current={t.tag === selected || undefined}>
                <span className="row-text">
                  <span className="row-title">{t.tag}</span>
                  <small>
                    {[`${t.kept} kept`, t.inbox ? `${t.inbox} in the deck` : '', t.archived ? `${t.archived} archived` : ''].filter(Boolean).join(' · ')}
                  </small>
                  <small>{[avg(t.avg_signal), minutes(t.minutes), t.analyzed ? `${t.analyzed} analyzed` : ''].filter(Boolean).join(' · ')}</small>
                </span>
                <span className="tag-count" aria-hidden="true">
                  {tagCount(t, view.status)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

interface PageView {
  status: TagItemStatus;
  sort: TagSort;
  dir: 'asc' | 'desc';
}

function TagPage({
  target,
  online,
  onBack,
  backText,
  embedded = false,
}: {
  target: TagTarget;
  online: boolean;
  onBack?(): void;
  backText?: string;
  embedded?: boolean;
}) {
  const info = useInfo();
  const wide = useMediaQuery(WIDE);
  const [data, setData] = useState<TagItemsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [building, setBuilding] = useState<string | null>(null);
  const [openCard, setOpenCard] = useState<Card | null>(null);
  const [view, setView] = useState<PageView>(() => {
    const v = readJSON<Partial<PageView>>(PAGE_KEY, {});
    return {
      status: target.status ?? 'kept',
      sort: v.sort && TAG_SORTS.includes(v.sort) ? v.sort : 'signal',
      dir: v.dir === 'asc' ? 'asc' : 'desc',
    };
  });
  const change = (patch: Partial<PageView>) =>
    setView((v) => {
      const next = { ...v, ...patch };
      writeJSON(PAGE_KEY, { sort: next.sort, dir: next.dir }); // the status follows where you came from
      return next;
    });

  useEffect(() => {
    const ctl = new AbortController();
    setData(null);
    setError(null);
    api
      .tagItems(target.tag, view.status, ctl.signal)
      .then(setData)
      .catch((err) => {
        if (ctl.signal.aborted || err instanceof AuthError) return;
        setError(isNetworkError(err) ? 'This tag needs a connection the first time.' : (err as Error).message);
      });
    return () => ctl.abort();
  }, [target.tag, view.status, online]);

  const items = useMemo(() => sortTagItems(data?.items ?? [], view.sort, view.dir), [data, view.sort, view.dir]);

  const buildTraining = async () => {
    setBuilding('Starting…');
    try {
      await api.buildTraining(data?.tag ?? target.tag);
      navigate('train');
    } catch (err) {
      setBuilding(isNetworkError(err) ? 'Building training needs a connection.' : (err as Error).message);
    }
  };

  // Kept, analyzed videos open their notes (on a phone); others open the info sheet.
  const open = (c: Card) => {
    if (!wide && !embedded && c.status === 'kept' && c.analysis_status === 'done') setOpenCard(c);
    else info.open({ kind: 'video', card: c });
  };
  if (openCard) return <ItemDetailView card={openCard} onBack={() => setOpenCard(null)} />;

  const [descWord, ascWord] = TAG_DIR_WORDS[view.sort];
  const s = data?.summary;
  const what = view.status === 'all' ? '' : view.status === 'inbox' ? ' in the deck' : ` ${view.status}`;

  return (
    <section className="page" aria-label={`Tag: ${target.tag}`}>
      <header className="page-head">
        {onBack ? (
          <button className="link-btn" onClick={onBack}>
            {backText ?? '‹ Back'}
          </button>
        ) : (
          <span />
        )}
        <span className="muted small">Tag</span>
      </header>
      <div className="scroll page-body tag-page">
        <h1 className="tag-page-title">{data?.tag ?? target.tag}</h1>
        {s && (
          <dl className="counts tag-summary">
            <div>
              <dt>Videos{what}</dt>
              <dd>{s.count.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Total time</dt>
              <dd>{minutes(s.minutes) || '0 min'}</dd>
            </div>
            <div>
              <dt>Analyzed</dt>
              <dd>{s.analyzed.toLocaleString()}</dd>
            </div>
          </dl>
        )}
        <button className="secondary train-from-tag" onClick={() => void buildTraining()} disabled={building === 'Starting…' || !online}>
          🎓 Build training from this tag
        </button>
        {building && building !== 'Starting…' && <p className="note small">{building}</p>}

        <div className="tag-controls">
          <div className="segmented" role="tablist" aria-label="Show">
            {STATUS_CHOICES.map(([k, label]) => (
              <button key={k} role="tab" aria-selected={view.status === k} className={view.status === k ? 'on' : ''} onClick={() => change({ status: k })}>
                {label}
              </button>
            ))}
          </div>
          <div className="lib-row">
            <label className="lib-select">
              <span>Sort</span>
              <select value={view.sort} onChange={(e) => change({ sort: e.target.value as TagSort })}>
                {TAG_SORTS.map((k) => (
                  <option key={k} value={k}>
                    {TAG_SORT_LABELS[k]}
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
          </div>
        </div>

        {error && <p className="note">{error}</p>}
        {!data && !error && <p className="note">Loading…</p>}
        {data && items.length === 0 && (
          <p className="note">
            {view.status === 'kept' ? 'No kept videos with this tag. Try Inbox or All.' : 'No videos here with this tag.'}
          </p>
        )}
        <ul className="rows">
          {items.map((x) => (
            <ItemRow key={x.id} card={tagItemCard(x)} onOpen={open} note={tagItemNote(x, view.status === 'all')} />
          ))}
        </ul>
      </div>
    </section>
  );
}
