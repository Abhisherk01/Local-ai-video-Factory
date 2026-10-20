import { useEffect, useState } from "react";
import { api } from "./api/client";
import type { BackendStatus } from "./api/types";
import StatusChip from "./components/StatusChip";
import { btnGhost, btnPrimary } from "./components/ui";
import Home from "./screens/Home";
import Pipeline from "./screens/Pipeline";
import Wizard from "./screens/Wizard";

/**
 * App shell state machine:
 *   starting -> (poll /health until the backend is up, max ~30 s)
 *            -> ready -> [onboarding_complete ? Home : Wizard]
 *            -> error (honest failure screen with fix hints)
 */
export default function App() {
  const [backend, setBackend] = useState<BackendStatus>({ state: "starting" });
  const [onboarded, setOnboarded] = useState<boolean | null>(null);
  const [screen, setScreen] = useState<"home" | "pipeline">("home");

  useEffect(() => {
    let cancelled = false;
    const startedAt = Date.now();
    const deadlineMs = 30_000;

    function describe(error: unknown): string {
      const message = error instanceof Error ? error.message : String(error);
      if (message.includes("unreachable") || message.includes("backend starting")) {
        return (
          "The backend process did not come up within 30 seconds. " +
          "Check that Python 3.12 exists (py -3.12 -V), that the repo venv " +
          "is installed (pip install -r backend/requirements.txt), or set " +
          "LAF_PYTHON to a Python 3.12 executable and restart the app."
        );
      }
      return message;
    }

    (async function poll() {
      while (!cancelled) {
        try {
          const health = await api.health();
          if (cancelled) return;
          setBackend({ state: "ready", version: health.version });
          try {
            const settings = await api.getSettings();
            if (!cancelled) {
              setOnboarded(settings.values["onboarding_complete"] === "true");
            }
          } catch {
            if (!cancelled) setOnboarded(false);
          }
          return;
        } catch (error) {
          if (cancelled) return;
          if (Date.now() - startedAt > deadlineMs) {
            setBackend({ state: "error", message: describe(error) });
            return;
          }
          await new Promise((resolve) => setTimeout(resolve, 800));
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex h-full flex-col bg-base">
      {/* Title bar strip */}
      <header className="flex h-10 shrink-0 items-center justify-between border-b border-line-subtle bg-surface px-4">
        <span className="text-caption font-medium text-ink-dim">
          Local AI Video Factory
        </span>
        {backend.state === "ready" ? (
          <StatusChip tone="ok" label="local backend" />
        ) : backend.state === "starting" ? (
          <StatusChip tone="info" label="starting" />
        ) : (
          <StatusChip tone="error" label="backend error" />
        )}
      </header>

      <main className="min-h-0 flex-1 overflow-auto">
        {backend.state === "starting" && (
          <div className="flex h-full flex-col items-center justify-center gap-3">
            <span className="h-6 w-6 animate-spin rounded-full border-2 border-line border-t-accent" />
            <p className="text-body2 text-ink-dim">Starting local backend...</p>
          </div>
        )}

        {backend.state === "error" && (
          <div className="mx-auto mt-16 max-w-xl px-6">
            <div className="rounded-lg border border-danger/30 bg-danger-subtle p-6">
              <h1 className="text-page-title text-danger">
                Backend failed to start
              </h1>
              <p className="mt-2 text-body2 text-ink-dim">{backend.message}</p>
            </div>
          </div>
        )}

        {backend.state === "ready" && onboarded === null && (
          <div className="flex h-full items-center justify-center">
            <p className="text-body2 text-ink-mute">Loading workspace...</p>
          </div>
        )}

        {backend.state === "ready" && onboarded === false && (
          <Wizard onFinish={() => setOnboarded(true)} />
        )}

        {backend.state === "ready" && onboarded === true && (
          <>
            <nav className="flex shrink-0 items-center gap-2 border-b border-line-subtle bg-surface px-4 py-2">
              <button
                className={screen === "home" ? btnPrimary : btnGhost}
                onClick={() => setScreen("home")}
              >
                Studio
              </button>
              <button
                className={screen === "pipeline" ? btnPrimary : btnGhost}
                onClick={() => setScreen("pipeline")}
              >
                Pipeline
              </button>
            </nav>
            {screen === "home" ? (
              <Home version={backend.version} />
            ) : (
              <Pipeline version={backend.version} />
            )}
          </>
        )}
      </main>
    </div>
  );
}
