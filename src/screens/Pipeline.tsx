import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type {
  AdaptersInfo,
  AdapterProbe,
  Episode,
  JobStats,
  JobsStatsInfo,
  PipelineJob,
  SeriesInfo,
  StyleInfo,
  VoiceInfo,
} from "../api/types";
import StoryboardPanel from "../components/StoryboardPanel";
import StatusChip from "../components/StatusChip";
import type { StatusChipProps } from "../components/StatusChip";
import { btnGhost, btnPrimary, card, inputCls } from "../components/ui";

const POLL_MS = 2500;

function statusTone(status: string): StatusChipProps["tone"] {
  switch (status) {
    case "succeeded":
    case "scripted":
    case "storyboarded":
    case "rendered":
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
  const [styles, setStyles] = useState<StyleInfo[]>([]);
  // Per-episode style choice (bug fix: one shared value made every row's
  // picker change together and sent the last-touched style with whichever
  // episode's Storyboard was clicked). Keyed by episode id; each defaults
  // to dark_cinematic, which the seeded registry always provides.
  const [styleByEp, setStyleByEp] = useState<Record<number, string>>({});
  // 0.4.5: per-episode narration voice. "auto" = the adapter's default
  // piper voice - the pre-0.4.5 behaviour, byte-identical renders.
  const [voices, setVoices] = useState<VoiceInfo[]>([]);
  const [voiceByEp, setVoiceByEp] = useState<Record<number, string>>({});
  const [series, setSeries] = useState<SeriesInfo[]>([]);
  const [seriesName, setSeriesName] = useState("");
  const [seriesPremise, setSeriesPremise] = useState("");
  const [seriesCount, setSeriesCount] = useState(20);
  const [planOpenFor, setPlanOpenFor] = useState<number | null>(null);
  const [planKey, setPlanKey] = useState(0);
  const [title, setTitle] = useState("");
  const [topic, setTopic] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const aliveRef = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const [ep, js, ad, st, se, vo] = await Promise.all([
        api.episodes(),
        api.jobs(),
        api.adapters(),
        api.styles(),
        api.series(),
        api.voices(),
      ]);
      if (!aliveRef.current) return;
      setEpisodes(ep.episodes);
      setJobs(js.jobs);
      setAdapters(ad);
      setWorkerRunning(ad.worker.running);
      setStyles(st.styles);
      setSeries(se.series);
      setVoices(vo.voices);
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

  async function storyboardEpisode(ep: Episode) {
    setBusy(true);
    try {
      await api.requestStoryboard(ep.id, {
        style_slug: styleByEp[ep.id] ?? "dark_cinematic",
        mode: "auto",
      });
      setPlanOpenFor(ep.id);
      setPlanKey((k) => k + 1);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function renderEpisode(ep: Episode) {
    setBusy(true);
    try {
      const vs = voiceByEp[ep.id];
      await api.requestRender(ep.id, {
        allow_fallback: true,
        ...(vs && vs !== "auto" ? { voice_slug: vs } : {}),
      });
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function createSeriesOutline() {
    if (!seriesName.trim() || !seriesPremise.trim() || busy) return;
    setBusy(true);
    try {
      await api.createSeries({
        name: seriesName.trim(),
        premise: seriesPremise.trim(),
        count: seriesCount,
        mode: "auto",
      });
      setSeriesName("");
      setSeriesPremise("");
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
            {episodes.length} - picker v2
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
              const renderJob = jobs.find(
                (j) => j.episode_id === ep.id && j.type.startsWith("video"),
              );
              const mp4 =
                renderJob && renderJob.status === "succeeded"
                  ? renderJob.result
                  : null;
              const mp4Path =
                mp4 && typeof mp4.path === "string" ? mp4.path : null;
              const mp4Dur =
                mp4 && typeof mp4.duration_s === "number" ? mp4.duration_s : null;
              const mp4Voice =
                mp4 && typeof mp4.voice === "string" ? mp4.voice : null;
              const planReady = ep.status === "storyboarded" || ep.status === "rendered";
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
                        {ep.series_id != null && (
                          <span className="font-mono text-caption text-ink-mute">
                            series {ep.series_id}
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 truncate text-caption text-ink-mute">
                        {ep.topic}
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                      <select
                        className="rounded-md border border-line-subtle bg-base px-2 py-1.5 font-mono text-caption text-ink-dim"
                        value={styleByEp[ep.id] ?? "dark_cinematic"}
                        title="Visual style applied to this episode's scene prompts"
                        onChange={(e) =>
                          setStyleByEp((m) => ({
                            ...m,
                            [ep.id]: e.target.value,
                          }))
                        }
                      >
                        {styles.length === 0 && (
                          <option value="dark_cinematic">dark_cinematic</option>
                        )}
                        {styles.map((s) => (
                          <option key={s.slug} value={s.slug}>
                            {s.name}
                          </option>
                        ))}
                      </select>
                      <select
                        className="rounded-md border border-line-subtle bg-base px-2 py-1.5 font-mono text-caption text-ink-dim"
                        value={voiceByEp[ep.id] ?? "auto"}
                        title={
                          voices.length === 0
                            ? "No piper voices installed yet - the render falls back to the default. Add voices with scripts\\add_voice.ps1"
                            : `Narration voice for Render. ${voices.length} installed; add more with scripts\\add_voice.ps1`
                        }
                        onChange={(e) =>
                          setVoiceByEp((m) => ({
                            ...m,
                            [ep.id]: e.target.value,
                          }))
                        }
                      >
                        <option value="auto">Auto voice</option>
                        {voices.map((v) => (
                          <option key={v.slug} value={v.slug}>
                            {v.name} - {v.gender}
                            {v.custom ? " (custom)" : ""}
                          </option>
                        ))}
                      </select>
                      <button
                        className={btnGhost}
                        disabled={busy}
                        onClick={() => void scriptEpisode(ep, "auto")}
                        title="Queue a script job (Ollama when installed, template fallback otherwise). Re-running replaces the stored script."
                      >
                        Script
                      </button>
                      <button
                        className={btnGhost}
                        disabled={busy}
                        onClick={() => void storyboardEpisode(ep)}
                        title="Split the script into scenes with per-scene visual prompts. Re-running replaces the scene plan."
                      >
                        Storyboard
                      </button>
                      {planReady && (
                        <button
                          className={btnGhost}
                          onClick={() =>
                            setPlanOpenFor(planOpenFor === ep.id ? null : ep.id)
                          }
                          title="Show or hide the scene plan"
                        >
                          {planOpenFor === ep.id ? "Hide plan" : "Plan"}
                        </button>
                      )}
                      <button
                        className={btnGhost}
                        disabled={busy}
                        onClick={() => void renderEpisode(ep)}
                        title="Render the finished 9:16 MP4 with the selected voice (piper when installed, tone placeholder otherwise). Re-running overwrites with the new voice."
                      >
                        Render
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
                  {renderJob && renderJob.status !== "succeeded" && (
                    <p className="font-mono text-caption text-ink-mute">
                      render job #{renderJob.id} {renderJob.status}
                      {renderJob.error ? ` - ${renderJob.error}` : ""}
                    </p>
                  )}
                  {mp4Path && (
                    <p className="truncate font-mono text-caption text-success">
                      mp4: {mp4Path}
                      {mp4Dur != null ? ` (${mp4Dur.toFixed(1)}s)` : ""}
                      {mp4Voice ? ` - voice: ${mp4Voice}` : ""}
                    </p>
                  )}
                  {planOpenFor === ep.id && (
                    <StoryboardPanel episodeId={ep.id} refreshKey={planKey} />
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className={`${card} mt-4`}>
        <div className="flex items-center justify-between">
          <h2 className="text-section text-ink">Series</h2>
          <span className="font-mono text-caption text-ink-mute">
            {series.length}
          </span>
        </div>
        <p className="mt-1 text-caption text-ink-mute">
          One premise becomes a season of episode drafts. Near-duplicate
          ideas are skipped and reported honestly.
        </p>
        <div className="mt-3 flex flex-col gap-2">
          <input
            className={inputCls}
            placeholder="Series name (e.g. Sourdough basics)"
            value={seriesName}
            maxLength={200}
            onChange={(e) => setSeriesName(e.target.value)}
          />
          <textarea
            className={`${inputCls} h-16 py-2`}
            placeholder="Premise the episodes should explore"
            value={seriesPremise}
            maxLength={4000}
            onChange={(e) => setSeriesPremise(e.target.value)}
          />
          <div className="flex items-center gap-2">
            <label className="text-caption text-ink-mute">episodes</label>
            <input
              type="number"
              min={3}
              max={30}
              className={`${inputCls} w-24`}
              value={seriesCount}
              onChange={(e) => setSeriesCount(Number(e.target.value) || 20)}
            />
            <button
              className={btnPrimary}
              disabled={busy || !seriesName.trim() || !seriesPremise.trim()}
              onClick={() => void createSeriesOutline()}
            >
              Generate outline
            </button>
          </div>
        </div>
        {series.length === 0 ? (
          <p className="mt-3 text-body2 text-ink-dim">
            No series yet. The outline works with built-in angle templates
            even before any model is installed.
          </p>
        ) : (
          <ul className="mt-3 divide-y divide-line-subtle">
            {series.map((s) => {
              const outlineJob = jobs.find(
                (j) =>
                  j.type.startsWith("series") &&
                  Number(j.payload?.series_id) === s.id,
              );
              return (
                <li key={s.id} className="flex items-center justify-between gap-3 py-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-body2 text-ink">
                        {s.name}
                      </span>
                      {s.method && (
                        <span
                          className={`font-mono text-caption ${
                            s.method === "local_ollama"
                              ? "text-success"
                              : "text-warning"
                          }`}
                        >
                          {s.method}
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 truncate text-caption text-ink-mute">
                      {s.premise}
                    </p>
                    {outlineJob && outlineJob.status !== "succeeded" && (
                      <p className="font-mono text-caption text-ink-mute">
                        outline job #{outlineJob.id} {outlineJob.status}
                        {outlineJob.error ? ` - ${outlineJob.error}` : ""}
                      </p>
                    )}
                    {outlineJob && outlineJob.status === "succeeded" && (
                      <p className="font-mono text-caption text-ink-mute">
                        outline done:
                        {outlineJob.result &&
                        typeof outlineJob.result.accepted === "number"
                          ? ` ${outlineJob.result.accepted} accepted`
                          : ""}
                        {outlineJob.result &&
                          Array.isArray(outlineJob.result.skipped) &&
                          outlineJob.result.skipped.length > 0
                            ? `, ${outlineJob.result.skipped.length} skipped as duplicates`
                            : ""}
                      </p>
                    )}
                  </div>
                  <span className="shrink-0 font-mono text-caption text-ink-mute">
                    {s.episode_count ?? 0}/{s.requested_count} episodes
                  </span>
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
