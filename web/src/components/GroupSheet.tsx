import { formatMinutes, thumbnailOf } from '../lib/format';
import type { Card } from '../lib/types';
import type { GroupSheetState } from '../state/useTriage';

interface Props {
  sheet: GroupSheetState;
  onArchiveAll(): void;
  onOneByOne(): void;
  onKeepAll(): void;
  onClose(): void;
}

function relation(c: Card, anchor: Card, basis: string): string {
  if (c.id === anchor.id) return 'this card';
  if (anchor.channel && c.channel === anchor.channel) return 'same creator';
  if (c.topics.some((t) => anchor.topics.includes(t))) return 'same topic';
  return basis === 'channel' ? 'same creator' : 'same topic';
}

export function GroupSheet({ sheet, onArchiveAll, onOneByOne, onKeepAll, onClose }: Props) {
  const { group, items, anchor, busy, error } = sheet;
  const total = items.reduce((s, c) => s + (c.duration_s ?? 0), 0);
  const basis = group.basis === 'channel' ? 'channel' : 'topic';
  return (
    <div className="sheet-backdrop" role="dialog" aria-modal="true" aria-labelledby="group-title">
      <div className="sheet">
        <div className="sheet-head">
          <button className="link-btn" onClick={onClose} aria-label="Close group and go back to the card">
            ‹ New group
          </button>
          <span className="pill group-pill">
            {items.length > 1 ? `${items.length - 1} related` : 'none related yet'}
          </span>
        </div>
        <div className="why-group" id="group-title">
          Grouped by {basis}: “{group.label}”
        </div>
        <div className="stackwrap" aria-hidden="true">
          {items.length > 2 && <div className="mini m3" />}
          {items.length > 1 && <div className="mini m2" />}
          <div className="mini m1">
            <img src={thumbnailOf(anchor)} alt="" />
            <div className="mini-label">
              {group.label}
              <small>
                {items.length} video{items.length === 1 ? '' : 's'}
                {total ? ` · ${formatMinutes(total)}` : ''}
              </small>
            </div>
          </div>
        </div>
        <ul className="list scroll" aria-label="Videos in this group">
          {items.map((c) => (
            <li className="li" key={c.id}>
              <img className="sw" src={thumbnailOf(c)} alt="" loading="lazy" />
              <div>
                {c.title}
                <br />
                <small>{[formatMinutes(c.duration_s), relation(c, anchor, basis)].filter(Boolean).join(' · ')}</small>
              </div>
            </li>
          ))}
        </ul>
        {items.length <= 1 && (
          <p className="sheet-note">
            Nothing else in your inbox shares this topic or creator yet. More cards get labeled as they're prepped.
          </p>
        )}
        {error && <p className="sheet-error" role="alert">{error}</p>}
        <div className="three">
          <button className="b-archive" onClick={onArchiveAll} disabled={busy} aria-label={`Archive all ${items.length}`}>
            Archive all
          </button>
          <button className="b-group" onClick={onOneByOne} disabled={busy} aria-label="Swipe them one by one">
            One by one
          </button>
          <button className="b-keep" onClick={onKeepAll} disabled={busy} aria-label={`Keep all ${items.length}`}>
            Keep all
          </button>
        </div>
      </div>
    </div>
  );
}
