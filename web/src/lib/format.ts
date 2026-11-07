// Display helpers. Defensive on purpose: fields can be missing or oddly typed.
import type { Analysis, Card, Moment } from './types';

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds <= 0) return '';
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

export function formatMinutes(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) return '';
  const m = Math.round(seconds / 60);
  if (m === 0) return '<1 min';
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return m % 60 ? `${h}h ${m % 60}m` : `${h}h`;
}

export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '';
  const days = Math.floor((now - t) / 86_400_000);
  if (days < 1) return 'today';
  if (days < 2) return 'yesterday';
  if (days < 14) return `${days} days ago`;
  if (days < 60) return `${Math.floor(days / 7)} weeks ago`;
  if (days < 365) return `${Math.floor(days / 30)} months ago`;
  const years = Math.floor(days / 365);
  return years === 1 ? '1 year ago' : `${years} years ago`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return String(iso);
  return new Date(t).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

/** Seconds from a number, "754", "12:34", or "1:02:03". NaN when unusable. */
export function parseSeconds(t: unknown): number {
  if (typeof t === 'number') return Number.isFinite(t) && t >= 0 ? Math.floor(t) : NaN;
  if (typeof t !== 'string') return NaN;
  const s = t.trim();
  if (/^\d+(\.\d+)?$/.test(s)) return Math.floor(Number(s));
  if (/^\d+(:\d{1,2}){1,2}$/.test(s)) {
    return s.split(':').reduce((acc, part) => acc * 60 + Number(part), 0);
  }
  return NaN;
}

/** The video URL with `t=<seconds>s`, keeping any existing query string. */
export function momentUrl(url: string, seconds: number): string {
  try {
    const u = new URL(url);
    u.searchParams.set('t', `${seconds}s`);
    return u.toString();
  } catch {
    return `${url}${url.includes('?') ? '&' : '?'}t=${seconds}s`;
  }
}

export function thumbnailOf(card: Pick<Card, 'thumbnail' | 'video_id'>): string {
  return card.thumbnail || `https://i.ytimg.com/vi/${encodeURIComponent(card.video_id)}/hqdefault.jpg`;
}

export function sourceLabel(source: string): string {
  if (source === 'youtube:watch_later') return 'Watch Later';
  if (source === 'safari') return 'Safari bookmark';
  if (source.startsWith('chrome:')) return `Chrome bookmark (${source.slice(7)})`;
  return source;
}

export function primarySourceBadge(sources: string[] | undefined): string {
  if (!sources?.length) return 'YouTube';
  if (sources.includes('youtube:watch_later')) return 'Watch Later';
  if (sources.some((s) => s.startsWith('chrome:'))) return 'Chrome';
  if (sources.includes('safari')) return 'Safari';
  return 'YouTube';
}

function strings(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  return v.filter((x): x is string => typeof x === 'string' && x.trim() !== '');
}

export interface NormalizedAnalysis {
  core_idea: string;
  frameworks: { name: string; how: string }[];
  takeaways: string[];
  try_this_week: string[];
  key_moment: { seconds: number; label: string } | null;
  skills: string[];
  useful_for: string;
  summary: string;
  key_points: string[];
  moments: { seconds: number; label: string }[];
  learnings: string[];
  curriculum_topic: string;
  transcript_source: string;
}

/** Accepts an object, a JSON string, or junk; always returns a safe shape. */
export function normalizeAnalysis(raw: unknown): NormalizedAnalysis | null {
  let a: unknown = raw;
  if (typeof raw === 'string') {
    try {
      a = JSON.parse(raw);
    } catch {
      return raw.trim() ? { ...empty(), summary: raw } : null;
    }
  }
  if (!a || typeof a !== 'object') return null;
  const o = a as Analysis & Record<string, unknown>;
  const moments = (Array.isArray(o.moments) ? (o.moments as unknown[]) : [])
    .map((m) => {
      if (!m || typeof m !== 'object') return null;
      const mm = m as Partial<Moment>;
      const seconds = parseSeconds(mm.t);
      if (Number.isNaN(seconds)) return null;
      return { seconds, label: typeof mm.label === 'string' ? mm.label : '' };
    })
    .filter((m): m is { seconds: number; label: string } => m !== null);
  const km = o.key_moment && typeof o.key_moment === 'object' ? o.key_moment : null;
  const kmSeconds = km ? parseSeconds(km.t) : NaN;
  return {
    core_idea: typeof o.core_idea === 'string' ? o.core_idea : '',
    frameworks: (Array.isArray(o.frameworks) ? o.frameworks : [])
      .filter((f): f is { name: string; how: string } => !!f && typeof f === 'object' && typeof f.name === 'string')
      .map((f) => ({ name: f.name, how: typeof f.how === 'string' ? f.how : '' })),
    takeaways: strings(o.takeaways),
    try_this_week: strings(o.try_this_week),
    key_moment: km && !Number.isNaN(kmSeconds) ? { seconds: kmSeconds, label: typeof km.label === 'string' ? km.label : '' } : null,
    skills: strings(o.skills),
    useful_for: typeof o.useful_for === 'string' ? o.useful_for : '',
    summary: typeof o.summary === 'string' ? o.summary : '',
    key_points: strings(o.key_points),
    moments,
    learnings: strings(o.learnings),
    curriculum_topic: typeof o.curriculum_topic === 'string' ? o.curriculum_topic : '',
    transcript_source: typeof o.transcript_source === 'string' ? o.transcript_source : '',
  };
}

