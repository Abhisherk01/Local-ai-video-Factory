/** Small shared class constants so screens stay visually consistent. */

export const btnPrimary =
  "inline-flex items-center justify-center gap-2 rounded-md bg-accent px-4 h-8 " +
  "text-body2 font-medium text-on-accent transition-colors duration-150 " +
  "hover:bg-accent-hover active:bg-accent-pressed " +
  "disabled:opacity-40 disabled:pointer-events-none";

export const btnGhost =
  "inline-flex items-center justify-center gap-2 rounded-md border border-line px-4 h-8 " +
  "text-body2 text-ink-dim transition-colors duration-150 " +
  "hover:text-ink hover:border-line-strong disabled:opacity-40 disabled:pointer-events-none";

export const card =
  "rounded-lg border border-line-subtle bg-surface p-6";

export const inputCls =
  "h-8 w-full rounded-md border border-line bg-base px-3 text-body2 text-ink " +
  "placeholder:text-ink-mute focus:border-accent focus:outline-none " +
  "font-mono";

export const chip =
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-caption";
