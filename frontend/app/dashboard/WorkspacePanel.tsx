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
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] as const }}
      whileHover={
        editing
          ? undefined
          : { y: -4, transition: { duration: 0.3, ease: [0.16, 1, 0.3, 1] as const } }
      }
      className={`glass-card spotlight-card widget-card widget-size-${size} group relative overflow-hidden p-4 ${
        selected ? "widget-card-selected" : ""
      }`}
      onClick={onSelect}
      onMouseMove={handleMouseMove}
    >
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span
            className="signal-mark"
            style={{
              background: `color-mix(in srgb, ${panel.color} 18%, transparent)`,
              color: panel.color,
            }}
          >
            {panel.title.slice(0, 1)}
          </span>
          <div className="min-w-0">
            <div className="eyebrow">
              {panel.rangeDays} day signal · Fitbit
            </div>
            <h3 className="mt-1 truncate text-base font-semibold tracking-tight">
              {panel.title}
            </h3>
            <p className="mt-0.5 text-[11px] font-medium uppercase tracking-[0.08em] text-[var(--ink-soft)]">
              {panel.metric.replaceAll("_", " ")}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {editing && (
            <span
              className="drag-handle"
              title="Drag to reorder"
              aria-label="Drag to reorder"
            >
              ⠿
            </span>
          )}
          <button
            type="button"
            title="Remove panel"
            aria-label={`Remove ${panel.title} panel`}
            onClick={(event) => {
              event.stopPropagation();
              onRemove();
            }}
            className="icon-button text-[var(--ink-soft)]"
          >
            ×
          </button>
        </div>
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
        <div className="flex h-44 items-center justify-center rounded-xl border border-dashed border-[var(--line)] text-sm text-[var(--ink-soft)]">
          Loading {panel.title}…
        </div>
      )}

      <div
        className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-[var(--line)] pt-3"
        onClick={(event) => event.stopPropagation()}
      >
        <motion.button
          type="button"
          onClick={onOpenDetail}
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          className="glass-chip glass-chip-active"
        >
          Open detail <span aria-hidden="true">↗</span>
        </motion.button>
        <div className="flex items-center gap-1 text-[11px] font-semibold text-[var(--ink-soft)]">
          <span>{panel.showBaseline ? "Baseline on" : "Raw trend"}</span>
          {editing && (
            <>
              <button
                type="button"
                className="icon-button"
                onClick={onMoveUp}
                title="Move up"
                aria-label="Move panel up"
              >
                ↑
              </button>
              <button
                type="button"
                className="icon-button"
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

      {editing && (
        <div
          className="mt-3 grid grid-cols-2 gap-2 rounded-xl bg-[var(--glass-subtle)] p-2"
          onClick={(event) => event.stopPropagation()}
        >
          <label className="eyebrow flex flex-col gap-1">
            Chart
            <select
              value={panel.chartType}
              onChange={(event) =>
                onChange({ chartType: event.target.value as ChartType })
              }
              className="glass-select"
            >
              <option value="area">Area</option>
              <option value="line">Line</option>
              <option value="bar">Bars</option>
            </select>
          </label>
          <label className="eyebrow flex flex-col gap-1">
            Size
            <select
              value={size}
              onChange={(event) =>
                onChange({ size: event.target.value as PanelSize })
              }
              className="glass-select"
            >
              <option value="small">Small</option>
              <option value="medium">Medium</option>
              <option value="large">Large</option>
            </select>
          </label>
          <label className="eyebrow flex flex-col gap-1">
            Window
            <select
              value={panel.rangeDays}
              onChange={(event) =>
                onChange({
                  rangeDays: Number(event.target.value) as RangeDays,
                })
              }
              className="glass-select"
            >
              <option value={7}>7 days</option>
              <option value={30}>30 days</option>
              <option value={90}>90 days</option>
            </select>
          </label>
          <label className="flex items-center gap-2 self-end pb-1 text-[11px] font-semibold text-[var(--ink-soft)]">
            <input
              type="checkbox"
              checked={panel.showBaseline}
              onChange={(event) =>
                onChange({ showBaseline: event.target.checked })
              }
            />
            Baseline
          </label>
        </div>
      )}
    </motion.article>
  );
}
