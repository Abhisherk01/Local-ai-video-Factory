import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { PathValidation, PrereqCheck, SystemPaths } from "../api/types";
import CheckRow from "../components/CheckRow";
import { btnGhost, btnPrimary, card, inputCls } from "../components/ui";

const STEPS = ["Welcome", "Prerequisites", "Storage", "Finish"] as const;

interface WizardProps {
  onFinish: () => void;
}

/**
 * First-run wizard skeleton (Phase 2).
 *
 * Everything shown here is detected live from the local backend - there
 * are no fake checkmarks. Advisory items (ffmpeg, ollama, disk) are
 * reported honestly with the phase where they become required.
 */
export default function Wizard({ onFinish }: WizardProps) {
  const [step, setStep] = useState(0);

  return (
    <div className="mx-auto flex h-full w-full max-w-2xl flex-col px-6 py-8">
      {/* Stepper */}
      <ol className="mb-6 flex items-center gap-2">
        {STEPS.map((label, index) => (
          <li key={label} className="flex flex-1 items-center gap-2">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                index <= step ? "bg-accent" : "bg-line"
              }`}
            />
            <span
              className={`text-caption ${
                index === step ? "text-ink" : "text-ink-mute"
              }`}
            >
              {label}
            </span>
            {index < STEPS.length - 1 && (
              <span className="h-px flex-1 bg-line-subtle" />
            )}
          </li>
        ))}
      </ol>

      <div className="min-h-0 flex-1">
        {step === 0 && <WelcomeStep />}
        {step === 1 && <PrereqStep />}
        {step === 2 && <StorageStep />}
        {step === 3 && <FinishStep />}
      </div>

      {/* Footer controls */}
      <div className="mt-6 flex items-center justify-between border-t border-line-subtle pt-4">
        <button
          type="button"
          className={btnGhost}
          onClick={() => setStep((s) => Math.max(0, s - 1))}
          disabled={step === 0}
        >
          Back
        </button>
        <span className="text-caption text-ink-mute">
          Step {step + 1} of {STEPS.length}
        </span>
        {step < STEPS.length - 1 ? (
          <button
            type="button"
            className={btnPrimary}
            onClick={() => setStep((s) => Math.min(STEPS.length - 1, s + 1))}
          >
            Continue
          </button>
        ) : (
          <FinishButton onFinish={onFinish} />
        )}
      </div>
    </div>
  );
}

function WelcomeStep() {
  return (
    <section className={card}>
      <h1 className="text-display text-ink">Local AI Video Factory</h1>
      <p className="mt-3 text-body text-ink-dim">
        A local-first studio that will take you from topic to published
        short-form video across your channels - scripting, narration,
        visuals, subtitles, and scheduling - with zero paid AI services.
      </p>
      <ul className="mt-4 space-y-2 text-body2 text-ink-dim">
        <li>
          <span className="text-ink">Everything runs on this machine.</span>{" "}
          No cloud generation, no per-video fees.
        </li>
        <li>
          <span className="text-ink">This is the Phase 2 skeleton.</span>{" "}
          Today you get the desktop shell, the local backend, and honest
          prerequisite detection. The episode pipeline starts in Phase 3.
        </li>
        <li>
          <span className="text-ink">Nothing is installed for you.</span>{" "}
          This wizard reports; scripts/installation stay explicit.
        </li>
      </ul>
    </section>
  );
}

function PrereqStep() {
  const [checks, setChecks] = useState<PrereqCheck[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .prereq()
      .then((result) => {
        if (!cancelled) setChecks(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const hardFailures = useMemo(
    () => (checks ?? []).filter((c) => c.required && !c.ok).length,
    [checks],
  );

  return (
    <section className={card}>
      <h2 className="text-page-title text-ink">Prerequisites</h2>
      <p className="mt-1 text-caption text-ink-dim">
        Detected live from this machine. Nothing was installed or changed.
      </p>

      {error && (
        <p className="mt-4 text-body2 text-danger">
          Detection failed: {error}
        </p>
      )}

      {checks === null && !error && (
        <p className="mt-4 text-body2 text-ink-mute">Checking...</p>
      )}

      {checks && (
        <ul className="mt-3 divide-y divide-line-subtle">
          {checks.map((check) => (
            <CheckRow key={check.name} check={check} />
          ))}
        </ul>
      )}

      {checks && hardFailures > 0 && (
        <p className="mt-3 text-caption text-danger">
          {hardFailures} required item(s) missing - see INSTALLATION.md before
          continuing.
        </p>
      )}
    </section>
  );
}

function StorageStep() {
  const [paths, setPaths] = useState<SystemPaths | null>(null);
  const [draftPath, setDraftPath] = useState<string>("");
  const [validation, setValidation] = useState<PathValidation | null>(null);
  const [validating, setValidating] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .paths()
      .then((result) => {
        if (cancelled) return;
        setPaths(result);
        setDraftPath(result.data_dir);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!draftPath) return;
    let cancelled = false;
    setValidating(true);
    const timer = setTimeout(() => {
      api
        .validatePath(draftPath)
        .then((result) => {
          if (!cancelled) setValidation(result);
        })
        .catch(() => {
          if (!cancelled) setValidation(null);
        })
        .finally(() => {
          if (!cancelled) setValidating(false);
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [draftPath]);

  return (
    <section className={card}>
      <h2 className="text-page-title text-ink">Storage</h2>
      <p className="mt-1 text-caption text-ink-dim">
        Where episodes, databases, and (later) model files live. The desktop
        shell already chose this directory; you can point the checker at
        another location to validate it.
      </p>

      {paths && (
        <dl className="mt-4 space-y-3">
          <div>
            <dt className="text-caption text-ink-mute">Data directory</dt>
            <dd className="mt-1">
              <input
                className={inputCls}
                value={draftPath}
                onChange={(event) => setDraftPath(event.target.value)}
                spellCheck={false}
              />
            </dd>
          </div>
          <div>
            <dt className="text-caption text-ink-mute">Models directory</dt>
            <dd className="mt-1 font-mono text-caption text-ink-dim">
              {paths.models_dir}
            </dd>
          </div>
        </dl>
      )}

      <div className="mt-4 min-h-10">
        {validating && (
          <p className="text-caption text-ink-mute">Validating...</p>
        )}
        {!validating && validation && (
          <ul className="space-y-1 text-caption">
            <li className={validation.exists ? "text-ink-dim" : "text-warning"}>
              {validation.exists
                ? "Directory exists"
                : "Directory does not exist yet (created on first use)"}
            </li>
            <li className={validation.writable ? "text-success" : "text-danger"}>
              {validation.writable ? "Writable" : "Not writable"}
            </li>
            <li className="text-ink-dim">
              Free space: {validation.free_gb ?? "unknown"} GB
              {(validation.free_gb ?? 0) < 60 && (
                <span className="text-warning">
                  {" "}
                  - below the 60 GB target for Phase 3
                </span>
              )}
            </li>
          </ul>
        )}
      </div>
    </section>
  );
}

function FinishStep() {
  return (
    <section className={card}>
      <h2 className="text-page-title text-ink">Finish</h2>
      <p className="mt-2 text-body2 text-ink-dim">
        Setup state will be saved locally (onboarding_complete). The studio
        home opens next; production features arrive with later phases.
      </p>
      <ul className="mt-4 space-y-2 text-body2 text-ink-dim">
        <li>Phase 3 - durable job queue + episode data model</li>
        <li>Phase 4 - local LLM scripting (Ollama)</li>
        <li>Phase 5 - visual generation engines</li>
      </ul>
    </section>
  );
}

function FinishButton({ onFinish }: { onFinish: () => void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function complete() {
    setSaving(true);
    setError(null);
    try {
      await api.putSettings({
        onboarding_complete: "true",
        onboarded_at: new Date().toISOString(),
      });
      onFinish();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <span className="flex items-center gap-3">
      {error && <span className="text-caption text-danger">{error}</span>}
      <button type="button" className={btnPrimary} onClick={complete} disabled={saving}>
        {saving ? "Saving..." : "Finish setup"}
      </button>
    </span>
  );
}
