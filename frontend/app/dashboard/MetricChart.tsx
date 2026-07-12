"use client";

import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type SummaryPoint = {
  date: string;
  mean_7d: number | null;
  mean_30d: number | null;
  stddev_30d: number | null;
  delta_vs_baseline: number | null;
};

type Props = {
  label: string;
  /** CSS variable reference for this series' hue, e.g. "var(--series-1)". */
  color: string;
  points: SummaryPoint[];
  chartType?: "area" | "line" | "bar";
  showBaseline?: boolean;
  embedded?: boolean;
};

/** Parse a calendar date without allowing the browser timezone to shift it. */
function dateTimestamp(iso: string): number {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  return Date.UTC(year, month - 1, day);
}

/** Short "M/D" label for the chart's UTC calendar-date timestamps. */
function shortDate(timestamp: number): string {
  const date = new Date(timestamp);
  return `${date.getUTCMonth() + 1}/${date.getUTCDate()}`;
}

/** Compact numeric formatting for axis ticks / tooltip values. */
function formatValue(value: number): string {
  if (Math.abs(value) >= 1000) {
    return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

type TooltipEntry = { value?: number | string; name?: string };
function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: string | number;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-md border border-black/10 bg-white px-2.5 py-1.5 text-xs shadow-sm dark:border-white/15 dark:bg-neutral-900">
      <div className="font-medium">
        {typeof label === "number" ? shortDate(label) : label}
      </div>
      {payload.map((entry, index) => {
        const raw = entry.value;
        const value =
          typeof raw === "number" ? formatValue(raw) : String(raw ?? "");
        return (
          <div key={`${entry.name ?? "value"}-${index}`} className="text-black/60 dark:text-white/60">
            {entry.name ?? "Value"}: <span className="font-mono">{value}</span>
          </div>
        );
      })}
    </div>
  );
}

/**
 * A single-metric area chart of the rolling 7-day mean over time.
 *
 * One series, so no legend is needed — the card title names it (per the dataviz
 * skill). Colors come from CSS custom properties on the enclosing `.viz-root`, so
 * light/dark swap in one place.
 */
export default function MetricChart({
  label,
  color,
  points,
  chartType = "area",
  showBaseline = false,
  embedded = false,
}: Props) {
  const gradientId = `grad-${label.replace(/[^a-z0-9]/gi, "")}`;
  const hasData = points.some((p) => p.mean_7d != null || p.mean_30d != null);
  const chartPoints = points.map((point) => ({
    ...point,
    timestamp: dateTimestamp(point.date),
  }));

  const chart = hasData ? (
    <div className="h-44 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartPoints} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.22} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid
            stroke="var(--viz-grid)"
            strokeDasharray="0"
            vertical={false}
          />
          <XAxis
            dataKey="timestamp"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={shortDate}
            tick={{ fontSize: 11, fill: "var(--viz-muted)" }}
            tickLine={false}
            axisLine={{ stroke: "var(--viz-axis)" }}
            minTickGap={24}
          />
          <YAxis
            tickFormatter={formatValue}
            tick={{ fontSize: 11, fill: "var(--viz-muted)" }}
            tickLine={false}
            axisLine={false}
            width={40}
          />
          <Tooltip
            content={<ChartTooltip />}
            cursor={{ stroke: "var(--viz-axis)", strokeWidth: 1 }}
          />
          {chartType === "bar" ? (
            <Bar
              dataKey="mean_7d"
              name="7-day mean"
              fill={color}
              fillOpacity={0.72}
              radius={[2, 2, 0, 0]}
              isAnimationActive={false}
            />
          ) : chartType === "line" ? (
            <Line
              type="monotone"
              dataKey="mean_7d"
              name="7-day mean"
              stroke={color}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 0 }}
              connectNulls
              isAnimationActive={false}
            />
          ) : (
            <Area
              type="monotone"
              dataKey="mean_7d"
              name="7-day mean"
              stroke={color}
              strokeWidth={2}
              fill={`url(#${gradientId})`}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 0 }}
              connectNulls
              isAnimationActive={false}
            />
          )}
          {showBaseline && (
            <Line
              type="monotone"
              dataKey="mean_30d"
              name="30-day baseline"
              stroke="var(--viz-muted)"
              strokeDasharray="4 4"
              strokeWidth={1.5}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  ) : (
    <div className="flex h-44 items-center justify-center text-sm text-black/40 dark:text-white/40">
      No data yet
    </div>
  );

  if (embedded) return chart;

  return (
    <div className="rounded-xl border border-black/10 bg-[var(--viz-surface)] p-4 dark:border-white/15">
      <h3 className="mb-3 text-sm font-medium">{label}</h3>
      {chart}
    </div>
  );
}
