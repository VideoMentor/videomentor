import { forwardRef, useEffect, useImperativeHandle, useRef, useState, type PointerEvent } from 'react';
import {
  LONG_PRESS_MS,
  TAP_SLOP,
  VelocityTracker,
  armedAction,
  classifySwipe,
  isTap,
  stampOpacities,
  type SwipeAction,
} from '../lib/gesture';
import { byline, formatDuration, savedBadge, savedLine, signalLabel, thumbnailOf } from '../lib/format';
import type { Card } from '../lib/types';
import { vibrate } from '../state/hooks';
import { touches } from '../state/events';
import { useInfo } from '../state/info';
import { CardBack } from './CardBack';

export interface SwipeCardHandle {
  fling(action: SwipeAction): void;
}

interface Props {
  card: Card;
  /** Called after the fly-out animation. A promise (group) holds the card until it settles. */
  onAction(action: SwipeAction): void | Promise<unknown>;
}

const STAMPS: { action: SwipeAction; label: string }[] = [
  { action: 'keep', label: 'KEEP' },
  { action: 'archive', label: 'ARCHIVE' },
  { action: 'group', label: 'GROUP ⧉' },
  { action: 'prioritize', label: 'PRIORITY ⚡' },
];

const FLY_MS = 260;

export const SwipeCard = forwardRef<SwipeCardHandle, Props>(function SwipeCard({ card, onAction }, ref) {
  const el = useRef<HTMLDivElement>(null);
  const stampEls = useRef<Partial<Record<SwipeAction, HTMLDivElement | null>>>({});
  const [flipped, setFlipped] = useState(false);
  const [pressing, setPressing] = useState(false);
  const g = useRef({
    pointer: -1,
    sx: 0,
    sy: 0,
    dx: 0,
    dy: 0,
    t0: 0,
    moved: false,
    long: false,
    timer: 0 as ReturnType<typeof setTimeout> | 0,
    armed: null as SwipeAction | null,
    busy: false,
    tracker: new VelocityTracker(),
  });

  useEffect(() => () => clearTimeout(g.current.timer || undefined), []);

  const setStamps = (dx: number, dy: number) => {
    const o = stampOpacities(dx, dy);
    for (const { action } of STAMPS) {
      const s = stampEls.current[action];
      if (s) s.style.opacity = String(o[action]);
    }
  };

  const showStamp = (action: SwipeAction) => {
    for (const { action: a } of STAMPS) {
      const s = stampEls.current[a];
      if (s) s.style.opacity = a === action ? '1' : '0';
    }
  };

  const springBack = () => {
    const e = el.current;
    if (!e) return;
    e.style.transition = 'transform .3s cubic-bezier(.2,.9,.3,1.2), opacity .2s';
    e.style.transform = '';
    e.style.opacity = '';
    setStamps(0, 0);
  };

  const commit = (action: SwipeAction) => {
    const e = el.current;
    if (!e || g.current.busy) return;
    g.current.busy = true;
    vibrate(15);
    showStamp(action);

    if (action === 'group') {
      // Lift the card while the group is gathered; spring back either way
      // (the sheet covers it, or we're offline and nothing happened).
      e.style.transition = 'transform .2s ease-out';
      e.style.transform = 'translate3d(0,-60px,0) scale(.97)';
      Promise.resolve(onAction('group')).finally(() => {
        g.current.busy = false;
        springBack();
      });
      return;
    }

    const w = window.innerWidth;
    const h = window.innerHeight;
    const { dx, dy } = g.current;
    const fly: Record<Exclude<SwipeAction, 'group'>, string> = {
      keep: `translate3d(${w * 1.2}px, ${dy}px, 0) rotate(22deg)`,
      archive: `translate3d(${-w * 1.2}px, ${dy}px, 0) rotate(-22deg)`,
      prioritize: `translate3d(${dx}px, ${h}px, 0)`,
    };
    e.style.transition = `transform ${FLY_MS}ms ease-in, opacity ${FLY_MS}ms ease-in`;
    e.style.transform = fly[action];
    e.style.opacity = '0';
    setTimeout(() => {
      void onAction(action);
    }, FLY_MS - 20);
  };

  useImperativeHandle(ref, () => ({ fling: (a) => commit(a) }));

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    const s = g.current;
    if (s.busy || s.pointer !== -1) return;
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    s.pointer = e.pointerId;
    s.sx = e.clientX;
    s.sy = e.clientY;
    s.dx = 0;
    s.dy = 0;
    s.t0 = e.timeStamp;
    s.moved = false;
    s.long = false;
    s.armed = null;
    s.tracker.reset();
    s.tracker.add(e.clientX, e.clientY, e.timeStamp);
    if (el.current) el.current.style.transition = 'none';
    s.timer = setTimeout(() => {
      if (!s.moved && s.pointer !== -1) {
        s.long = true;
        vibrate(25);
        setPressing(true);
      }
    }, LONG_PRESS_MS);
  };

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const s = g.current;
    if (e.pointerId !== s.pointer) return;
    s.dx = e.clientX - s.sx;
    s.dy = e.clientY - s.sy;
    s.tracker.add(e.clientX, e.clientY, e.timeStamp);
    if (!s.moved && Math.hypot(s.dx, s.dy) > TAP_SLOP) {
      s.moved = true;
      clearTimeout(s.timer || undefined);
      if (s.long) {
        s.long = false;
        setPressing(false);
      }
    }
    if (!s.moved || !el.current) return;
    el.current.style.transform = `translate3d(${s.dx}px, ${s.dy}px, 0) rotate(${s.dx / 18}deg)`;
    setStamps(s.dx, s.dy);
    const armed = armedAction(s.dx, s.dy);
    if (armed !== s.armed) {
      if (armed) vibrate(8);
      s.armed = armed;
    }
  };

  const onPointerUp = (e: PointerEvent<HTMLDivElement>) => {
    const s = g.current;
    if (e.pointerId !== s.pointer) return;
    s.pointer = -1;
    clearTimeout(s.timer || undefined);
    s.tracker.add(e.clientX, e.clientY, e.timeStamp);

    if (s.long && !s.moved) {
      // Opened on release, not on the timer, so it counts as a user gesture
      // and isn't blocked as a pop-up.
      s.long = false;
      setPressing(false);
      window.open(card.url, '_blank', 'noopener,noreferrer');
      touches.track('open', card.id);
      springBack();
      return;
    }
    if (!s.moved) {
      if (isTap(s.dx, s.dy, e.timeStamp - s.t0)) {
        if (!flipped) touches.track('flip', card.id);
        setFlipped((f) => !f);
      }
      springBack();
      return;
    }
    const { vx, vy } = s.tracker.velocity();
    const action = classifySwipe(s.dx, s.dy, vx, vy);
    if (action) commit(action);
    else springBack();
  };

  const onPointerCancel = (e: PointerEvent<HTMLDivElement>) => {
    const s = g.current;
    if (e.pointerId !== s.pointer) return;
    s.pointer = -1;
    clearTimeout(s.timer || undefined);
    s.long = false;
    setPressing(false);
    springBack();
  };

  const duration = formatDuration(card.duration_s);
  const saved = savedLine(card);

  return (
    <div
      ref={el}
      className={`card top${pressing ? ' pressing' : ''}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onContextMenu={(e) => e.preventDefault()}
      role="group"
      aria-roledescription="swipe card"
      aria-label={`${card.title}. Swipe right to keep, left to archive, up to group, down to prioritize. Tap to flip.`}
    >
      <div className={`flipper${flipped ? ' flipped' : ''}`}>
        <div className="face front" aria-hidden={flipped}>
          <CardFront card={card} duration={duration} saved={saved} interactive />
        </div>
        <div className="face back" aria-hidden={!flipped}>
          <CardBack card={card} active={flipped} />
        </div>
      </div>
      {STAMPS.map(({ action, label }) => (
        <div
          key={action}
          className={`stamp ${action}`}
          ref={(n) => {
            stampEls.current[action] = n;
          }}
          aria-hidden="true"
        >
          {label}
        </div>
      ))}
      {pressing && <div className="press-hint">Release to open on YouTube</div>}
    </div>
  );
});

export function CardFront({
  card,
  duration,
  saved,
  interactive = false,
}: {
  card: Card;
  duration: string;
  saved: string;
  interactive?: boolean;
}) {
  const [imgFailed, setImgFailed] = useState(false);
  const { open } = useInfo();
  const { posted, by } = byline(card);
  const tags = card.tags?.length ? card.tags : card.topics;
  return (
    <>
      <div className="thumb">
        {!imgFailed && (
          <img src={thumbnailOf(card)} alt="" draggable={false} onError={() => setImgFailed(true)} decoding="async" />
        )}
        <span className="src">{savedBadge(card)}</span>
        {interactive && (
          <button
            className="info-btn"
            aria-label="Video info"
            onPointerDown={(e) => e.stopPropagation()}
            onPointerUp={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              open({ kind: 'video', card });
            }}
          >
            i
          </button>
        )}
        {duration && <span className="dur">{duration}</span>}
      </div>
      <div className="body">
        <h3 className="title">{card.title}</h3>
        {(posted || by) && (
          <div className="byline">
            {posted && (
              <span>
                <span className="byline-label">Posted</span> {posted}
              </span>
            )}
            {by && (
              <span>
                <span className="byline-label">by</span> <b>{by}</b>
              </span>
            )}
          </div>
        )}
        {(saved || card.priority > 0) && (
          <div className="meta">
            {saved}
            {card.priority ? <span className="prio-flag">{saved ? ' · ' : ''}⚡ prioritized</span> : null}
          </div>
        )}
        {(card.signal || card.key_moment) && (
          <div className="signal-row">
            {card.signal ? (
              <span className={`signal s${card.signal}`} title={card.signal_reason ?? ''}>
                {signalLabel(card)}
              </span>
            ) : null}
            {card.key_moment && (
              <span className="key-idea">Key idea at {formatDuration(card.key_moment.t) || '0:00'}</span>
            )}
          </div>
        )}
        {card.core_idea ? (
          <div className="why">
            <span>Core idea</span>
            {card.core_idea}
          </div>
        ) : (
          card.why && (
            <div className="why">
              <span>Why you saved it</span>
              {card.why}
            </div>
          )
        )}
        {tags.length > 0 && (
          <div className="chips">
            {tags.slice(0, 4).map((t) => (
              <span className="chip" key={t}>
                {t}
              </span>
            ))}
          </div>
        )}
        <div className="hint">Tap to flip · drag to decide · hold to open</div>
      </div>
    </>
  );
}

/** The non-interactive card peeking out behind the top one. */
export function BehindCard({ card }: { card: Card }) {
  return (
    <div className="card behind" aria-hidden="true">
      <div className="flipper">
        <div className="face front">
          <CardFront card={card} duration={formatDuration(card.duration_s)} saved={savedLine(card)} />
        </div>
      </div>
    </div>
  );
}
