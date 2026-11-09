// Thin client for the VideoMentor API. Auth is the httpOnly session cookie set
// by GET /pair?code=..., so every request goes same-origin with credentials.
import type {
  AiCheck,
  AiChoice,
  AiStatus,
  Card,
  NotForLearning,
  ChannelSummary,
  DecisionPayload,
  DeckOrder,
  GroupAction,
  Playlist,
  ChannelPullResult,
  PulledChannel,
  Progress,
  ActionItem,
  ActionCounts,
  ActionStatus,
  TrainingModule,
  PairedDevice,
  RenderStatus,
  SignalSettings,
  TagMerge,
  YouTubeApiState,
  GroupResponse,
  ItemDetail,
  StatusResponse,
  TagHistory,
  TagRow,
  TagItemStatus,
  TagItemsResponse,
  Insights,
  NextUpMode,
  NextUpResponse,
} from './types';
import type { TouchEvent } from './events';
import { isCacheable, offlineStore, withTimeout } from './offlineStore';
import type { OfflinePack } from './offlinePack';
import type { BatchResult, QueueTransport } from './queue';

export class ApiError extends Error {
  readonly permanent: boolean;
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
    // 4xx means "this request will never succeed"; 401/408/429 are retryable.
    this.permanent = status >= 400 && status < 500 && ![401, 408, 429].includes(status);
  }
}

export class AuthError extends ApiError {
  constructor() {
    super(401, 'This device is not paired');
    this.name = 'AuthError';
  }
}

export class NetworkError extends Error {
  readonly permanent = false;
  constructor(message = 'No connection') {
    super(message);
    this.name = 'NetworkError';
  }
}

export function isNetworkError(err: unknown): boolean {
  return err instanceof NetworkError;
}

type Listener = () => void;
const unauthorizedListeners = new Set<Listener>();
const authorizedListeners = new Set<Listener>();

/** Called whenever any /api request returns 401. */
export function onUnauthorized(fn: Listener): () => void {
  unauthorizedListeners.add(fn);
  return () => unauthorizedListeners.delete(fn);
}

