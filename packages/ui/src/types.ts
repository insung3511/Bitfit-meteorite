/** Chart render style for a metric panel. */
export type ChartType = "area" | "line" | "bar";

/** Rolling-window length in days. */
export type RangeDays = 7 | 30 | 90;

/** One time-series point of rolling health-metric statistics. */
export type SummaryPoint = {
  date: string;
  mean_7d: number | null;
  mean_30d: number | null;
  stddev_30d: number | null;
  delta_vs_baseline: number | null;
};

/** Configuration for a single workspace chart panel (app-decoupled). */
export type PanelConfig = {
  id: string;
  title: string;
  metric: string;
  /** CSS variable reference for this series' hue, e.g. "var(--series-1)". */
  color: string;
  chartType: ChartType;
  rangeDays: RangeDays;
  showBaseline: boolean;
};

/** A flagged deviation of a metric from its baseline. */
export type Anomaly = {
  date: string;
  metricName: string;
  delta: number | null;
  sigma: number | null;
};
