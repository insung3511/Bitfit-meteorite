import type { Anomaly } from "./types";

export type AnomalyListProps = {
  anomalies: Anomaly[];
  /** Map a metric name to a display label. Defaults to identity. */
  formatName?: (metricName: string) => string;
  /** Accent color for the delta value. Defaults to --series-3. */
  deltaColor?: string;
  emptyText?: string;
};

/** Format a signed delta with optional sigma, e.g. "+2.3 vs. baseline (1.8σ)". */
function formatDelta(a: Anomaly): string {
  if (a.delta == null) return "";
  const sign = a.delta > 0 ? "+" : "";
  const deltaText = `${sign}${a.delta.toFixed(1)}`;
  const sigmaText = a.sigma != null ? ` (${a.sigma.toFixed(1)}σ)` : "";
  return `${deltaText} vs. baseline${sigmaText}`;
}

/** Divided list of flagged metric anomalies with series-colored deltas. */
export function AnomalyList({
  anomalies,
  formatName = (n) => n,
  deltaColor = "var(--series-3)",
  emptyText = "Nothing flagged — every metric is within its normal range.",
}: AnomalyListProps) {
  if (anomalies.length === 0) {
    return <p className="text-sm text-black/40 dark:text-white/40">{emptyText}</p>;
  }
  return (
    <ul className="divide-y divide-black/10 dark:divide-white/15">
      {anomalies.map((a, i) => (
        <li
          key={`${a.date}-${a.metricName}-${i}`}
          className="flex items-center justify-between gap-4 py-2 text-sm"
        >
          <div>
            <span className="font-medium">{formatName(a.metricName)}</span>
            <span className="ml-2 text-black/40 dark:text-white/40">{a.date}</span>
          </div>
          <span className="font-mono" style={{ color: deltaColor }}>
            {formatDelta(a)}
          </span>
        </li>
      ))}
    </ul>
  );
}
