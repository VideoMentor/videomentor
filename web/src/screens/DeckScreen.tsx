import { useCallback, useEffect, useRef, useState } from 'react';
import { BehindCard, SwipeCard, type SwipeCardHandle } from '../components/SwipeCard';
import { GroupSheet } from '../components/GroupSheet';
import { progress } from '../lib/deck';
import type { SwipeAction } from '../lib/gesture';
import type { Card } from '../lib/types';
import type { Triage } from '../state/useTriage';
import { api } from '../lib/api';
import { SourceSheet } from '../components/SourceSheet';
import { round as celebrateRound } from '../kit/delight/celebrate';
import { scheduleMilestoneCheck } from '../state/milestones';
import { ItemDetailView } from '../components/ItemDetailView';
import { WIDE, useMediaQuery } from '../state/hooks';
import { UNDO_LIMIT } from '../lib/undoHistory';
import { orderLabel } from '../state/source';
import { formatPosted } from '../lib/format';

interface Props {
  t: Triage;
  online: boolean;
  queued: number;
}

export function DeckScreen({ t, online, queued }: Props) {
  const top = useRef<SwipeCardHandle>(null);
  const [picking, setPicking] = useState(false);
  const wide = useMediaQuery(WIDE);
  const { state } = t;
  const card = state.cards[0];
  const behind = state.cards[1];
  const p = progress(state);

  const onAction = useCallback(
    (c: Card, action: SwipeAction) => {
      if (action === 'group') return t.requestGroup(c);
      t.decide(c, action);
    },
    [t],
  );

  // Arrow keys on a desktop browser do the same as swipes.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (t.sheet || !top.current || e.target instanceof HTMLInputElement) return;
      const map: Record<string, SwipeAction> = {
        ArrowRight: 'keep',
        ArrowLeft: 'archive',
        ArrowUp: 'group',
        ArrowDown: 'prioritize',
      };
      const a = map[e.key];
      if (a) {
        e.preventDefault();
        top.current.fling(a);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [t.sheet]);

  const fling = (a: SwipeAction) => top.current?.fling(a);

  return (
    <div className={wide ? 'deck-wide' : 'deck-narrow'}>
    <section className="deck-screen" aria-label="Deck">
      <header className="topbar">
        <b className="topbar-title">Deck</b>
        <div className="topbar-right">
          {!online && (
            <span className="pill offline" title="Offline. Swipes are saved and sent later.">
              Offline{queued ? ` · ${queued}` : ''}
            </span>
          )}
          {card && (
            <span className="pill" aria-label={`Card ${p.position} of ${p.total}`}>
              {p.position} of {p.total}
            </span>
          )}
          <button
            className="icon-btn undo-btn"
            onClick={() => void t.undo()}
            disabled={!t.canUndo}
            aria-label={t.undoCount ? `Undo last decision, ${t.undoCount} available` : 'Nothing to undo'}
            title={`Undo (${t.undoCount} of the last ${UNDO_LIMIT} kept)`}
          >
            ↶{t.undoCount > 0 && <span className="undo-count">{t.undoCount}</span>}
          </button>
        </div>
      </header>
      <button className="source-btn" onClick={() => setPicking(true)} aria-label={`Deck source: ${t.source.label}. Change`}>
        <span className="muted">From</span> <b>{t.source.label}</b>
        {t.order.sort !== 'default' && <span className="muted"> · {orderLabel(t.order, (d) => formatPosted(d, false))}</span>}{' '}
        <span aria-hidden="true">▾</span>
      </button>
      <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={p.total} aria-valuenow={state.decided}>
        <i style={{ width: `${Math.round(p.fraction * 100)}%` }} />
      </div>

      <div className="deck">
        {card ? (
          <>
            {behind && <BehindCard key={`b-${behind.id}`} card={behind} />}
            <SwipeCard key={card.id} ref={top} card={card} onAction={(a) => onAction(card, a)} />
          </>
        ) : (
          <EmptyDeck t={t} online={online} />
        )}
      </div>

      <div className="actions">
        <button className="btn a" onClick={() => fling('archive')} disabled={!card} aria-label="Archive" title="Archive (swipe left)">
          ✕
        </button>
        <button className="btn small p" onClick={() => fling('prioritize')} disabled={!card} aria-label="Keep and analyze first" title="Prioritize (swipe down)">
          ⚡
        </button>
        <button className="btn small g" onClick={() => fling('group')} disabled={!card} aria-label="Group related videos" title="Group (swipe up)">
          ⧉
        </button>
        <button className="btn k" onClick={() => fling('keep')} disabled={!card} aria-label="Keep" title="Keep (swipe right)">
          ✓
        </button>
      </div>

      {picking && <SourceSheet onClose={() => setPicking(false)} />}
      {t.sheet && (
        <GroupSheet
          sheet={t.sheet}
          onArchiveAll={() => void t.groupDecide('archive')}
          onKeepAll={() => void t.groupDecide('keep')}
          onOneByOne={t.groupOneByOne}
          onClose={t.closeSheet}
        />
      )}
    </section>
    {wide && (
      <aside className="deck-detail" aria-label="Details for the top card">
        {card ? (
          <ItemDetailView key={card.id} card={card} embedded />
        ) : (
          <div className="empty">
            <p className="note">The top card's details show here.</p>
          </div>
        )}
      </aside>
    )}
    </div>
  );
}

