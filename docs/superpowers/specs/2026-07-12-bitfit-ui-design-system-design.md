# Design: `@bitfit/ui` Design System Package

**Date:** 2026-07-12
**Status:** Approved decisions, pending spec review
**Goal:** Extract the reusable UI of the `frontend` Next.js app into a standalone, compiled component library (`packages/ui`) so it can be synced to claude.ai/design via `/design-sync`. The design agent will then build screens out of the app's *real* components.

## Context

`bitfit_meteorite` is a health-analytics app: a FastAPI backend + a Next.js 16 / React 19 / Tailwind v4 frontend (`frontend/`). The frontend has a small but coherent design language — CSS-variable tokens (light/dark) and a consistent component vocabulary — but everything lives inline in app screens (`frontend/app/**`). There is no component library, no Storybook, no `dist/`. `/design-sync` requires a compiled, standalone library, so this project creates one.

**Non-goals:** This work does **not** modify the `frontend` app. Rewiring the app to consume `@bitfit/ui` is a separate, later task. The in-flight `feat/takeout-dnd-import` branch is untouched.

## Decisions (locked)

| Decision | Choice | Rationale |
|---|---|---|
| Component scope | **Core kit + app patterns + 2 reference-inspired** | Full reusable vocabulary + composites + `StatTile`/`Badge` drawn from the `design/` references. |
| Preview source | **Storybook** | design-sync captures + verifies previews from the real Storybook render — highest fidelity. |
| App refactor | **None now** | Standalone package first; no risk to in-flight app branch. |
| Styling approach | **A — keep Tailwind utilities, ship compiled CSS** | Zero component rewriting, existing components keep app parity; aesthetic lean is additive. |
| Design references | **Ship as guidelines + extend components** | Moodboard images + style note uploaded to the design project; new components + heading/number type treatment embody the aesthetic. |
| Package build | **tsup (esbuild)** | Simplest esbuild-based library build; design-sync bundles esbuild output. |

### Design references / aesthetic direction

`design/references/` holds seven inspiration images the user curated. They share a coherent language:

- **Swiss / International Typographic Style** (NYC Underground signage, Zürich Card) — bold grotesque type (Helvetica/Arial family, which the app already uses), black headers, high-contrast **saturated color-coding**, strong grid, big legible numerals.
- **Dark-mode data widgets** (Apple Watch faces, Velovories) — compact **"big number + label + unit + mini-chart"** metric tiles on dark canvases, vivid categorical accents.

This maps directly onto the app's existing `--series-*` categorical palette and health-metric domain. Incorporated two ways:

1. **Guidelines upload** — the seven images are copied into the design-sync output under `guidelines/` alongside a short `guidelines/aesthetic.md` style note, so the claude.ai/design agent sees the moodboard.
2. **Component extension** — two new components (`StatTile`, `Badge`) embody the tile/route-bullet patterns, and a heading/number **type treatment** (heavier weight, tighter tracking on headings and numerals) leans the system toward the bold Swiss look. Applied additively: existing components keep app parity; only the new components and an opt-in heading/`.stat-number` treatment carry the lean.

### Rejected alternatives

- **Rewrite components to CSS-modules/plain CSS** — full rewrite of working components, drift risk, discards existing parity.
- **Inline all styles via `style={}`** — kills the token system and dark mode.
- **Charts-only / core-only scope** — user chose the richest scope.
- **Rewire the app now** — deferred to avoid touching uncommitted app files and the Next 16 build mid-branch.

## Architecture

New monorepo subpackage. The frontend app and backend are unchanged.