/** Called whenever an /api request succeeds (so the pair screen can close itself). */
export function onAuthorized(fn: Listener): () => void {
  authorizedListeners.add(fn);
  return () => authorizedListeners.delete(fn);
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;
let fetchImpl: FetchLike = (input, init) => fetch(input, init);

/** For tests. */
export function setFetch(fn: FetchLike): void {
  fetchImpl = fn;
}

// A gateway error means Tailscale (or a proxy) answered but the app behind it is down.
const GATEWAY = new Set([502, 503, 504]);
let offlineTimeoutMs = 5000;

/** How long a screen waits for the Mac before showing its saved copy (tests shorten it). */
export function setOfflineTimeout(ms: number): void {
  offlineTimeoutMs = ms;
}

const TIMED_OUT = Symbol('timed out');
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function request<T>(path: string, init: { method?: string; body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  let body: string | undefined;
  if (init.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(init.body);
  }
  const method = init.method ?? (body ? 'POST' : 'GET');
  const saveable = method === 'GET' && isCacheable(path);
  // With a saved copy on hand, don't make the screen wait out a long network timeout.
  const saved = saveable ? await withTimeout(offlineStore().get(path), 1000, undefined) : undefined;
  let res: Response;
  try {
    const fetching = fetchImpl(path, {
      method,
      headers,
      body,
      credentials: 'same-origin',
      cache: 'no-store',
      signal: init.signal,
    });
    res =
      saved === undefined
        ? await fetching
        : ((await Promise.race([fetching, delay(offlineTimeoutMs).then(() => TIMED_OUT)])) as Response);
    if ((res as unknown) === TIMED_OUT) return saved as T;
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    // The Mac can't be reached: use the copy saved the last time this screen loaded.
    if (saved !== undefined) return saved as T;
    throw new NetworkError();
  }
  if (GATEWAY.has(res.status)) {
    if (saved !== undefined) return saved as T;
    throw new NetworkError();
  }
  if (res.status === 401) {
    await offlineStore().clear(); // signed out: nobody else on this device reads the library
    unauthorizedListeners.forEach((fn) => fn());
    throw new AuthError();
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      if (data && typeof data.detail === 'string') detail = data.detail;
    } catch {
      // not JSON
    }
    throw new ApiError(res.status, detail || `HTTP ${res.status}`);
  }
  authorizedListeners.forEach((fn) => fn());
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = (text ? JSON.parse(text) : undefined) as T;
  if (saveable && data !== undefined) void offlineStore().set(path, data);
  return data;
}

// ---- URL builders (pure, tested) -----------------------------------------

export function deckUrl(n: number, exclude: string[], source = 'all', order?: DeckOrder): string {
  const params = new URLSearchParams({ deck: 'main', n: String(n) });
  if (source && source !== 'all') params.set('source', source);
  if (order && order.sort !== 'default') {
    params.set('sort', order.sort);
    params.set('dir', order.dir);
    if (order.start) params.set('start', order.start);
  }
  const ids = [...new Set(exclude)].filter(Boolean);
  if (ids.length) params.set('exclude', ids.join(','));
  return `/api/deck?${params.toString()}`;
}

export function libraryUrl(q: string, status = 'kept'): string {
  const params = new URLSearchParams({ status });
  if (q.trim()) params.set('q', q.trim());
  return `/api/library?${params.toString()}`;
}

export function tagItemsUrl(tag: string, status: TagItemStatus = 'kept'): string {
  return `/api/tags/${encodeURIComponent(tag)}/items?status=${status}`;
}

export function nextUpUrl(mode: NextUpMode, skill?: string): string {
  const params = new URLSearchParams({ mode });
  if (skill) params.set('skill', skill);
  return `/api/next-up?${params.toString()}`;
}

export function itemUrl(id: string): string {
  return `/api/items/${encodeURIComponent(id)}`;
}

// ---- endpoints -------------------------------------------------------------

export const api = {
  status: () => request<StatusResponse>('/api/status'),

  deck: (n: number, exclude: string[], source = 'all', order?: DeckOrder) =>
    request<{ cards: Card[] }>(deckUrl(n, exclude, source, order)).then((r) => r?.cards ?? []),

  playlists: (signal?: AbortSignal) =>
    request<{ playlists: Playlist[]; youtube_api: YouTubeApiState }>('/api/playlists', { signal }),

  playlist: (id: string, signal?: AbortSignal) =>
    request<Playlist>(`/api/playlists/${encodeURIComponent(id)}`, { signal }),

  progress: (signal?: AbortSignal) => request<Progress>('/api/progress', { signal }),

  milestonesSeen: (ids: string[]) => request<{ ok: boolean }>('/api/milestones/seen', { body: { ids } }),
  actions: (status: ActionStatus | 'all', signal?: AbortSignal) =>
    request<{ actions: ActionItem[]; counts: ActionCounts }>(`/api/actions?status=${status}`, { signal }),

  updateAction: (id: number, patch: { status?: ActionStatus; note?: string }) =>
    request<ActionItem>(`/api/actions/${id}`, { body: patch }),
  trainingList: (signal?: AbortSignal) => request<{ modules: TrainingModule[] }>('/api/training', { signal }),

  training: (id: number, signal?: AbortSignal) => request<TrainingModule>(`/api/training/${id}`, { signal }),

  renderTraining: (id: number) => request<RenderStatus>(`/api/training/${id}/render`, { method: 'POST' }),

  renderStatus: (id: number, signal?: AbortSignal) => request<RenderStatus>(`/api/training/${id}/render`, { signal }),

  buildTraining: (tag: string, goal?: string) =>
    request<{ id: number; status: string }>('/api/training', { body: { tag, goal: goal || null } }),

  pullChannel: (body: {
    channel_id: string;
    mode: 'newest' | 'oldest' | 'range';
    count?: number;
    start?: string;
    end?: string;
    include_shorts?: boolean;
    include_lives?: boolean;
  }) =>
    request<ChannelPullResult>('/api/channel/pull', { body }),

  pulledChannels: (signal?: AbortSignal) => request<{ channels: PulledChannel[] }>('/api/channel-pulls', { signal }),

  devices: (signal?: AbortSignal) => request<{ devices: PairedDevice[]; expire_days: number }>('/api/devices', { signal }),

  signOutDevice: (id: string) => request<{ ok: boolean }>(`/api/devices/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  deviceHint: (hint: 'iPad') => request<{ ok: boolean }>('/api/devices/me', { body: { hint } }),

  signOutOthers: () => request<{ signed_out: number }>('/api/devices/sign-out-others', { method: 'POST' }),

  settings: (signal?: AbortSignal) => request<SignalSettings>('/api/settings', { signal }),

  saveSettings: (s: SignalSettings) => request<SignalSettings>('/api/settings', { method: 'PUT', body: s }),

  ai: (signal?: AbortSignal) => request<AiStatus>('/api/ai', { signal }),

  saveAi: (change: { backend?: AiChoice; cap_usd?: number }) =>
    request<AiStatus>('/api/ai', { method: 'PUT', body: change }),

  checkAi: () => request<AiCheck>('/api/ai/check', { method: 'POST', body: {} }),

  rescore: () => request<{ queued: number }>('/api/signal/rescore', { method: 'POST', body: {} }),

  tagMerges: (signal?: AbortSignal) =>
    request<{ merges: TagMerge[]; counts: { proposed: number; applied: number } }>('/api/tag-merges', { signal }),

  applyTagMerges: (approve: number[], reject: number[]) =>
    request<{ applied: number; rejected: number; videos: number }>('/api/tag-merges/apply', { body: { approve, reject } }),

  undoTagMerge: (id: number) => request<TagMerge>(`/api/tag-merges/${id}/undo`, { method: 'POST', body: {} }),

  setPlaylist: (id: string, enabled: boolean) =>
    request<Playlist>(`/api/playlists/${encodeURIComponent(id)}`, { body: { enabled } }),

  item: (id: string, signal?: AbortSignal) => request<ItemDetail>(itemUrl(id), { signal }),

  decide: (d: DecisionPayload) => request<{ decision_id: string | number; item: Card }>('/api/decisions', { body: d }),

  decideBatch: (decisions: DecisionPayload[]) =>
    request<{ results: unknown[] }>('/api/decisions/batch', { body: { decisions } }).then((r) => r?.results ?? []),

  undoBatch: (batch: string) => request<{ undone: number; skipped: number }>('/api/undo-batch', { body: { batch } }),

  notForLearning: (signal?: AbortSignal) => request<NotForLearning>('/api/not-for-learning', { signal }),

  archiveNotForLearning: (olderThanDays: number) =>
    request<{ archived: number; batch: string }>('/api/not-for-learning/archive', { body: { older_than_days: olderThanDays } }),

  undo: (decisionId?: string | number) =>
    request<{ undone: (string | number)[]; items: Card[] }>('/api/undo', {
      body: decisionId === undefined ? {} : { decision_id: decisionId },
    }),

  createGroup: (anchorItemId: string) => request<GroupResponse>('/api/groups', { body: { anchor_item_id: anchorItemId } }),

  decideGroup: (groupId: string | number, clientId: string, action: GroupAction) =>
    request<Record<string, unknown>>(`/api/groups/${encodeURIComponent(String(groupId))}/decide`, {
      body: { client_id: clientId, action },
    }),

  offlinePack: (cards: number, exclude: string[], source: string) => {
    const params = new URLSearchParams({ cards: String(cards), source });
    const ids = [...new Set(exclude)].filter(Boolean);
    if (ids.length) params.set('exclude', ids.join(','));
    return request<OfflinePack>(`/api/offline-pack?${params.toString()}`);
  },

  ready: () => request<{ items: Card[] }>('/api/ready').then((r) => r?.items ?? []),

  seen: (id: string) => request<unknown>(`${itemUrl(id)}/seen`, { method: 'POST', body: {} }),

  library: (q: string, signal?: AbortSignal, status = 'kept') =>
    request<{ items: Card[] }>(libraryUrl(q, status), { signal }).then((r) => r?.items ?? []),

  sync: () => request<{ started: boolean }>('/api/sync', { method: 'POST', body: {} }),

  events: (events: TouchEvent[]) => request<{ stored: number }>('/api/events', { body: { events } }),

  tagHistory: (tag: string, signal?: AbortSignal) =>
    request<TagHistory>(`/api/tags/${encodeURIComponent(tag)}/history`, { signal }),

  tags: (signal?: AbortSignal) => request<{ tags: TagRow[] }>('/api/tags', { signal }).then((r) => r?.tags ?? []),

  tagItems: (tag: string, status: TagItemStatus = 'kept', signal?: AbortSignal) =>
    request<TagItemsResponse>(tagItemsUrl(tag, status), { signal }),

  insights: (signal?: AbortSignal) => request<Insights>('/api/insights', { signal }),

  nextUp: (mode: NextUpMode, skill?: string, signal?: AbortSignal) => request<NextUpResponse>(nextUpUrl(mode, skill), { signal }),

  channel: (who: { channel_id?: string | null; name?: string | null }, signal?: AbortSignal) =>
    request<ChannelSummary>(channelUrl(who), { signal }),
};

export function channelUrl(who: { channel_id?: string | null; name?: string | null }): string {
  const params = new URLSearchParams();
  if (who.channel_id) params.set('channel_id', who.channel_id);
  else if (who.name) params.set('name', who.name);
  return `/api/channel?${params.toString()}`;
}

/** Normalize one entry of the batch response into what the queue needs. */
export function toBatchResult(raw: unknown): BatchResult {
  if (!raw || typeof raw !== 'object') return {};
  const r = raw as Record<string, unknown>;
  const id = r.decision_id ?? r.id ?? (r.decision as Record<string, unknown> | undefined)?.id;
  const error = typeof r.error === 'string' ? r.error : r.ok === false ? 'rejected' : null;
  return {
    client_id: typeof r.client_id === 'string' ? r.client_id : undefined,
    decision_id: typeof id === 'string' || typeof id === 'number' ? id : null,
    error,
  };
}

export const queueTransport: QueueTransport = {
  async sendBatch(decisions) {
    const results = await api.decideBatch(decisions);
    return results.map(toBatchResult);
  },
  async undo(decisionId) {
    await api.undo(decisionId);
  },
};

/** Pull a decision id out of the group decide response, whatever it's called. */
export function groupDecisionId(res: Record<string, unknown> | undefined): string | number | undefined {
  if (!res) return undefined;
  const direct = res.decision_id;
  if (typeof direct === 'string' || typeof direct === 'number') return direct;
  const many = res.decision_ids;
  if (Array.isArray(many) && (typeof many[0] === 'string' || typeof many[0] === 'number')) return many[0];
  return undefined;
}
