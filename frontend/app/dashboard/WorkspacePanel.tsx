"use client";

import { motion } from "framer-motion";
import MetricChart, { type SummaryPoint } from "./MetricChart";
import type {
  ChartType,
  PanelSize,
  RangeDays,
  WorkspacePanel as Panel,
} from "./workspace";

type Props = {
  panel: Panel;
  points: SummaryPoint[] | null;
  selected: boolean;
  editing: boolean;
  onSelect: () => void;
  onOpenDetail: () => void;
  onChange: (patch: Partial<Panel>) => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onDragStart: () => void;
  onDrop: () => void;
};

export default function WorkspacePanel({
  panel,
  points,
  selected,
  editing,
  onSelect,
  onOpenDetail,
  onChange,
  onRemove,
  onMoveUp,
  onMoveDown,
  onDragStart,
  onDrop,
}: Props) {
  const size = panel.size ?? "medium";

  function cycleSize() {
    const next: PanelSize =
      size === "small" ? "medium" : size === "medium" ? "large" : "small";
    onChange({ size: next });
  }

  function handleMouseMove(e: React.MouseEvent<HTMLElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 100;
    const y = ((e.clientY - rect.top) / rect.height) * 100;
    e.currentTarget.style.setProperty("--mouse-x", `${x}%`);
    e.currentTarget.style.setProperty("--mouse-y", `${y}%`);
  }

  return (
    <motion.article
      layout={editing ? false : true}
      layoutId={panel.id}
      draggable={editing}
      onDragStart={(event) => {
        if (!editing) return;
        (event as unknown as React.DragEvent).dataTransfer.effectAllowed =
          "move";
        onDragStart();
      }}
      onDragOver={(event) => editing && event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        if (editing) onDrop();
      }}
      initial={{ opacity: 0, y: 20, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{
        duration: 0.4,
        ease: [0.16, 1, 0.3, 1] as const,
        layout: { duration: 0.4, ease: [0.16, 1, 0.3, 1] },
      }}
      whileHover={
        editing
          ? undefined
          : {
              y: -4,
              transition: { duration: 0.3, ease: [0.16, 1, 0.3, 1] as const },
            }
      }
      className={`widget-module relative overflow-hidden p-4 widget-size-${size} ${
        size === "large" ? "widget-large" : ""
      } ${selected ? "widget-module-selected" : ""}`}
      onMouseMove={handleMouseMove}
      style={{ "--metric-color": panel.color } as React.CSSProperties}
    >
      {/* Remove button — small × in the top-right corner */}
      <button
        type="button"
        title="Remove panel"
        aria-label={`Remove ${panel.title} panel`}
        onClick={(event) => {
          event.stopPropagation();
          onRemove();
        }}
        className="absolute right-2 top-2 z-10 flex h-5 w-5 items-center justify-center text-[10px] font-bold text-[var(--text-muted)] transition-colors hover:text-[var(--signal-danger)]"
      >
        ×
      </button>

      {/* Header */}
      <div className="mb-3 flex items-start justify-between gap-3 pr-6">
        <div className="flex min-w-0 items-start gap-2.5">
          {/* Signal mark: small square, not rounded, metric color */}
          <span
            className="mt-0.5 inline-block h-2 w-2 flex-shrink-0"
            style={{ background: panel.color }}
          />
          <div className="min-w-0">
            <div className="cmd-label">
              {panel.rangeDays} day signal · Fitbit
            </div>
            <button
              type="button"
              onClick={onSelect}
              aria-pressed={selected}
              aria-label={`Select ${panel.title} panel`}
              className="mt-1 block max-w-full truncate text-left text-base font-semibold tracking-tight"
              style={{
                fontFamily:
                  "'JetBrains Mono', 'SF Mono', 'Fira Code', monospace",
              }}
            >
              {panel.title}
            </button>
            <p
              className="mt-0.5 text-[11px] font-medium uppercase tracking-[0.08em] text-[var(--text-secondary)]"
              style={{
                fontFamily:
                  "'JetBrains Mono', 'SF Mono', 'Fira Code', monospace",
              }}
            >
              {panel.metric.replaceAll("_", " ")}
            </p>
          </div>
        </div>
        {editing && (
          <span
            className="cursor-grab text-[var(--text-muted)] active:cursor-grabbing"
            title="Drag to reorder"
            aria-label="Drag to reorder"
          >
            ⠿
          </span>
        )}
      </div>

      {/* Chart area — subtle border, no rounded corners inside */}
      {points ? (
        <div className="border border-[var(--border-subtle)]">
          <MetricChart
            label={panel.title}
            color={panel.color}
            points={points}
            chartType={panel.chartType}
            showBaseline={panel.showBaseline}
            embedded
          />
        </div>
      ) : (
        <div className="flex h-44 items-center justify-center border border-dashed border-[var(--border-subtle)] text-sm text-[var(--text-secondary)]">
          Loading {panel.title}…
        </div>
      )}

      {/* Footer */}
      <div
        className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-[var(--border-subtle)] pt-3"
        onClick={(event) => event.stopPropagation()}
      >
        <motion.button
          type="button"
          onClick={onOpenDetail}
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
          className="cmd-btn cmd-btn-primary"
        >
          Open detail <span aria-hidden="true">↗</span>
        </motion.button>
        <div className="flex items-center gap-2 text-[11px] font-semibold text-[var(--text-secondary)]">
          <span
            className={`status-pip ${
              panel.showBaseline ? "status-pip-active" : "status-pip-good"
            }`}
          />
          <span>{panel.showBaseline ? "Baseline on" : "Raw trend"}</span>
          {editing && (
            <>
              <button
                type="button"
                className="flex h-6 w-6 items-center justify-center rounded text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)]"
                onClick={onMoveUp}
                title="Move up"
                aria-label="Move panel up"
              >
                ↑
              </button>
              <button
                type="button"
                className="flex h-6 w-6 items-center justify-center rounded text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)]"
                onClick={onMoveDown}
                title="Move down"
                aria-label="Move panel down"
              >
                ↓
              </button>
            </>
          )}
        </div>
      </div>

      {/* Editing controls — compact grid with .cmd-input styled selects */}
      {editing && (
        <div
          className="mt-3 grid grid-cols-2 gap-2"
          onClick={(event) => event.stopPropagation()}
        >
          <label className="cmd-label flex flex-col gap-1">
            Chart
            <select
              value={panel.chartType}
              onChange={(event) =>
                onChange({ chartType: event.target.value as ChartType })
              }
              className="cmd-input"
            >
              <option value="area">Area</option>
              <option value="line">Line</option>
              <option value="bar">Bars</option>
            </select>
          </label>
          <label className="cmd-label flex flex-col gap-1">
            Size
            <select
              value={size}
              onChange={(event) =>
                onChange({ size: event.target.value as PanelSize })
              }
              className="cmd-input"
            >
              <option value="small">Small</option>
              <option value="medium">Medium</option>
              <option value="large">Large</option>
            </select>
          </label>
          <label className="cmd-label flex flex-col gap-1">
            Window
            <select
              value={panel.rangeDays}
              onChange={(event) =>
                onChange({
                  rangeDays: Number(event.target.value) as RangeDays,
                })
              }
              className="cmd-input"
            >
              <option value={7}>7 days</option>
              <option value={30}>30 days</option>
              <option value={90}>90 days</option>
            </select>
          </label>
          <label className="flex items-center gap-2 self-end pb-1 text-[11px] font-semibold text-[var(--text-secondary)]">
            <input
              type="checkbox"
              checked={panel.showBaseline}
              onChange={(event) =>
                onChange({ showBaseline: event.target.checked })
              }
              className="h-3.5 w-3.5 accent-[var(--accent-cyan)]"
            />
            Baseline
          </label>
        </div>
      )}
      {/* Resize handle — cycles size when clicked (edit mode only) */}
      {editing && (
        <button
          type="button"
          className="widget-resize-handle"
          title="Resize widget"
          aria-label="Resize widget"
          onClick={(event) => {
            event.stopPropagation();
            cycleSize();
          }}
        >
          ⤡
        </button>
      )}
    </motion.article>
  );
}
