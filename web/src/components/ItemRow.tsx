import { formatMinutes, thumbnailOf } from '../lib/format';
import type { Card } from '../lib/types';
import { useInfo } from '../state/info';

export function ItemRow({ card, onOpen, note, selected = false }: { card: Card; onOpen(c: Card): void; note?: string; selected?: boolean }) {
  const { open } = useInfo();
  return (
    <li className="row-wrap">
      <button className={`row${selected ? ' selected' : ''}`} onClick={() => onOpen(card)} aria-current={selected || undefined}>
        <img className="row-thumb" src={thumbnailOf(card)} alt="" loading="lazy" />
        <span className="row-text">
          <span className="row-title">{card.title}</span>
          <small>{[card.channel, formatMinutes(card.duration_s), note].filter(Boolean).join(' · ')}</small>
          {card.summary_short && <span className="row-summary">{card.summary_short}</span>}
        </span>
      </button>
      <button className="info-btn row-info" aria-label={`Info: ${card.title}`} onClick={() => open({ kind: 'video', card })}>
        i
      </button>
    </li>
  );
}
