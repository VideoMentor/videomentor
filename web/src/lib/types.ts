// Shapes from the API contract in docs/superpowers/specs/2026-10-25-youtube-swipe-design.md.

export type DeckKey = 'main' | 'music';
export type ItemStatus = 'inbox' | 'kept' | 'archived';
export type AnalysisStatus = 'none' | 'queued' | 'running' | 'done' | 'failed';
export type DecisionAction = 'keep' | 'archive' | 'prioritize';
export type GroupAction = 'keep' | 'archive';

export interface Collaborator {
  name: string;
  channel_id: string | null;
}

export interface Card {
  id: string;
  video_id: string;
  url: string;
  title: string;
  channel: string | null;
  channel_id?: string | null;
  /** Channels credited besides the owner on a collaboration. */
  collaborators?: Collaborator[];
  /** ISO time when exact, else YYYY-MM-DD. */
  posted_at: string | null;
  posted_exact: boolean;
  duration_s: number | null;
  thumbnail: string | null;
  added_at: string | null;
  /** Best known save time (playlist save date or bookmark date) and where. */
  saved_at?: string | null;
  saved_where?: string | null;
  why: string | null;
  topics: string[];
  tags: string[];
  category: string | null;
  status: ItemStatus;
  priority: number;
  analysis_status: AnalysisStatus;
  sources: string[];
  /** Where it was saved, in words: "Watch Later", playlist names, bookmarks. */
  saved_in_labels?: string[];
  summary_short: string | null;
  /** 1 to 5 business-learning value; 'prep' = guess from metadata, 'analysis' = from the video. */
  signal?: number | null;
  signal_reason?: string | null;
  signal_source?: 'prep' | 'analysis' | null;
  key_moment?: { t: number; label: string } | null;
  core_idea?: string | null;
  skills?: string[];
}

export interface Moment {
  t: number | string;
  label: string;
}

export interface Analysis {
  core_idea?: string;
  frameworks?: { name: string; how: string }[];
  takeaways?: string[];
  try_this_week?: string[];
  key_moment?: Moment | null;
  skills?: string[];
  useful_for?: string;
  signal?: number;
  signal_reason?: string;
  summary?: string;
  key_points?: string[];
  moments?: Moment[];
  learnings?: string[];
  curriculum_topic?: string;
  transcript_source?: 'captions' | 'none' | string;
}

export interface SavedIn {
  source: string;
  source_ref: string | null;
  first_seen: string;
}

export interface Decision {
  id: number;
  action: string;
  new_status: string | null;
  reason: string | null;
  undone: number;
  at: string;
}

export interface ItemDetail extends Card {
  description?: string | null;
  channel_handle?: string | null;
  channel_followers?: number | null;
  view_count?: number | null;
  yt_tags?: string[];
  yt_categories?: string[];
  saved_in?: SavedIn[];
  chapters?: { t: number; label: string }[];
  // Stored as JSON in SQLite; the server may send it parsed or as a string.
  analysis?: Analysis | string | null;
  decisions?: Decision[];
}

export interface StatusCounts {
  inbox: number;
  kept: number;
  archived: number;
  music_inbox: number;
  unprepped: number;
  pulled_inbox: number;
  queued: number;
  ready: number;
}

export interface YouTubeApiState {
  state: 'not_set_up' | 'signed_out' | 'expired' | 'ok' | string;
  message: string;
  signed_in_at?: string | null;
}

export interface Playlist {
  id: string;
  title: string | null;
  owner: string | null;
  visibility: string | null;
  video_count: number | null;
  /** YYYYMMDD */
  modified_date: string | null;
  created_at: string | null;
  enabled: boolean;
  error: string | null;
  synced: number;
  newest_save: string | null;
  dates_known: boolean;
  inbox: number;
  kept: number;
  archived: number;
  items_synced_at: string | null;
  /** Position in YouTube's own playlist library. */
  feed_order?: number | null;
}

/** How the deck is ordered. start = YYYY-MM-DD: forward (asc) or backward (desc) from that day. */
export interface DeckOrder {
  sort: 'default' | 'posted' | 'saved';
  dir: 'desc' | 'asc';
  start: string | null;
}

/** 'all' | 'wl' | 'playlists' | 'pl:<id>' */
export interface DeckSource {
  key: string;
  label: string;
}

export interface StatusResponse {
  counts: Partial<StatusCounts>;
  youtube_api?: YouTubeApiState;
  playlists_enabled?: number;
  // Shape not pinned down by the contract: ISO string, a sync_runs row, or null.
  last_sync: unknown;
  worker?: Record<string, unknown>;
}

export interface Group {
  id: string | number;
  label: string;
  basis: 'topic' | 'channel' | string;
}

export interface GroupResponse {
  group: Group;
  items: Card[];
}

export interface DecisionPayload {
  client_id: string;
  item_id: string;
  action: DecisionAction;
  at: string;
}

export interface TouchedCard extends Card {
  last_action: string;
  last_at: string;
  touches: number;
}

export interface TagHistory {
  tag: string;
  total: number;
  related: { tag: string; count: number }[];
  items: TouchedCard[];
}

