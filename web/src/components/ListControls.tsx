// Sort, group and (for Library) kept/archived filter, shared by Library and Ready.
// The page title toggles them; the choice is remembered per list.
import { useState } from 'react';
import {
  DIR_WORDS,
  SORT_LABELS,
  type CardGroup,
  type LibraryCard,
  type GroupOrder,
  type LibraryGroup,
  type LibrarySort,
  type LibraryStatus,
  type ListView,
} from '../lib/libraryView';
import { readJSON, writeJSON } from '../state/storage';
import { ItemRow } from './ItemRow';

export function useListView(storageKey: string, defaults: ListView, sorts: LibrarySort[]) {
  const [view, setView] = useState<ListView>(() => {
    const v = readJSON<Partial<ListView>>(storageKey, {});
    return {
      status: ['kept', 'archived', 'processed'].includes(v.status as string) ? (v.status as LibraryStatus) : defaults.status,
      sort: v.sort && sorts.includes(v.sort) ? v.sort : defaults.sort,
      dir: v.dir === 'asc' || v.dir === 'desc' ? v.dir : defaults.dir,
      group: ['none', 'playlist', 'tag', 'channel'].includes(v.group as string) ? (v.group as LibraryGroup) : defaults.group,
      groupOrder: ['most', 'fewest', 'name'].includes(v.groupOrder as string) ? (v.groupOrder as GroupOrder) : defaults.groupOrder,
      controls: typeof v.controls === 'boolean' ? v.controls : defaults.controls,
    };
  });
  const change = (patch: Partial<ListView>) =>
    setView((v) => {
      const next = { ...v, ...patch };
      writeJSON(storageKey, next);
      return next;
    });
  return [view, change] as const;
}

/** The page title as a button that shows or hides the list controls. */
export function ToggleTitle({ title, open, onToggle }: { title: string; open: boolean; onToggle(): void }) {
  return (
    <button className="title-toggle" onClick={onToggle} aria-expanded={open} aria-label={`${title}: ${open ? 'hide' : 'show'} sort and group`}>
      <h1>{title}</h1>
      <span className="title-caret" aria-hidden="true">
        {open ? '▴' : '▾'}
      </span>
    </button>
  );
}

export function ListControls({
  view,
  change,
  sorts,
  showStatus,
}: {
  view: ListView;
  change(p: Partial<ListView>): void;
  sorts: LibrarySort[];
  showStatus: boolean;
}) {
  const [descWord, ascWord] = DIR_WORDS[view.sort];
  return (
    <div className="lib-controls">
      {showStatus && (
        <div className="segmented" role="tablist" aria-label="Show">
          {(
            [
              ['kept', 'Kept'],
              ['archived', 'Archived'],
              ['processed', 'Both'],
            ] as const
          ).map(([k, label]) => (
            <button key={k} role="tab" aria-selected={view.status === k} className={view.status === k ? 'on' : ''} onClick={() => change({ status: k })}>
              {label}
            </button>
          ))}
        </div>
      )}
      <div className="lib-row">
        <label className="lib-select">
          <span>Sort</span>
          <select value={view.sort} onChange={(e) => change({ sort: e.target.value as LibrarySort })}>
            {sorts.map((k) => (
              <option key={k} value={k}>
                {SORT_LABELS[k]}
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
        <label className="lib-select">
          <span>Group</span>
          <select value={view.group} onChange={(e) => change({ group: e.target.value as LibraryGroup })}>
            <option value="none">None</option>
            <option value="playlist">Playlist</option>
            <option value="tag">Tag</option>
            <option value="channel">Channel</option>
          </select>
        </label>
        {view.group !== 'none' && (
          <label className="lib-select">
            <span>Groups</span>
            <select value={view.groupOrder} onChange={(e) => change({ groupOrder: e.target.value as GroupOrder })}>
              <option value="most">Most videos</option>
              <option value="fewest">Fewest videos</option>
              <option value="name">A to Z</option>
            </select>
          </label>
        )}
      </div>
    </div>
  );
}

/** Rows, flat or under collapsible group headers (many groups start closed). */
export function GroupedRows({
  groups,
  grouped,
  onOpen,
  note,
  selectedId,
  onGroupInfo,
}: {
  groups: CardGroup<LibraryCard>[];
  grouped: boolean;
  onOpen(c: LibraryCard): void;
  note(c: LibraryCard): string;
  selectedId?: string | null;
  /** When set, each group header gets an ⓘ (used for channel groups). */
  onGroupInfo?(group: CardGroup<LibraryCard>): void;
}) {
  const [flipped, setFlipped] = useState<Set<string>>(new Set());
  const startOpen = groups.length <= 6;
  const isOpen = (k: string) => (startOpen ? !flipped.has(k) : flipped.has(k));
  const toggle = (k: string) =>
    setFlipped((s) => {
      const n = new Set(s);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });

  if (!grouped) {
    return (
      <ul className="rows">
        {groups[0]?.items.map((c) => (
          <ItemRow key={c.id} card={c} onOpen={onOpen} note={note(c)} selected={c.id === selectedId} />
        ))}
      </ul>
    );
  }
  return (
    <>
      {groups.map((g) => (
        <section key={g.key} className="lib-group">
          <div className="lib-group-bar">
            <button className="lib-group-head" onClick={() => toggle(g.key)} aria-expanded={isOpen(g.key)}>
              <span aria-hidden="true">{isOpen(g.key) ? '▾' : '▸'}</span>
              <b>{g.label}</b>
              <span className="muted">{g.items.length}</span>
            </button>
            {onGroupInfo && g.key !== 'unknown channel' && (
              <button className="info-btn inline" aria-label={`About ${g.label}`} onClick={() => onGroupInfo(g)}>
                i
              </button>
            )}
          </div>
          {isOpen(g.key) && (
            <ul className="rows">
              {g.items.map((c) => (
                <ItemRow key={`${g.key}-${c.id}`} card={c} onOpen={onOpen} note={note(c)} selected={c.id === selectedId} />
              ))}
            </ul>
          )}
        </section>
      ))}
    </>
  );
}
