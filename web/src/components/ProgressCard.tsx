// Your progress: the numbers milestones celebrate.
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import type { Progress } from '../lib/types';

export function ProgressCard({ online }: { online: boolean }) {
  const [p, setP] = useState<Progress | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    api
      .progress(ctl.signal)
      .then(setP)
      .catch(() => {});
    return () => ctl.abort();
  }, [online]);
  if (!p) return null;
  return (
    <div className="card-block progress-card">
      <h4>Your progress</h4>
      <div className="progress-stats">
        <div>
          <b>{p.decided.toLocaleString()}</b>
          <span>videos triaged</span>
        </div>
        <div>
          <b>{p.hours.toLocaleString()}</b>
          <span>hours sorted</span>
        </div>
        <div>
          <b>{p.streak_days}</b>
          <span>day streak</span>
        </div>
        <div>
          <b>{p.today}</b>
          <span>today</span>
        </div>
      </div>
    </div>
  );
}
