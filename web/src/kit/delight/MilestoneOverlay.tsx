// Full-screen moment for a milestone: big number counting up, label, one stat line.
// Tap anywhere (or wait) to close.
import { useEffect, useState } from 'react';
import { dismissMilestone, milestoneFanfare, useMilestone } from './celebrate';

export function MilestoneOverlay({ onShown }: { onShown(id: string): void }) {
  const m = useMilestone();
  const [shown, setShown] = useState(0);

  useEffect(() => {
    if (!m) return;
    onShown(m.id);
    milestoneFanfare();
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (reduce) {
      setShown(m.value);
    } else {
      const start = performance.now();
      let raf = 0;
      const tick = (t: number) => {
        const k = Math.min(1, (t - start) / 900);
        setShown(Math.round(m.value * (1 - Math.pow(1 - k, 3))));
        if (k < 1) raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
      const close = setTimeout(dismissMilestone, 7000);
      return () => {
        cancelAnimationFrame(raf);
        clearTimeout(close);
      };
    }
    const close = setTimeout(dismissMilestone, 7000);
    return () => clearTimeout(close);
  }, [m?.id]); // re-run per milestone only; onShown is a stable callback

  if (!m) return null;
  const unit = m.label.replace(/^\d+[\s-]*/, '');
  return (
    <div className="milestone" role="dialog" aria-live="assertive" aria-label={m.label} onClick={dismissMilestone}>
      <div className="milestone-card">
        <div className="milestone-badge" aria-hidden="true">
          ★
        </div>
        <div className="milestone-number">{shown.toLocaleString()}</div>
        <div className="milestone-label">{unit}</div>
        {m.detail && <p className="milestone-detail">{m.detail}</p>}
        <p className="milestone-hint">Tap to continue</p>
      </div>
    </div>
  );
}
