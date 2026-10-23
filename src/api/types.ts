/**
 * Shared API types mirroring backend/laf/api route payloads.
 * Keep in sync with the backend schemas.
 */

export interface HealthInfo {
  status: "ok";
  version: string;
  db: { ok: boolean; journal_mode: string };
  uptime_s: number;
}

export interface PrereqCheck {
  name: string;
  ok: boolean;
  required: boolean;
  detail: string;
}

export interface SystemPaths {
  data_dir: string;
  models_dir: string;
  db_path: string;
}

export interface PathValidation {
  path: string;
  exists: boolean;
  writable: boolean;
  free_gb: number | null;
}

export type BackendStatus =
  | { state: "starting" }
  | { state: "ready"; version: string }
  | { state: "error"; message: string };

// ---------------------------------------------------------------------------
// Phase 3: pipeline types (episodes, jobs, adapters)
// ---------------------------------------------------------------------------

export type EpisodeStatus =
  | "draft"
  | "scripted"
  | "storyboarded"
  | "rendered"
  | "published"
  | "failed"
  | "cancelled";

export interface Episode {
  id: number;
  title: string;
  topic: string;
  channel: string;
  status: EpisodeStatus;
  script_text: string | null;
  script_method: string | null;
  series_id: number | null;
  created_at: string;
  updated_at: string;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface PipelineJob {
  id: number;
  type: string;
  status: JobStatus;
  priority: number;
  gpu: boolean;
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  attempts: number;
  max_attempts: number;
  run_after: string | null;
  idempotency_key: string | null;
  episode_id: number | null;
  worker_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface JobStats {
  queued: number;
  running: number;
  succeeded: number;
  failed: number;
  cancelled: number;
}

export interface JobsStatsInfo {
  stats: JobStats;
  known_types: string[];
  worker: { running: boolean; worker_id: string | null };
}

export interface AdapterProbe {
  name: string;
  available: boolean;
  detail: string;
  extra?: Record<string, unknown>;
}

export interface AdaptersInfo {
  adapters: Record<string, AdapterProbe>;
  worker: { running: boolean; worker_id: string | null };
}

// ---------------------------------------------------------------------------
// 0.4.5: voices
// ---------------------------------------------------------------------------

export interface VoiceInfo {
  slug: string;
  name: string;
  gender: string;
  quality: string;
  description: string;
  length_scale?: number | null;
  custom?: boolean;
  installed?: boolean;
}

export interface VoicesInfo {
  voices: VoiceInfo[];
  catalog: VoiceInfo[];
  voices_dir: string;
}

// ---------------------------------------------------------------------------
// Phase 4: styles, storyboards, series
// ---------------------------------------------------------------------------

export interface StyleInfo {
  id: number;
  slug: string;
  name: string;
  prompt_prefix: string;
  prompt_suffix: string;
  is_builtin: boolean;
}

export interface StoryboardScene {
  idx: number;
  narration: string;
  visual_prompt: string;
  duration_s: number;
}

export interface Storyboard {
  id: number;
  episode_id: number;
  style_slug: string;
  method: string | null;
  scene_count: number;
  total_duration_s: number;
  created_at: string;
  updated_at: string;
  scenes: StoryboardScene[];
}

export interface SeriesInfo {
  id: number;
  name: string;
  premise: string;
  requested_count: number;
  method: string | null;
  episode_count?: number;
  created_at: string;
  updated_at: string;
}
