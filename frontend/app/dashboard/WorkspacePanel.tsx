"use client";

import MetricChart, { type SummaryPoint } from "./MetricChart";
import type { ChartType, RangeDays, WorkspacePanel as Panel } from "./workspace";

type Props = {
  panel: Panel;
  points: SummaryPoint[] | null;
  selected: boolean;
  onSelect: () => void;
  onChange: (patch: Partial<Panel>) => void;
  onRemove: () => void;
};

export default function WorkspacePanel({
  panel,
  points,
  selected,
  onSelect,
  onChange,
  onRemove,
}: Props) {
  const signalColor = panel.color;

  return (
    <article
      className={`board-card relative overflow-hidden rounded-[4px] p-4 transition ${
        selected
          ? "ring-2 ring-[var(--ink)] ring-offset-2 ring-offset-[var(--board)]"
          : "hover:-translate-y-0.5 hover:shadow-md"
      }`}
      onClick={onSelect}
    >
      <div className="absolute inset-x-0 top-0 h-1" style={{ backgroundColor: signalColor }} />
      <div className="mb-4 flex items-start justify-between gap-3 pt-1">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex h-8 min-w-8 items-center justify-center rounded-full text-xs font-black text-white" style={{ backgroundColor: signalColor }}>
            {panel.title.slice(0, 1)}
          </span>
          <div className="min-w-0">
            <div className="eyebrow">{panel.rangeDays} day signal</div>
            <h3 className="mt-1 truncate text-base font-black tracking-tight">{panel.title}</h3>
            <p className="mt-0.5 text-[11px] font-medium uppercase tracking-[0.08em] text-[var(--ink-soft)]">
              {panel.metric.replaceAll("_", " ")}
            </p>
          </div>
        </div>
        <button
          type="button"
          title="Remove panel"
          aria-label={`Remove ${panel.title} panel`}
          onClick={(event) => {
            event.stopPropagation();
            onRemove();
          }}
          className="rounded px-2 py-1 text-[10px] font-bold uppercase tracking-[0.08em] text-[var(--ink-soft)] hover:bg-black/5 hover:text-[var(--ink)] dark:hover:bg-white/10"
        >
          Hide
        </button>
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
        <div className="flex h-44 items-center justify-center border border-dashed border-[var(--line)] text-sm text-[var(--ink-soft)]">
          Loading {panel.title}…
        </div>
      )}

      <div
        className="mt-4 grid grid-cols-2 gap-3 border-t border-[var(--line)] pt-3 text-xs sm:grid-cols-4"
        onClick={(event) => event.stopPropagation()}
      >
        <label className="eyebrow flex flex-col gap-1">
          Chart
          <select
            value={panel.chartType}
            onChange={(event) =>
              onChange({ chartType: event.target.value as ChartType })
            }
            className="rounded border border-[var(--line-strong)] bg-transparent px-2 py-1 text-xs font-medium text-[var(--ink)]"
          >
            <option value="area">Area</option>
            <option value="line">Line</option>
            <option value="bar">Bars</option>
          </select>
        </label>
        <label className="eyebrow flex flex-col gap-1">
          Window
          <select
            value={panel.rangeDays}
            onChange={(event) =>
              onChange({ rangeDays: Number(event.target.value) as RangeDays })
            }
            className="rounded border border-[var(--line-strong)] bg-transparent px-2 py-1 text-xs font-medium text-[var(--ink)]"
          >
            <option value={7}>7 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
          </select>
        </label>
        <label className="col-span-2 flex items-center gap-2 self-end pb-1 text-[11px] font-semibold text-[var(--ink-soft)] sm:col-span-2">
          <input
            type="checkbox"
            checked={panel.showBaseline}
            onChange={(event) => onChange({ showBaseline: event.target.checked })}
          />
          Show 30-day baseline
        </label>
      </div>
    </article>
  );
}
