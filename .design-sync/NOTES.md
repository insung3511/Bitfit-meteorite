# design-sync notes — @bitfit/ui

## Repo facts
- DS package: `packages/ui` (`@bitfit/ui`), storybook shape. Storybook config: `packages/ui/.storybook`.
- Converter run from repo root; `--entry packages/ui/dist/index.js` (the package isn't installed under its own name in its source repo), `--node-modules packages/ui/node_modules`.
- Build: `npm --prefix packages/ui run build` runs **both** `build:js` (tsup) and `build:css` (@tailwindcss/cli). Always run the full script.

## Fixes applied (traceable)
- **[GENERAL] react must stay a shared external in the bundle.** Two dist issues emitted a runtime `__require("react")` that throws in the design bundle:
  1. recharts has no `exports` map and a CJS `main`; forced ESM via `esbuildOptions.mainFields/conditions` in `tsup.config.ts`.
  2. recharts pulls `use-sync-external-store` (CJS-only); an esbuild `onResolve` plugin redirects every `use-sync-external-store` entry to `src/shims/use-sync-external-store-with-selector.mjs`, an ESM reimplementation on React 19's native `useSyncExternalStore`.
  Verify after any recharts/react bump: `grep -c '__require("react")' packages/ui/dist/index.js` must be 0.
- **[GRID_OVERFLOW]** MetricChart, StatTile, WorkspacePanel render wider than a grid cell → `cfg.overrides.<Name>.cardMode: "column"`.

## Verification (first sync)
- 12/12 components, every story graded `match` from storybook-vs-preview sheets. No `close`, no skips.

## Re-sync risks (watch-list)
- **recharts / react version bumps** — re-check the `__require` grep above; the `use-sync-external-store` shim reimplements that package's ponyfill, so if recharts changes its internal store it may need revisiting.
- **tsup `clean: true` wipes `dist/`** — running `build:js` alone deletes `dist/styles.css` and the converter silently falls back to a CSS-in-JS stub (unstyled previews). The `buildCmd` runs both; never run `build:js` standalone before a converter run.
- Story fixtures are inlined in `packages/ui/src/_sample.ts` (deterministic, no `Date.now()`/random) — stable across captures.
- Guidelines images live in `design/references/` and are copied into `ds-bundle/guidelines/` at upload; `guidelines/aesthetic.md` is authored in `.design-sync/guidelines/`.