```
bitfit_meteorite/
├── frontend/                 (unchanged Next.js app)
├── backend/                  (unchanged)
├── packages/
│   └── ui/                   ← NEW
│       ├── package.json      name "@bitfit/ui"; exports "." → dist, "./styles.css" → dist/styles.css
│       ├── tsconfig.json
│       ├── tsup.config.ts    esbuild build → dist/ (ESM + .d.ts)
│       ├── src/
│       │   ├── index.ts      barrel export of all components + types
│       │   ├── tokens.css    --viz-* / --series-* / --background / --foreground (light + dark + [data-theme])
│       │   ├── styles.css    @import "tailwindcss"; @source "./"; @import "./tokens.css";  (CSS build input)
│       │   ├── types.ts      ChartType, RangeDays, SummaryPoint, Anomaly, PanelConfig (no app coupling)
│       │   ├── Card.tsx
│       │   ├── Button.tsx
│       │   ├── Input.tsx
│       │   ├── Select.tsx
│       │   ├── Alert.tsx
│       │   ├── Badge.tsx        ← NEW (reference-inspired)
│       │   ├── StatTile.tsx     ← NEW (reference-inspired)
│       │   ├── AppHeader.tsx
│       │   ├── MetricChart.tsx
│       │   ├── WorkspacePanel.tsx
│       │   ├── AnomalyList.tsx
│       │   ├── CoachingCard.tsx
│       │   └── *.stories.tsx  (one story file per component)
│       └── .storybook/
│           ├── main.ts        framework: react-vite (or @storybook/react); stories glob src/**/*.stories.tsx
│           └── preview.ts     imports "../src/styles.css" so previews carry tokens + utilities
├── design/
│   └── references/           existing 7 inspiration images (copied into design-sync guidelines/ at sync time)
└── docs/superpowers/specs/2026-07-12-bitfit-ui-design-system-design.md
```

## Components

Each is a single-purpose, props-only unit — no `fetch`, no `localStorage`, no routing, no `next/*` imports. Every prop shape is derived from the current app usage.

### Primitives

- **Card** — `rounded-xl border bg-[var(--viz-surface)] p-4` container. Props: `title?`, `subtitle?`, `selected?` (adds the selected border/shadow from WorkspacePanel), `onClick?`, `children`.
- **Button** — variants `solid` (black/white — the primary CTA), `outline` (bordered — Add signal/Undo/Restore), `ghost` (text/underline — logout/remove). Props: `variant`, `disabled?`, standard button props.
- **Input** — bordered transparent text field from the login form. Props: standard input props + `invalid?`.
- **Select** — bordered transparent select from WorkspacePanel controls. Props: standard select props + `label?`.
- **Alert** — red bordered callout (`role="alert"`) from the dashboard error/backend states. Props: `tone` (`error` initially; `info` optional), `children`.
- **Badge** — reference-inspired color-coded pill/bullet (Zürich Card bars, MTA route bullets). Props: `color` (a `--series-*` var ref or CSS color), `variant` (`pill` | `bullet`), `children`. Bold, high-contrast, white text on saturated fill. Used to label metrics/categories.
- **StatTile** — reference-inspired metric tile (Apple Watch / Velovories widgets): big number + label + unit, optional trend/mini-chart slot, optional accent color. Props: `label`, `value` (string|number), `unit?`, `caption?`, `accent?` (color var), `chart?` (ReactNode — e.g. an embedded `MetricChart`), `tone` (`light` | `dark`). Uses the `.stat-number` type treatment (heavy weight, tight tracking).
- **AppHeader** — the nav bar from `layout.tsx`: brand link + nav links + right slot. Props: `brand`, `links: {label, href}[]`, `right?` (ReactNode, e.g. a logout Button). Uses plain `<a>` (no `next/link`) so it renders standalone.

### Data-viz

- **MetricChart** — the recharts composed chart, extracted essentially verbatim (it is already props-only: `label`, `color`, `points`, `chartType`, `showBaseline`, `embedded`). `recharts` is bundled into the JS bundle.

### Composites (decoupled from app data)

- **WorkspacePanel** — the chart panel with title, remove button, embedded MetricChart, and chart/window/baseline controls. Props: `panel: PanelConfig`, `points: SummaryPoint[] | null`, `selected?`, `onSelect?`, `onChange?`, `onRemove?` — callbacks default to no-ops. `PanelConfig` is a local type (title, metric, color, chartType, rangeDays, showBaseline), NOT the app's `workspace.ts` type.
- **AnomalyList** — presentational list carved from the dashboard "Anomalies" section. Props: `anomalies: Anomaly[]`, `formatLabel?`. Renders the divided list with series-colored deltas; handles empty state.
- **CoachingCard** — the sleep-coaching card. Props: `state` (`idle | loading | ready | error`), `text?`, `error?`, `onRun?`, `disclaimer?`. Purely presentational — no fetch.

