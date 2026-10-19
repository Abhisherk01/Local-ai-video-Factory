/**
 * Backend API client.
 *
 * Base resolution (ADR-008):
 * 1. Inside the Tauri shell: ask Rust for the backend port + session
 *    token via the `get_backend_info` command.
 * 2. In plain browser dev mode (`npm run dev`): talk through the Vite
 *    proxy at /laf-api, which injects the dev token header itself.
 *
 * All traffic stays on 127.0.0.1.
 */

import type {
  AdaptersInfo,
  Episode,
  HealthInfo,
  JobsStatsInfo,
  PathValidation,
  PipelineJob,
  PrereqCheck,
  SeriesInfo,
  Storyboard,
  StyleInfo,
  SystemPaths,
} from "./types";

interface ResolvedBackend {
  base: string;
  token: string;
  proxied: boolean;
}

let cached: ResolvedBackend | null = null;

type TauriBackendInfo =
  | { state: "starting" }
  | { state: "ready"; port: number; token: string; pid: number | null }
  | { state: "error"; message: string };

async function tryTauriInvoke(): Promise<TauriBackendInfo | null> {
  try {
    const core = await import("@tauri-apps/api/core");
    return await core.invoke<TauriBackendInfo>("get_backend_info");
  } catch {
    return null; // not running inside Tauri
  }
}

export async function resolveBackend(): Promise<ResolvedBackend> {
  if (cached) return cached;

  const info = await tryTauriInvoke();
  if (info?.state === "ready") {
    cached = {
      base: `http://127.0.0.1:${info.port}`,
      token: info.token,
      proxied: false,
    };
    return cached;
  }
  if (info?.state === "error") {
    throw new Error(info.message);
  }

  // Browser dev fallback (Vite proxy adds the token header).
  cached = { base: "/laf-api", token: "", proxied: true };
  return cached;
}

export function isBackendStartingError(error: unknown): boolean {
  return (
    error instanceof Error &&
    (error.message === "backend starting" || error.message.includes("Failed to fetch"))
  );
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(
  path: string,
  init: RequestInit & { json?: unknown } = {},
): Promise<T> {
  const backend = await resolveBackend();
  const headers = new Headers(init.headers);
  if (!backend.proxied && backend.token) {
    headers.set("X-LAF-Token", backend.token);
  }
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }

  let response: Response;
  try {
    response = await fetch(`${backend.base}${path}`, { ...init, headers, body });
  } catch {
    throw new ApiError(0, "backend unreachable (is it still starting?)");
  }
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, `${response.status}: ${text}`);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<HealthInfo>("/health"),

  prereq: () => request<PrereqCheck[]>("/api/v1/system/prereq"),

  paths: () => request<SystemPaths>("/api/v1/system/paths"),

  validatePath: (path: string) =>
    request<PathValidation>("/api/v1/system/paths/validate", {
      method: "POST",
      json: { path },
    }),

  getSettings: () =>
    request<{ values: Record<string, string> }>("/api/v1/settings"),

  putSettings: (values: Record<string, string>) =>
    request<{ values: Record<string, string> }>("/api/v1/settings", {
      method: "PUT",
      json: { values },
    }),

  // -- Phase 3: pipeline ---------------------------------------------------

  episodes: (status?: string) =>
    request<{ episodes: Episode[] }>(
      `/api/v1/episodes${status ? `?status=${status}` : ""}`,
    ),

  createEpisode: (title: string, topic: string) =>
    request<{ episode: Episode }>("/api/v1/episodes", {
      method: "POST",
      json: { title, topic },
    }),

  deleteEpisode: (id: number) =>
    request<{ deleted: boolean }>(`/api/v1/episodes/${id}`, {
      method: "DELETE",
    }),

  requestScript: (id: number, body: { mode: string; allow_fallback?: boolean }) =>
    request<{ job: PipelineJob; created: boolean }>(
      `/api/v1/episodes/${id}/script`,
      { method: "POST", json: body },
    ),

  jobs: (limit = 50) =>
    request<{ jobs: PipelineJob[] }>(`/api/v1/jobs?limit=${limit}`),

  cancelJob: (id: number) =>
    request<{ job: PipelineJob }>(`/api/v1/jobs/${id}/cancel`, {
      method: "POST",
    }),

  jobStats: () => request<JobsStatsInfo>("/api/v1/jobs/stats"),

  adapters: () => request<AdaptersInfo>("/api/v1/adapters"),

  // -- Phase 4: styles, storyboards, series --------------------------------

  styles: () => request<{ styles: StyleInfo[] }>("/api/v1/styles"),

  requestStoryboard: (
    id: number,
    body: { style_slug?: string; mode: string; allow_fallback?: boolean },
  ) =>
    request<{ job: PipelineJob; created: boolean }>(
      `/api/v1/episodes/${id}/storyboard`,
      { method: "POST", json: body },
    ),

  storyboard: (id: number) =>
    request<{ storyboard: Storyboard | null }>(
      `/api/v1/episodes/${id}/storyboard`,
    ),

  series: () => request<{ series: SeriesInfo[] }>("/api/v1/series"),

  createSeries: (body: {
    name: string;
    premise: string;
    count: number;
    mode: string;
  }) =>
    request<{ series: SeriesInfo; job: PipelineJob; created: boolean }>(
      "/api/v1/series",
      { method: "POST", json: body },
    ),
};
