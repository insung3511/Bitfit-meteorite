# @bitfit/ui — how to build with this design system

A small health-analytics component library. Components are **props-only** — no data fetching, routing, or storage. Style with Tailwind utility classes plus the CSS-variable tokens below.

## Setup & theming

- Import the stylesheet once at the app root: `import "@bitfit/ui/styles.css"`. It carries the tokens **and** the compiled utilities — nothing renders styled without it.
- Tokens live on `:root`. Dark mode resolves automatically from `prefers-color-scheme`, and can be forced by stamping `data-theme="dark"` (or `"light"`) on the root element. Toggle that attribute to switch themes.
- No provider/wrapper component is required. There is no web font — the family is the system grotesque stack (`Arial, Helvetica, sans-serif`), matching the Swiss-signage look of the references.

## Tokens (CSS variables)

Reference these as `var(--name)` in `style={}` or Tailwind arbitrary values like `bg-[var(--viz-surface)]`.

| Token | Use |
|-------|-----|
| `--background`, `--foreground` | page bg / text |
| `--viz-surface` | card / tile surface |
| `--viz-muted`, `--viz-grid`, `--viz-axis` | chart chrome |
| `--series-1` … `--series-6` | categorical hues, **fixed order** — assign by meaning, never recycle. blue, aqua, yellow, green, violet, red |

Big metric numbers use the `.stat-number` class (heavy weight, tight tracking, tabular numerals) — `StatTile` applies it for you.

## Styling idiom

Tailwind utility classes, exactly as the components use them. Common vocabulary in this system:

- Surfaces: `rounded-xl border border-black/10 bg-[var(--viz-surface)] p-4 dark:border-white/15`
- Muted text: `text-black/60 dark:text-white/60` (and `/45`, `/40` for fainter)
- Solid button: `bg-black text-white dark:bg-white dark:text-black`
- Series color: `style={{ color: "var(--series-1)" }}` or `bg-[var(--series-1)]`

Prefer these tokens/utilities over inventing new colors, so designs stay on-palette in light and dark.

## Components

Primitives: `Card`, `Button` (`variant`: solid | outline | ghost), `Input`, `Select`, `Alert` (`tone`: error | info), `Badge` (`variant`: pill | bullet), `StatTile`, `AppHeader`.
Data: `MetricChart` (recharts area/line/bar). Composites: `WorkspacePanel`, `AnomalyList`, `CoachingCard`.

Read `_ds/<folder>/styles.css` and each component's `.d.ts` / `.prompt.md` for exact props before composing.

## Idiomatic snippet

```tsx
import { StatTile, MetricChart, Badge } from "@bitfit/ui";

<div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
  <StatTile tone="dark" label="Resting HR" value="62" unit="bpm" accent="var(--series-1)" />
  <StatTile tone="dark" label="Steps" value="8,647" accent="var(--series-3)" />
</div>

<div className="rounded-xl border border-black/10 bg-[var(--viz-surface)] p-4 dark:border-white/15">
  <div className="mb-3 flex items-center gap-2">
    <Badge color="var(--series-5)">Sleep</Badge>
    <h3 className="text-sm font-medium">Sleep duration</h3>
  </div>
  <MetricChart label="Sleep" color="var(--series-5)" points={points} chartType="area" embedded />
</div>
```
