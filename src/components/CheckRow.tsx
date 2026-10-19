import type { PrereqCheck } from "../api/types";

/** One prerequisite check row: dot indicator, mono name, honest detail. */
export default function CheckRow({ check }: { check: PrereqCheck }) {
  const tone = check.ok
    ? "bg-success"
    : check.required
      ? "bg-danger"
      : "bg-warning";

  return (
    <li className="flex items-start gap-3 py-2">
      <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${tone}`} />
      <div className="min-w-0">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-body2 text-ink">{check.name}</span>
          {!check.required && (
            <span className="text-caption text-ink-mute">optional now</span>
          )}
        </div>
        <p className="text-caption text-ink-dim break-words">{check.detail}</p>
      </div>
    </li>
  );
}
