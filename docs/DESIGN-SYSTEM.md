# Design System — Local AI Video Factory (v0.1)

Source of truth: [`design/tokens.json`](../design/tokens.json). Everything visual derives from those tokens (compiled into Tailwind theme + CSS variables in Phase 2). Changes to look and feel happen in tokens first, never as scattered one-off styles.

## 1. Design principles

1. **Trust through determinism.** This app renders, plans, and publishes on the owner's behalf. Status colors reflect *verified* state only — green means a platform confirmed it, amber means the app needs the owner, red means something failed and the UI offers the recovery action. There are no decorative animations pretending work is happening; determinate progress or skeletons only.
2. **Restraint.** One accent color. Semantic colors reserved for meaning. The interface is graphite and quiet so that video thumbnails, storyboards, and charts are the loudest things on screen.
3. **Density with air.** 15 channels and 100-episode series mean data-heavy tables and calendars: dense rows (36 px) and compact controls, but with a strict 4-px spacing grid so density never becomes clutter.
4. **Offline-first clarity.** Every model, file, and engine has a visible state (installed / downloading / missing / failed with reason). Nothing pretends to be available when it isn't.
5. **Accessible by default.** WCAG AA contrast on all token pairs, full keyboard navigation, visible focus, minimum target sizes, and never color-only status (always icon + text).

## 2. Theme

Dark-first (`laf-dark-graphite`): this is a media-adjacent production tool used for long sessions, and thumbnails/renders must be judged accurately against a neutral dark ground. A light theme is deferred; tokens are structured with semantic slots so a light variant derives without redesign.

## 3. Palette

| Slot | Hex | Usage |
|---|---|---|
| `bg.base` | `#0F1115` | App background |
| `bg.surface` | `#151922` | Cards, panels, table containers |
| `bg.elevated` | `#1B212E` | Modals, popovers, command palette |
| `bg.overlay` | `#212A3B` | Above-modal scrims, tooltips |
| `border.subtle` | `#232B3B` | Dividers, table rules |
| `border.default` | `#2E3947` | Card and input borders |
| `border.strong` | `#405066` | Hovered/focused borders |
| `text.primary` | `#E7EBF3` | Headings, body |
| `text.secondary` | `#9BA6B7` | Labels, metadata |
| `text.muted` | `#6B7688` | Timestamps, IDs (14 px+ only) |
| `accent.default` | `#2DD4BF` | Primary buttons, active nav, selection, key data |
| `accent.hover / pressed / subtle` | `#5EEAD4 / #0FA593 / #103B36` | Interaction states, accent-tinted fills |
| `semantic.success` | `#3DDC97` | Verified real states: Published, QC passed, installed |
| `semantic.warning` | `#F5C04E` | Needs Attention, quota pressure, degraded models |
| `semantic.danger` | `#F2707A` | Failed, validation errors — always paired with an action |
| `semantic.info` | `#6AA6F8` | Neutral notices, scheduled-but-not-running |
| `chart.series` | 7 hues | Analytics only; accent blue-teal leads, ordered for colorblind separation |

**Accent discipline.** Teal marks interactive elements and primary data highlights — nothing else. If everything glows, nothing does. **Semantic discipline.** Success is never used for "we hope this works"; it means a checked, verified result. Warnings always name the cause; errors always carry a next action.

## 4. Typography

| Token | Font | Size/Line | Weight | Usage |
|---|---|---|---|---|
| `caption` | Inter | 12/16 | 500 | Table meta, badges — never body text |
| `body2` | Inter | 13/18 | 400 | Dense table cells, secondary lists |
| `body` | Inter | 14/20 | 400 | Default body, forms |
| `section` | Inter | 16/22 | 600 | Card titles, group headers |
| `pageTitle` | Inter | 20/28 | 600 | Screen titles |
| `display` | Inter | 26/32 | 600 | Dashboard hero, wizard steps |
| mono | JetBrains Mono | matches size | 400/500 | Timestamps, file paths, job IDs, logs, JSON |

