import type { BackupSummary } from './types';

export function formatBytes(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`;
  if (n >= 1024 ** 2) return `${Math.round(n / 1024 ** 2)} MB`;
  return `${Math.max(1, Math.round(n / 1024))} KB`;
}

/** "Backups: daily, last 3:00 AM today, 14 kept (92 MB)", or "No backup yet". */
export function backupLine(s: BackupSummary | undefined, now = Date.now()): string {
  if (!s || !s.last_at || !s.count) return 'No backup yet';
  const t = new Date(s.last_at);
  if (Number.isNaN(t.getTime())) return 'No backup yet';
  const time = t.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOfDay(new Date(now)) - startOfDay(t)) / 86_400_000);
  const when =
    days <= 0 ? 'today' : days === 1 ? 'yesterday' : t.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  return `Backups: daily, last ${time} ${when}, ${s.count} kept (${formatBytes(s.bytes)})`;
}
