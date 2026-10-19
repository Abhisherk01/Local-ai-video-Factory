import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type {
  AdaptersInfo,
  AdapterProbe,
  Episode,
  JobStats,
  JobsStatsInfo,
  PipelineJob,
} from "../api/types";
import StatusChip from "../components/StatusChip";
import type { StatusChipProps } from "../components/StatusChip";
import { btnGhost, btnPrimary, card, inputCls } from "../components/ui";

const POLL_MS = 2500;

function statusTone(status: string): StatusChipProps["tone"] {
  switch (status) {
    case "succeeded":
    case "scripted":
    case "published":
      return "ok";
    case "running":
    case "failed":
      return status === "running" ? "warn" : "error";
    case "draft":
    case "queued":
    case "cancelled":
    default:
      return "info";
  }
}

function jobTone(status: string): StatusChipProps["tone"] {
  switch (status) {
    case "succeeded":
      return "ok";
    case "running":
      return "warn";
    case "failed":
      return "error";
    default:
      return "info"; // queued / cancelled
  }
}

function AdapterChip({ probe }: { probe: AdapterProbe }) {
  const short = probe.available ? probe.name : `${probe.name} off`;
  return (
    <span
      title={probe.detail}
      className="inline-flex items-center"
    >
      <StatusChip tone={probe.available ? "ok" : "info"} label={short} />
    </span>
  );
}

function StatBox({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="rounded-md border border-line-subtle bg-base px-3 py-2">
      <div className={`font-mono text-page-title ${tone}`}>{value}</div>
      <div className="text-caption text-ink-mute">{label}</div>
    </div>
  );
}

interface PipelineProps {
  version: string;
}

/**
 * Pipeline screen (Phase 3): episodes + durable job queue visibility.
 * Every generation path is honest: chips show which adapters are
 * installed, and results carry their method label (local_ollama,
 * fallback_template, fallback_tone, local_piper).
 */
