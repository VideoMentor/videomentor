// Small, pure helpers for the Insights screen.
import type { KeepRate, UsageTotals } from './types';

/** "76%" from 0.756 (or from 75.6, in case the engine sends a percent). Empty when unknown. */
export function percent(rate: number | null | undefined): string {
  if (rate === null || rate === undefined || !Number.isFinite(rate)) return '';
  return `${Math.round(rate > 1 ? rate : rate * 100)}%`;
}

/** 0 to 1, for a bar's width. */
export function fraction(rate: number | null | undefined): number {
  if (rate === null || rate === undefined || !Number.isFinite(rate)) return 0;
  const f = rate > 1 ? rate / 100 : rate;
  return Math.max(0, Math.min(1, f));
}

export interface KeepRateRow {
  signal: number;
  raw: number | null;
  rawN: number;
  clean: number | null;
  cleanN: number;
}

/** Raw and clean keep rates side by side, one row per signal, lowest signal first. */
export function keepRateRows(raw: KeepRate[] | undefined, clean: KeepRate[] | undefined): KeepRateRow[] {
  const rows = new Map<number, KeepRateRow>();
  const row = (signal: number) => {
    let r = rows.get(signal);
    if (!r) rows.set(signal, (r = { signal, raw: null, rawN: 0, clean: null, cleanN: 0 }));
    return r;
  };
  for (const k of raw ?? []) {
    const r = row(k.signal);
    r.raw = k.rate ?? null;
    r.rawN = (k.kept ?? 0) + (k.archived ?? 0);
  }
  for (const k of clean ?? []) {
    const r = row(k.signal);
    r.clean = k.rate ?? null;
    r.cleanN = (k.kept ?? 0) + (k.archived ?? 0);
  }
  return [...rows.values()].sort((a, b) => a.signal - b.signal);
}

/** A median in hours, in words. */
export function formatHours(h: number | null | undefined): string {
  if (h === null || h === undefined || !Number.isFinite(h)) return 'No data yet';
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
  if (h < 48) {
    const v = Math.round(h * 10) / 10;
    return `${v} ${v === 1 ? 'hour' : 'hours'}`;
  }
  return `${Math.round((h / 24) * 10) / 10} days`;
}

export function tokenTotal(u: UsageTotals | undefined): number {
  if (!u) return 0;
  return (u.input_tokens ?? 0) + (u.output_tokens ?? 0) + (u.cache_read_tokens ?? 0) + (u.cache_creation_tokens ?? 0);
}

export function formatCost(usd: number | null | undefined): string {
  if (!usd || !Number.isFinite(usd) || usd <= 0) return '$0.00';
  if (usd < 0.005) return '<$0.01';
  return `$${usd.toFixed(2)}`;
}
