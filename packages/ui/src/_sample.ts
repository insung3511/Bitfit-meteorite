import type { Anomaly, PanelConfig, SummaryPoint } from "./types";

/** Deterministic sample series for previews (a gentle wave with a bump). */
export const samplePoints: SummaryPoint[] = Array.from({ length: 30 }, (_, i) => {
  const base = 62 + Math.sin(i / 4) * 6 + (i > 20 ? (i - 20) * 0.8 : 0);
  const day = String((i % 28) + 1).padStart(2, "0");
  return {
    date: `2026-06-${day}`,
    mean_7d: Math.round(base * 10) / 10,
    mean_30d: Math.round((base - 2) * 10) / 10,
    stddev_30d: 3.2,
    delta_vs_baseline: Math.round((base - 60) * 10) / 10,
  };
});

export const samplePanel: PanelConfig = {
  id: "panel-resting-hr",
  title: "Resting heart rate",
  metric: "resting_heart_rate",
  color: "var(--series-1)",
  chartType: "area",
  rangeDays: 30,
  showBaseline: false,
};

export const sampleAnomalies: Anomaly[] = [
  { date: "2026-06-24", metricName: "Resting heart rate", delta: 6.2, sigma: 2.1 },
  { date: "2026-06-19", metricName: "Sleep duration", delta: -1.4, sigma: 1.8 },
  { date: "2026-06-11", metricName: "Steps", delta: 3400, sigma: 1.6 },
];