function empty(): NormalizedAnalysis {
  return {
    core_idea: '',
    frameworks: [],
    takeaways: [],
    try_this_week: [],
    key_moment: null,
    skills: [],
    useful_for: '',
    summary: '',
    key_points: [],
    moments: [],
    learnings: [],
    curriculum_topic: '',
    transcript_source: '',
  };
}

/** Coerce a card from the server into the shape the UI relies on. */
export function normalizeCard<T extends Card>(c: T): T {
  return {
    ...c,
    topics: Array.isArray(c.topics) ? c.topics.filter((t) => typeof t === 'string') : [],
    // Cards cached by older versions may have no tags or post time.
    tags: Array.isArray(c.tags) ? c.tags.filter((t) => typeof t === 'string') : [],
    posted_at: typeof c.posted_at === 'string' ? c.posted_at : null,
    posted_exact: c.posted_exact === true,
    saved_in_labels: Array.isArray(c.saved_in_labels) ? c.saved_in_labels.filter((t) => typeof t === 'string') : [],
    sources: Array.isArray(c.sources) ? c.sources.filter((t) => typeof t === 'string') : [],
    title: c.title || 'Untitled video',
  };
}

export function excerpt(text: string | null | undefined, max = 280): string {
  if (!text) return '';
  const clean = text.replace(/\s+/g, ' ').trim();
  if (clean.length <= max) return clean;
  const cut = clean.slice(0, max);
  const space = cut.lastIndexOf(' ');
  return `${(space > max * 0.6 ? cut.slice(0, space) : cut).trimEnd()}…`;
}

const MONTH_DAY_YEAR: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric', year: 'numeric' };

/** "Mar 4, 2025, 9:15 AM" for exact times (local), "Mar 4, 2025" for date-only values. */
export function formatPosted(postedAt: string | null | undefined, exact: boolean | undefined): string {
  if (!postedAt) return '';
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(postedAt);
  if (dateOnly) {
    // Build a local date so the day doesn't shift with the time zone.
    const d = new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]));
    return d.toLocaleDateString('en-US', MONTH_DAY_YEAR);
  }
  const t = Date.parse(postedAt);
  if (Number.isNaN(t)) return '';
  const d = new Date(t);
  return exact
    ? d.toLocaleString('en-US', { ...MONTH_DAY_YEAR, hour: 'numeric', minute: '2-digit' })
    : d.toLocaleDateString('en-US', MONTH_DAY_YEAR);
}

export function byline(
  c: Pick<Card, 'posted_at' | 'posted_exact' | 'channel' | 'collaborators'>,
): { posted: string; by: string } {
  // "Owner", "Owner with A", "Owner with A and B", "Owner with A, B and C".
  const names = (c.collaborators ?? []).map((x) => x.name);
  const guests = names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0];
  const by = c.channel ? (guests ? `${c.channel} with ${guests}` : c.channel) : '';
  return { posted: formatPosted(c.posted_at, c.posted_exact), by };
}

/** 950, 12K, 1.3M. */
export function compactNumber(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '';
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumSignificantDigits: 2 }).format(n);
}

const ACTION_LABELS: Record<string, string> = {
  keep: 'Kept',
  prioritize: 'Kept, analyze first',
  archive: 'Archived',
  flip: 'Flipped the card',
  open: 'Opened on YouTube',
  info: 'Viewed info',
};

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action;
}

/** "20261030" -> "Oct 30, 2026" (YouTube's playlist "last updated"). */
export function formatYmd(ymd: string | null | undefined): string {
  if (!ymd || !/^\d{8}$/.test(ymd)) return '';
  return formatPosted(`${ymd.slice(0, 4)}-${ymd.slice(4, 6)}-${ymd.slice(6)}`, false);
}

/** Thumbnail badge: the first place it was saved, "+N" for more. */
export function savedBadge(c: Pick<Card, 'saved_in_labels' | 'sources'>): string {
  const labels = c.saved_in_labels ?? [];
  if (!labels.length) return primarySourceBadge(c.sources);
  return labels.length > 1 ? `${labels[0]} +${labels.length - 1}` : labels[0];
}

/** "Saved Oct 30, 2026 to Biz ideas", or '' when YouTube doesn't tell us (Watch Later). */
export function savedLine(c: Pick<Card, 'saved_at' | 'saved_where'>): string {
  if (!c.saved_at) return '';
  const when = formatPosted(c.saved_at, false);
  if (!when) return '';
  return c.saved_where ? `Saved ${when} to ${c.saved_where}` : `Saved ${when}`;
}

/** "Signal 4/5" pill text, with a tilde when it's only a guess from the title. */
export function signalLabel(c: Pick<Card, 'signal' | 'signal_source'>): string {
  if (!c.signal) return '';
  return c.signal_source === 'analysis' ? `Signal ${c.signal}/5` : `Signal ~${c.signal}/5`;
}
