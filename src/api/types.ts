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
