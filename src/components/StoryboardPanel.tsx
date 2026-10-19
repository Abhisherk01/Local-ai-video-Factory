import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Storyboard } from "../api/types";
import { btnGhost } from "./ui";

const POLL_MS = 2500;

function methodTone(method: string | null): string {
  if (method === "local_ollama") return "text-success";
  if (method && method.startsWith("fallback")) return "text-warning";
  return "text-ink-mute";
}

interface StoryboardPanelProps {
  episodeId: number;
  /** Bump to re-fetch after a storyboard job lands. */
  refreshKey: number;
}

/**
 * Inline scene-plan view for one episode: per-scene narration slice,
 * composed visual prompt, estimated duration. The method label is
 * honest (local_ollama vs fallback_split), per ADR-010.
 */
export default function StoryboardPanel({
  episodeId,
  refreshKey,
}: StoryboardPanelProps) {
  const [plan, setPlan] = useState<Storyboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    let timer: ReturnType<typeof setInterval> | null = null;

    async function load() {
      try {
        const body = await api.storyboard(episodeId);
        if (!aliveRef.current) return;
        setPlan(body.storyboard);
        setError(null);
      } catch (err) {
        if (aliveRef.current) {
          setError(err instanceof ApiError ? err.message : String(err));
        }
      }
    }

    void load();
    // Poll while no plan exists yet - a storyboard job may be running.
    if (plan === null) {
      timer = setInterval(() => void load(), POLL_MS);
    }
    return () => {
      aliveRef.current = false;
      if (timer) clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [episodeId, refreshKey, plan === null]);

  if (error) {
    return (
      <p className="mt-2 text-caption text-danger">
        storyboard: {error}
      </p>
    );
  }
  if (!plan) {
    return (
      <p className="mt-2 font-mono text-caption text-ink-mute">
        waiting for the scene plan...
      </p>
    );
  }

  const shown = expanded ? plan.scenes : plan.scenes.slice(0, 2);

  return (
    <div className="mt-2 rounded-md border border-line-subtle bg-surface px-3 py-2">
      <div className="flex items-center gap-3">
        <span className="text-caption text-ink-dim">
          scene plan - {plan.scene_count} scenes - ~
          {Math.round(plan.total_duration_s)}s
        </span>
        <span className={`font-mono text-caption ${methodTone(plan.method)}`}>
          {plan.method ?? "unknown method"}
        </span>
        <span className="font-mono text-caption text-ink-mute">
          {plan.style_slug}
        </span>
      </div>
      <ol className="mt-2 space-y-2">
        {shown.map((scene) => (
          <li key={scene.idx} className="border-l-2 border-line-subtle pl-3">
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-caption text-ink-mute">
                #{scene.idx} ~{scene.duration_s.toFixed(1)}s
              </span>
            </div>
            <p className="text-caption text-ink-dim">{scene.narration}</p>
            <p className="font-mono text-caption text-ink-mute">
              {scene.visual_prompt}
            </p>
          </li>
        ))}
      </ol>
      {plan.scenes.length > 2 && (
        <button
          className={`${btnGhost} mt-2`}
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "Show less" : `Show all ${plan.scenes.length} scenes`}
        </button>
      )}
    </div>
  );
}