## Data flow

None at runtime beyond props. Components are pure/presentational; the only stateful component is `MetricChart` internally (recharts). Storybook stories provide realistic fixture data (a small hand-written `SummaryPoint[]`, sample anomalies) so previews render meaningfully.

## Styling & tokens

- `tokens.css` holds every custom property currently in `frontend/app/globals.css`: `--background`, `--foreground`, `--viz-surface`, `--viz-muted`, `--viz-grid`, `--viz-axis`, `--series-1..6` — with the existing light values, the `@media (prefers-color-scheme: dark)` block, **and** a `:root[data-theme="dark"]` / `:root[data-theme="light"]` override so claude.ai/design's theme toggle (which stamps `data-theme`) switches themes deterministically.
- `styles.css` is the Tailwind v4 entry: `@import "tailwindcss";` + `@source` pointed at the component sources so only used utilities compile, + `@import "./tokens.css";`. The CSS build (`@tailwindcss/cli`) emits `dist/styles.css` — the single stylesheet design-sync ships; its `@import` closure carries both utilities and tokens.
- **Type treatment (reference lean):** `tokens.css` adds a `.stat-number` class (heavy weight ~700, tight `letter-spacing`, tabular numerals via `font-variant-numeric: tabular-nums`) for big metric values, used by `StatTile`. Headings in new components use bolder weights. The base font family stays the app's grotesque stack (`Arial, Helvetica, sans-serif`) — already Swiss-appropriate — so no web-font is added. Existing components' type is unchanged (parity preserved).

## Build

- **JS:** `tsup src/index.ts --format esm --dts`. `react` + `react-dom` marked external (peer deps); `recharts` bundled in. Output: `dist/index.mjs` + `dist/index.d.ts`.
- **CSS:** `@tailwindcss/cli -i src/styles.css -o dist/styles.css`.
- `package.json` scripts: `build` (runs both), `build:js`, `build:css`, `storybook`, `build-storybook`.
- `package.json` `exports`: `"."` → `./dist/index.mjs` (+ types), `"./styles.css"` → `./dist/styles.css`.

## design-sync integration

- Shape: **storybook**. `.design-sync/config.json` records `shape: "storybook"`, `storybookConfigDir: "packages/ui/.storybook"`, a `globalName`, and `readmeHeader: ".design-sync/conventions.md"`.
- Conventions header teaches the design agent: the Tailwind utility idiom (with a family table of the real class names used — `bg-[var(--viz-surface)]`, `border-black/10`, `rounded-xl`, the `--series-*` token refs), the token vars, the `.stat-number` treatment, dark-mode via `data-theme`, and one idiomatic build snippet.
- **Guidelines:** the 7 `design/references/*.jpg` images are copied into the output `guidelines/` dir, plus `guidelines/aesthetic.md` — a short written style note naming the Swiss-type + dark-tile direction and how it maps to the tokens/components. design-sync ships `guidelines/**` to the project so the agent sees the moodboard.
- A new claude.ai/design project is created for the first sync.

## Testing / verification

Evidence required before claiming done, in order:
1. `pnpm --filter @bitfit/ui build:js` succeeds; `dist/index.mjs` + `dist/index.d.ts` exist.
2. `build:css` succeeds; `dist/styles.css` contains the token vars and the used utilities.
3. `build-storybook` succeeds.
4. Every component's story renders without error (visual check).
5. design-sync's own screenshot-verification loop grades each preview against the Storybook render (runs during the sync).

## Open implementation details (decide during build)

- Storybook framework: `@storybook/react-vite` (fast, esbuild-friendly) vs `@storybook/nextjs`. Lean react-vite since the package is framework-agnostic.
- Package manager: repo `frontend` uses npm (has `package-lock`-style setup). The monorepo may need a workspace root or the package can install independently. Resolve at scaffold time; do not disturb `frontend`'s install.
- Exact `globalName` for the design bundle (e.g. `BitfitUI`).