export default function Pipeline({ version }: PipelineProps) {
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [jobs, setJobs] = useState<PipelineJob[]>([]);
  const [stats, setStats] = useState<JobStats | null>(null);
  const [workerRunning, setWorkerRunning] = useState<boolean | null>(null);
  const [adapters, setAdapters] = useState<AdaptersInfo | null>(null);
  const [title, setTitle] = useState("");
  const [topic, setTopic] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const aliveRef = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const [ep, js, ad] = await Promise.all([
        api.episodes(),
        api.jobs(),
        api.adapters(),
      ]);
      if (!aliveRef.current) return;
      setEpisodes(ep.episodes);
      setJobs(js.jobs);
      setAdapters(ad);
      setWorkerRunning(ad.worker.running);
      const statsBody: JobsStatsInfo = await api.jobStats();
      if (aliveRef.current) setStats(statsBody.stats);
      setError(null);
    } catch (err) {
      if (aliveRef.current) {
        setError(err instanceof ApiError ? err.message : String(err));
      }
    }
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    void refresh();
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => {
      aliveRef.current = false;
      clearInterval(timer);
    };
  }, [refresh]);

  async function createEpisode() {
    if (!title.trim() || !topic.trim() || busy) return;
    setBusy(true);
    try {
      await api.createEpisode(title.trim(), topic.trim());
      setTitle("");
      setTopic("");
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function scriptEpisode(ep: Episode, mode: "auto" | "template") {
    setBusy(true);
    try {
      await api.requestScript(ep.id, { mode });
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function removeEpisode(ep: Episode) {
    setBusy(true);
    try {
      await api.deleteEpisode(ep.id);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function cancelJob(job: PipelineJob) {
    setBusy(true);
    try {
      await api.cancelJob(job.id);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const jobById = new Map(jobs.map((j) => [j.id, j]));

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col px-6 py-8">
      <section className={card}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-display text-ink">Pipeline</h1>
            <p className="mt-1 text-body2 text-ink-dim">
              Episodes and the durable job queue (backend v{version}). Jobs
              survive restarts; crashed work is reclaimed on boot.
            </p>
          </div>
          {workerRunning !== null && (
            <StatusChip
              tone={workerRunning ? "ok" : "warn"}
              label={workerRunning ? "worker running" : "worker stopped"}
            />
          )}
        </div>
        {adapters && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {Object.values(adapters.adapters).map((probe) => (
              <AdapterChip key={probe.name} probe={probe} />
            ))}
            <span className="text-caption text-ink-mute">
              generation backends detected on this machine
            </span>
          </div>
        )}
      </section>

      {error && (
        <div className="mt-4 rounded-lg border border-danger/30 bg-danger-subtle px-4 py-2 text-body2 text-danger">
          {error}
        </div>
      )}

      <section className={`${card} mt-4`}>
        <h2 className="text-section text-ink">New episode</h2>
        <div className="mt-3 flex flex-col gap-2">
          <input
            className={inputCls}
            placeholder="Title (e.g. Why sourdough fails)"
            value={title}
            maxLength={200}
            onChange={(e) => setTitle(e.target.value)}
          />
          <textarea
            className={`${inputCls} h-16 py-2`}
            placeholder="Topic the script should cover"
            value={topic}
            maxLength={2000}
            onChange={(e) => setTopic(e.target.value)}
          />
          <div>
            <button
              className={btnPrimary}
              disabled={busy || !title.trim() || !topic.trim()}
              onClick={() => void createEpisode()}
            >
              Create episode
            </button>
          </div>
        </div>
      </section>

      <section className={`${card} mt-4`}>
        <div className="flex items-center justify-between">
          <h2 className="text-section text-ink">Episodes</h2>
          <span className="font-mono text-caption text-ink-mute">
            {episodes.length}
          </span>
        </div>
        {episodes.length === 0 ? (
          <p className="mt-3 text-body2 text-ink-dim">
            No episodes yet. Create one above - the script step works with
            the template fallback even before any model is installed.
          </p>
        ) : (
          <ul className="mt-3 divide-y divide-line-subtle">
            {episodes.map((ep) => {
              const scriptJob = jobs.find(
                (j) => j.episode_id === ep.id && j.type.startsWith("script"),
              );
              return (
                <li key={ep.id} className="flex flex-col gap-1 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-body2 text-ink">
                          {ep.title}
                        </span>
                        <StatusChip
                          tone={statusTone(ep.status)}
                          label={ep.status}
                        />
                        {ep.script_method && (
                          <span className="font-mono text-caption text-ink-mute">
                            {ep.script_method}
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 truncate text-caption text-ink-mute">
                        {ep.topic}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <button
                        className={btnGhost}
                        disabled={busy || ep.status === "scripted"}
                        onClick={() => void scriptEpisode(ep, "auto")}
                        title="Queue a script job (Ollama when installed, template fallback otherwise)"
                      >
                        Script
                      </button>
                      <button
                        className={btnGhost}
                        disabled={busy}
                        onClick={() => void removeEpisode(ep)}
                        title="Delete episode (job history is kept)"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                  {scriptJob && scriptJob.status !== "succeeded" && (
                    <p className="font-mono text-caption text-ink-mute">
                      job #{scriptJob.id} {scriptJob.status}
                      {scriptJob.error ? ` - ${scriptJob.error}` : ""}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className={`${card} mt-4`}>
        <div className="flex items-center justify-between">
          <h2 className="text-section text-ink">Job queue</h2>
          <span className="font-mono text-caption text-ink-mute">
            recent {jobs.length}
          </span>
        </div>
        {stats && (
          <div className="mt-3 grid grid-cols-5 gap-2">
            <StatBox label="queued" value={stats.queued} tone="text-info" />
            <StatBox label="running" value={stats.running} tone="text-warning" />
            <StatBox label="done" value={stats.succeeded} tone="text-success" />
            <StatBox label="failed" value={stats.failed} tone="text-danger" />
            <StatBox label="cancelled" value={stats.cancelled} tone="text-ink-dim" />
          </div>
        )}
        {jobs.length === 0 ? (
          <p className="mt-3 text-body2 text-ink-dim">No jobs yet.</p>
        ) : (
          <ul className="mt-3 divide-y divide-line-subtle">
            {jobs.map((job) => (
              <li key={job.id} className="flex items-center justify-between gap-3 py-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-caption text-ink-mute">
                      #{job.id}
                    </span>
                    <span className="font-mono text-caption text-ink">
                      {job.type}
                    </span>
                    <StatusChip tone={jobTone(job.status)} label={job.status} />
                    {job.attempts > 1 && (
                      <span className="font-mono text-caption text-warning">
                        attempt {job.attempts}/{job.max_attempts}
                      </span>
                    )}
                    {job.episode_id !== null && jobById.has(job.id) === false && (
                      <span className="font-mono text-caption text-ink-mute">
                        ep {job.episode_id}
                      </span>
                    )}
                  </div>
                  {(job.error != null || job.result?.method != null) && (
                    <p className="mt-0.5 truncate font-mono text-caption text-ink-mute">
                      {job.error
                        ? job.error
                        : `method: ${String(job.result?.method)}`}
                    </p>
                  )}
                </div>
                {job.status === "queued" && (
                  <button
                    className={btnGhost}
                    disabled={busy}
                    onClick={() => void cancelJob(job)}
                  >
                    Cancel
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
