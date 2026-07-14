import { MetricChart } from "./MetricChart";
import type { ChartType, PanelConfig, RangeDays, SummaryPoint } from "./types";

export type WorkspacePanelProps = {
  panel: PanelConfig;
  points: SummaryPoint[] | null;
  selected?: boolean;
  onSelect?: () => void;
  onChange?: (patch: Partial<PanelConfig>) => void;
  onRemove?: () => void;
};

/** Chart panel with title, remove control, embedded chart, and view controls. */
export function WorkspacePanel({
  panel,
  points,
  selected = false,
  onSelect,
  onChange,
  onRemove,
}: WorkspacePanelProps) {
  return (
    <article
      className={`rounded-xl border bg-[var(--viz-surface)] p-4 transition ${
        selected
          ? "border-black/50 shadow-sm dark:border-white/60"
          : "border-black/10 dark:border-white/15"
      }`}
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          {onSelect ? (
            <button
              type="button"
              onClick={onSelect}
              aria-pressed={selected}
              className="text-left text-sm font-medium"
            >
              {panel.title}
            </button>
          ) : (
            <h3 className="text-sm font-medium">{panel.title}</h3>
          )}
          <p className="mt-0.5 text-xs text-black/45 dark:text-white/45">
            {panel.metric} · {panel.rangeDays} days
          </p>
        </div>
        {onRemove && (
          <button
            type="button"
            title="Remove panel"
            aria-label={`Remove ${panel.title} panel`}
            onClick={onRemove}
            className="rounded-md px-2 py-1 text-xs text-black/45 hover:bg-black/5 hover:text-black dark:text-white/45 dark:hover:bg-white/10 dark:hover:text-white"
          >
            Remove
          </button>
        )}
      </div>

      {points ? (
        <MetricChart
          label={panel.title}
          color={panel.color}
          points={points}
          chartType={panel.chartType}
          showBaseline={panel.showBaseline}
          embedded
        />
      ) : (
        <div className="flex h-44 items-center justify-center rounded-lg border border-black/5 text-sm text-black/40 dark:border-white/10 dark:text-white/40">
          Loading {panel.title}…
        </div>
      )}

      {onChange && (
        <div className="mt-3 grid grid-cols-2 gap-2 border-t border-black/10 pt-3 text-xs dark:border-white/15 sm:grid-cols-4">
          <label className="flex flex-col gap-1 text-black/50 dark:text-white/50">
            Chart
            <select
              value={panel.chartType}
              onChange={(event) =>
                onChange({ chartType: event.target.value as ChartType })
              }
              className="rounded-md border border-black/10 bg-transparent px-2 py-1 text-xs text-inherit dark:border-white/15"
            >
              <option value="area">Area</option>
              <option value="line">Line</option>
              <option value="bar">Bars</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-black/50 dark:text-white/50">
            Window
            <select
              value={panel.rangeDays}
              onChange={(event) =>
                onChange({ rangeDays: Number(event.target.value) as RangeDays })
              }
              className="rounded-md border border-black/10 bg-transparent px-2 py-1 text-xs text-inherit dark:border-white/15"
            >
              <option value={7}>7 days</option>
              <option value={30}>30 days</option>
              <option value={90}>90 days</option>
            </select>
          </label>
          <label className="col-span-2 flex items-center gap-2 self-end pb-1 text-black/60 dark:text-white/60 sm:col-span-2">
            <input
              type="checkbox"
              checked={panel.showBaseline}
              onChange={(event) =>
                onChange({ showBaseline: event.target.checked })
              }
            />
            Show 30-day baseline
          </label>
        </div>
      )}
    </article>
  );
}