Fonts bundle via `@fontsource` packages in Phase 2 — no runtime web fetch, offline-first. Numerals: tabular figures in all tables and metrics.

## 5. Space, radius, elevation, motion

- **Spacing:** 4-px grid — tokens `xs 4 / sm 8 / md 12 / lg 16 / xl 24 / 2xl 32 / 3xl 48`. Screen gutters 24; card padding 16–24.
- **Radius:** `sm 6` (inputs, badges), `md 10` (cards, buttons), `lg 14` (modals), `full` (pills, avatars).
- **Elevation on dark:** borders first, shadows sparingly (`elevated` surfaces + subtle shadow only for floating layers). Depth is communicated by surface color steps, not glow.
- **Motion:** `fast 120ms` (hover, focus), `base 180ms` (panels, drawers), `slow 280ms` (modal transitions), one ease curve. `prefers-reduced-motion` disables non-essential animation. Progress that reflects real work is always truthfully indeterminate or determinate.

## 6. Core component inventory

Button (primary/accent, secondary, danger, ghost), IconButton, Card/Panel, Table (dense, sticky header, row selection), Tabs, TextField/TextArea/Select/Toggle, Modal, Drawer (side panels for episode detail), Command palette (keyboard-first navigation), Timeline/scene strip (storyboard), Progress (determinate, always tied to a real job), StatusBadge, EmptyState, ErrorState (message + cause + action), Toast (transient, actionable), ContextualHelp (inline "why is this happening" expanders), KeyboardShortcutsBar.

Rules every component inherits: loading = skeleton of the real layout (not a naked spinner where layout is known); errors render inline near their context, plus toast only for background failures; every destructive action confirms with the object's name, not a generic "Are you sure?".

## 7. Screen map (the 12 required screens)

| # | Screen | Primary components | Empty-state intent |
|---|---|---|---|
| 1 | First-run setup | Wizard steps, readiness checklist | N/A — explains exactly what will be installed/downloaded before anything happens |
| 2 | Home dashboard | KPI cards, queue summary, next scheduled posts, alerts | "Create your first project" path |
| 3 | Content Studio | Script editor w/ version history, model picker, tone/duration controls | Template-first scripting so the app is useful before any model is installed |
| 4 | Series & episode manager | Series bible view, episode table w/ status, dedup flags | Sample-series suggestion |
| 5 | Storyboard & preview | Scene strip, per-scene engine label, video preview | Scene placeholders generated from script |
| 6 | Clip extraction | Import panel, transcript view, clip candidates w/ scores | Explains rights rules before any URL is accepted |
| 7 | Editing & render queue | Timeline templates, render queue w/ cancel/pause/retry | Queue explanation + render presets |
| 8 | Model & asset manager | Registry table: size, VRAM, license, install state | Pre-checked download plan from Phase 0 |
| 9 | Channel manager | Account cards, per-account rules, isolation indicators | Guided account-prep checklist (Phases 9–11) |
| 10 | Publishing calendar | Day/week views, conflict warnings, per-account filters | Demo-free: explains that nothing publishes while the PC is off |
| 11 | Analytics | Metric cards, trend charts, experiment log | CSV-import first path — never fake metrics |
| 12 | Settings, logs, backups | Settings sections, log viewer w/ redaction, backup/restore | Diagnostic self-test button |

## 8. Accessibility

All token text/background pairs meet WCAG AA (4.5:1 body, 3:1 large text); `text.muted` is restricted to ≥ 14 px metadata. Focus ring: 2-px `accent.focusRing` with 2-px offset, visible on every interactive element. Full keyboard paths for all primary flows; shortcuts don't collide with Windows/system combos. Minimum targets: 32 px dense tables, 40 px comfortable forms. Status is always icon + text + color.

## 9. Iconography & imagery

Lucide icons (ISC), 16-px grid, 1.5 stroke — loaded as bundled components, never hotlinked. Illustration is absent by design; where a visual moment is needed (empty states), the UI uses schematic diagrams built from the token palette.