export interface ChannelSummary {
  channel: string | null;
  channel_id: string | null;
  handle: string | null;
  followers: number | null;
  counts: { saved: number; kept: number; archived: number; inbox: number };
  items?: Card[];
}

export interface TagMerge {
  id: number;
  keep: string;
  fold: string[];
  reason: string | null;
  status: 'proposed' | 'applied' | 'rejected' | 'undone';
  videos: number;
  created_at: string;
  applied_at: string | null;
}

export interface SignalSettings {
  signal_areas: string[];
  signal_guidance: string;
  skill_map: string[];
}

export interface Progress {
  decided: number;
  kept: number;
  archived: number;
  hours: number;
  streak_days: number;
  today: number;
  unseen: { id: string; kind: string; value: number; label: string }[];
}

export type ActionStatus = 'open' | 'done' | 'skipped';

export interface ActionItem {
  id: number;
  item_id: string;
  text: string;
  position: number;
  status: ActionStatus;
  note: string | null;
  created_at: string;
  done_at: string | null;
  item: Card | null;
}

export interface ActionCounts {
  open: number;
  done: number;
  skipped: number;
  done_this_week: number;
}

/** A paired device (one sign-in). */
export interface PairedDevice {
  id: string;
  created_at: string;
  last_seen: string;
  device: string;
  current: boolean;
}

export interface TrainingClip {
  video: string;
  start: number;
  end: number;
  why: string;
  watch_for: string;
  title: string | null;
  channel: string | null;
  url: string;
  embed: string;
  thumbnail: string;
}

export interface TrainingModuleBody {
  title: string;
  outcome: string;
  minutes: number | null;
  lessons: { title: string; goal: string; clips: TrainingClip[]; exercise: string }[];
  quiz: { question: string; answer: string; video: string; t: number; url: string; title: string | null }[];
  gaps: string[];
  dropped: number;
  tag: string;
  goal: string | null;
}

/** A rendered training video. */
export interface RenderStatus {
  state: 'none' | 'rendering' | 'ready' | 'failed';
  done?: number;
  total?: number;
  seconds?: number;
  error?: string;
  finished_at?: string;
}

export interface TrainingModule {
  id: number;
  tag: string;
  goal: string | null;
  status: 'building' | 'ready' | 'failed';
  title: string | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  lessons?: number;
  clips?: number;
  module?: TrainingModuleBody | null;
  video?: RenderStatus;
}

export interface ChannelPullResult {
  channel: string;
  channel_id: string;
  seen: number;
  added: number;
  via: 'api' | 'yt-dlp';
}

export interface PulledChannel {
  channel_id: string;
  channel: string | null;
  last_pull: string;
  videos: number;
  inbox: number;
  preparing: number;
}

// ---- tags, insights and next up (GET /api/tags, /api/insights, /api/next-up) ----

/** One tag with its counts. `avg_signal` is over all its videos, `minutes` over kept ones. */
export interface TagRow {
  tag: string;
  total: number;
  kept: number;
  inbox: number;
  archived: number;
  analyzed: number;
  avg_signal: number | null;
  minutes: number | null;
}

export type TagItemStatus = 'kept' | 'inbox' | 'archived' | 'all';

/** A video on a tag page. `words` is null without a transcript; `notes` counts key points,
 *  frameworks and takeaways; `duration_s` is null when unknown. */
export interface TagItem {
  id: string;
  title: string;
  channel: string | null;
  status: ItemStatus;
  signal: number | null;
  duration_s: number | null;
  words: number | null;
  notes: number;
  actions_open: number;
  actions_done: number;
  added_at: string | null;
  analyzed_at: string | null;
}

export interface TagItemsResponse {
  tag: string;
  summary: { count: number; minutes: number | null; analyzed: number };
  items: TagItem[];
}

export interface SkillReport {
  skill: string;
  kept: number;
  analyzed: number;
  avg_signal: number | null;
  minutes: number | null;
  actions_open: number;
  actions_done: number;
}

export interface KeepRate {
  signal: number;
  kept: number;
  archived: number;
  rate: number | null;
}

export interface UsageTotals {
  calls?: number;
  failed?: number;
  input_tokens?: number;
  output_tokens?: number;
  cache_read_tokens?: number;
  cache_creation_tokens?: number;
  cost_usd?: number;
}

export interface UsageByStep extends UsageTotals {
  step: string;
}

export interface Insights {
  skills: SkillReport[];
  funnel: {
    inbox: number;
    kept: number;
    archived: number;
    analyzed: number;
    analysis_failed: number;
    decisions_7d: number;
    undo_rate: number | null;
  };
  signal_keep: KeepRate[];
  signal_keep_clean?: KeepRate[];
  sources: { source: string; label?: string | null; kept: number; archived: number; rate: number | null }[];
  latency: { queue_to_notes_h: number | null; save_to_notes_h: number | null };
  usage: { since: string | null; total: UsageTotals; last_7d: UsageTotals; by_step: UsageByStep[] };
  inbox_by_tag: { tag: string; inbox: number; avg_signal: number | null }[];
}

export type NextUpMode = 'watch' | 'apply';

export type NextUpResponse =
  | { mode: 'watch'; item: Card | null }
  | { mode: 'apply'; action: (Omit<ActionItem, 'item'> & { item_title: string; item_id: string; item?: Card | null }) | null };
