# Aesthetic direction

Moodboard images in this folder (curated in `design/references/`). Two threads, both applied in `@bitfit/ui`:

**Swiss / International Typographic Style** — NYC subway signage, Zürich Card. Bold grotesque type, black headers, high-contrast **saturated color-coding**, strong grid, big legible numerals. → `Badge` (route-bullet / category-pill), bold headings, the `--series-*` palette.

**Dark-mode data widgets** — Apple Watch faces, Velovories. Compact **"big number + label + unit + mini-chart"** tiles on dark canvases, vivid categorical accents. → `StatTile` (especially `tone="dark"`), `.stat-number` treatment, `MetricChart` embedded in tiles.

Design guidance for building screens:
- Lead with the number. Metric value large (`.stat-number`), label small and uppercase, unit muted.
- Color carries meaning — use `--series-1..6` by metric, consistently; never decoratively recycle.
- High contrast, generous spacing, few type sizes. Let the grid do the work.
- Dark data-dashboards: `StatTile tone="dark"` tiles in a grid read like the watch-face references.