function EmptyDeck({ t, online }: { t: Triage; online: boolean }) {
  const { state, loading, error } = t;
  const cleared = !loading && state.decided > 0;
  // A finished round: chord and confetti once, then look for milestones.
  useEffect(() => {
    if (!cleared) return;
    celebrateRound();
    scheduleMilestoneCheck(1200);
  }, [cleared]);
  if (loading) {
    return (
      <div className="empty">
        <div className="spinner" aria-hidden="true" />
        <p>Dealing cards…</p>
      </div>
    );
  }
  if (state.decided > 0) {
    const { keep, archive, prioritize } = state.stats;
    const hasNext = !!state.next?.length;
    return (
      <div className="empty cleared">
        <h2>Deck cleared</h2>
        <ul className="tally" aria-label="This deck">
          <li className="k">
            <b>{keep + prioritize}</b> kept
          </li>
          <li className="a">
            <b>{archive}</b> archived
          </li>
          <li className="p">
            <b>{prioritize}</b> analyzing first
          </li>
        </ul>
        <button className="primary" onClick={t.nextRound}>
          Next 10
        </button>
        {!online && !hasNext && <p className="note">Offline: the next round comes from your offline pack.</p>}
      </div>
    );
  }
  if (!state.loaded || error) {
    const offline = !online || error === 'offline';
    return (
      <div className="empty">
        <h2>{offline ? 'You’re offline' : 'Couldn’t load the deck'}</h2>
        <p className="note">{offline ? 'The deck loads when you have signal.' : error}</p>
        <button className="primary" onClick={() => void t.refresh()}>
          {offline ? 'Use offline pack' : 'Try again'}
        </button>
      </div>
    );
  }
  if (t.source.key.startsWith('ch:')) return <PreparingChannel t={t} online={online} />;
  return (
    <div className="empty">
      <h2>Nothing left to triage</h2>
      <p className="note">
        {t.source.key === 'all'
          ? 'New videos show up after the next sync.'
          : `Nothing in “${t.source.label}” right now. Videos may still be getting tagged.`}
        {t.order.start ? ' Nothing more past the start date in this direction.' : ''}
      </p>
      <button className="secondary" onClick={() => void t.refresh()} disabled={!online}>
        Check again
      </button>
    </div>
  );
}

/** A channel deck right after a pull: its videos need a minute or two of tagging and scoring. */
function PreparingChannel({ t, online }: { t: Triage; online: boolean }) {
  const id = t.source.key.slice(3);
  const [preparing, setPreparing] = useState<number | null>(null);
  useEffect(() => {
    if (!online) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const check = async () => {
      try {
        const r = await api.pulledChannels();
        const c = r.channels.find((x) => x.channel_id === id);
        if (stop) return;
        setPreparing(c?.preparing ?? 0);
        if (c && c.preparing > 0) timer = setTimeout(() => void check(), 10_000);
        if (c && c.inbox > c.preparing) void t.refresh(); // some are ready: deal them
      } catch {
        if (!stop) timer = setTimeout(() => void check(), 20_000);
      }
    };
    void check();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [id, online]);
  if (preparing) {
    return (
      <div className="empty">
        <div className="spinner" aria-hidden="true" />
        <h2>Getting {preparing} {preparing === 1 ? 'video' : 'videos'} ready</h2>
        <p className="note">Tagging and scoring the videos you pulled. They appear here on their own, usually within a couple of minutes.</p>
      </div>
    );
  }
  return (
    <div className="empty">
      <h2>Nothing left to triage</h2>
      <p className="note">{`Nothing left from “${t.source.label}”. Pull more from the channel to keep going.`}</p>
      <button className="secondary" onClick={() => void t.refresh()} disabled={!online}>
        Check again
      </button>
    </div>
  );
}
