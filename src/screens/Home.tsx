import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { SystemPaths } from "../api/types";
import StatusChip from "../components/StatusChip";
import { card } from "../components/ui";

interface HomeProps {
  version: string;
}

/**
 * Studio home placeholder (Phase 2).
 * Confirms the shell + backend + database loop is alive and shows what
 * ships next. Honest placeholder - no fake pipeline data.
 */
export default function Home({ version }: HomeProps) {
  const [paths, setPaths] = useState<SystemPaths | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .paths()
      .then((result) => {
        if (!cancelled) setPaths(result);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col px-6 py-8">
      <section className={card}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-display text-ink">Studio</h1>
            <p className="mt-1 text-body2 text-ink-dim">
              Shell, backend, and database are online. The content pipeline
              lives in the Pipeline tab.
            </p>
          </div>
          <StatusChip tone="ok" label={`backend v${version}`} />
        </div>
      </section>

      <section className={`${card} mt-4`}>
        <h2 className="text-section text-ink">What ships next</h2>
        <ol className="mt-3 space-y-2 text-body2 text-ink-dim">
          <li>
            <span className="font-mono text-caption text-accent">Phase 4</span>{" "}
            - install Ollama + a voice model and verify the model-backed
            paths end-to-end (queue and fallback paths already ship)
          </li>
          <li>
            <span className="font-mono text-caption text-accent">Phase 5</span>{" "}
            - visual generation engines behind the same adapter registry
            (honest method labels, GPU concurrency 1)
          </li>
        </ol>
      </section>

      {paths && (
        <section className={`${card} mt-4`}>
          <h2 className="text-section text-ink">Local paths</h2>
          <dl className="mt-3 space-y-2 font-mono text-caption text-ink-dim">
            <div>
              <dt className="text-ink-mute">data_dir</dt>
              <dd>{paths.data_dir}</dd>
            </div>
            <div>
              <dt className="text-ink-mute">db_path</dt>
              <dd>{paths.db_path}</dd>
            </div>
          </dl>
        </section>
      )}
    </div>
  );
}
