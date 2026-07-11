"use client";

import { useEffect, useState } from "react";
import MetricChart, { type SummaryPoint } from "./MetricChart";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// Preferred default metrics to chart, in display order, each mapped to a fixed
// categorical slot (per the dataviz skill: hues are assigned in fixed order and
// never reassigned/cycled based on what's present).
const DEFAULT_METRICS: { metric: string; label: string; color: string }[] = [
  { metric: "steps", label: "Steps", color: "var(--series-1)" },
  { metric: "resting_heart_rate", label: "Resting Heart Rate", color: "var(--series-2)" },
  { metric: "sleep_deep_minutes", label: "Deep Sleep", color: "var(--series-3)" },
  { metric: "sleep_rem_minutes", label: "REM Sleep", color: "var(--series-4)" },
  { metric: "hrv", label: "HRV", color: "var(--series-5)" },
  { metric: "spo2", label: "SpO2", color: "var(--series-6)" },
];

type Anomaly = {
  date: string;
  metric_name: string;
  delta_vs_baseline: number | null;
  sigma: number | null;
};

type AnomaliesResponse = { count: number; anomalies: Anomaly[] };
type MetricsResponse = { metrics: string[] };
type SummaryResponse = { metric: string; points: SummaryPoint[] };

type FetchState<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T };

async function getJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
    ...init,
  });
  if (!res.ok) {
    throw new Error(`${path} returned ${res.status}`);
  }
  return res.json() as Promise<T>;
}

function formatDelta(a: Anomaly): string {
  if (a.delta_vs_baseline == null) return "";
  const sign = a.delta_vs_baseline > 0 ? "+" : "";
  const deltaText = `${sign}${a.delta_vs_baseline.toFixed(1)}`;
  const sigmaText = a.sigma != null ? ` (${a.sigma.toFixed(1)}σ)` : "";
  return `${deltaText} vs. baseline${sigmaText}`;
}

function metricDisplayName(metric: string): string {
  const known = DEFAULT_METRICS.find((m) => m.metric === metric);
  if (known) return known.label;
  return metric
    .split("_")
    .map((w) => w[0]?.toUpperCase() + w.slice(1))
    .join(" ");
}

export default function DashboardPage() {
  const [availableMetrics, setAvailableMetrics] = useState<Set<string>>(
    new Set(),
  );
  const [metricsState, setMetricsState] = useState<FetchState<null>>({
    status: "loading",
  });
  const [charts, setCharts] = useState<
    Record<string, FetchState<SummaryPoint[]>>
  >({});
  const [anomalies, setAnomalies] = useState<FetchState<Anomaly[]>>({
    status: "loading",
  });
  const [coaching, setCoaching] = useState<
    | { status: "idle" }
    | { status: "loading" }
    | { status: "ready"; text: string }
    | { status: "error"; message: string }
  >({ status: "idle" });

  useEffect(() => {
    let cancelled = false;

    getJSON<MetricsResponse>("/dashboard/metrics")
      .then((res) => {
        if (cancelled) return;
        setAvailableMetrics(new Set(res.metrics));
        setMetricsState({ status: "ready", data: null });
      })
      .catch((err) => {
        if (cancelled) return;
        setMetricsState({ status: "error", message: String(err) });
      });

    getJSON<AnomaliesResponse>("/dashboard/anomalies?days=30")
      .then((res) => {
        if (!cancelled) setAnomalies({ status: "ready", data: res.anomalies });
      })
      .catch((err) => {
        if (!cancelled) setAnomalies({ status: "error", message: String(err) });
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (metricsState.status !== "ready") return;
    let cancelled = false;

    for (const { metric } of DEFAULT_METRICS) {
      if (!availableMetrics.has(metric)) continue;
      setCharts((prev) => ({ ...prev, [metric]: { status: "loading" } }));
      getJSON<SummaryResponse>(`/dashboard/summary?metric=${metric}&days=30`)
        .then((res) => {
          if (cancelled) return;
          setCharts((prev) => ({
            ...prev,
            [metric]: { status: "ready", data: res.points },
          }));
        })
        .catch((err) => {
          if (cancelled) return;
          setCharts((prev) => ({
            ...prev,
            [metric]: { status: "error", message: String(err) },
          }));
        });
    }

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metricsState.status, availableMetrics]);

  async function runSleepCoaching() {
    setCoaching({ status: "loading" });
    try {
      const res = await fetch(`${API_BASE_URL}/dashboard/sleep-coaching`, {
        method: "POST",
        credentials: "include",
      });
      const body = (await res.json()) as {
        summary: string | null;
        error?: string;
      };
      if (!res.ok || !body.summary) {
        setCoaching({
          status: "error",
          message:
            body.error ??
            "Sleep coaching is unavailable — check that ANTHROPIC_API_KEY is configured.",
        });
        return;
      }
      setCoaching({ status: "ready", text: body.summary });
    } catch {
      setCoaching({
        status: "error",
        message: `Could not reach the backend at ${API_BASE_URL}.`,
      });
    }
  }

  const chartableMetrics = DEFAULT_METRICS.filter((m) =>
    availableMetrics.has(m.metric),
  );
  const noDataYet =
    metricsState.status === "ready" && availableMetrics.size === 0;

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <p className="mt-1 text-sm text-black/60 dark:text-white/60">
          Trends, anomaly flags, and sleep coaching over your synced health data.
        </p>
      </div>

      {metricsState.status === "error" && (
        <div
          role="alert"
          className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-2 text-sm text-red-700 dark:text-red-300"
        >
          Could not reach the backend at {API_BASE_URL}.
        </div>
      )}

      {noDataYet && (
        <div className="rounded-xl border border-black/10 bg-[var(--viz-surface)] px-4 py-6 text-center text-sm text-black/60 dark:border-white/15 dark:text-white/60">
          No data synced yet. Connect your Google Health account and run a sync,
          or import a Google Takeout export, to see trends here.
        </div>
      )}

      {chartableMetrics.length > 0 && (
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {chartableMetrics.map(({ metric, label, color }) => {
            const state = charts[metric];
            if (!state || state.status === "loading") {
              return (
                <div
                  key={metric}
                  className="flex h-52 items-center justify-center rounded-xl border border-black/10 bg-[var(--viz-surface)] text-sm text-black/40 dark:border-white/15 dark:text-white/40"
                >
                  Loading {label}…
                </div>
              );
            }
            if (state.status === "error") {
              return (
                <div
                  key={metric}
                  className="flex h-52 items-center justify-center rounded-xl border border-red-500/30 bg-red-500/5 text-sm text-red-700 dark:text-red-300"
                >
                  Could not load {label}.
                </div>
              );
            }
            return (
              <MetricChart
                key={metric}
                label={label}
                color={color}
                points={state.data}
              />
            );
          })}
        </section>
      )}

      <section className="rounded-xl border border-black/10 p-4 dark:border-white/15">
        <h2 className="mb-3 text-sm font-medium">Anomalies (last 30 days)</h2>
        {anomalies.status === "loading" && (
          <p className="text-sm text-black/40 dark:text-white/40">Loading…</p>
        )}
        {anomalies.status === "error" && (
          <p className="text-sm text-red-700 dark:text-red-300">
            Could not load anomalies.
          </p>
        )}
        {anomalies.status === "ready" && anomalies.data.length === 0 && (
          <p className="text-sm text-black/40 dark:text-white/40">
            Nothing flagged — every metric is within its normal range.
          </p>
        )}
        {anomalies.status === "ready" && anomalies.data.length > 0 && (
          <ul className="divide-y divide-black/10 dark:divide-white/15">
            {anomalies.data.map((a, i) => (
              <li
                key={`${a.date}-${a.metric_name}-${i}`}
                className="flex items-center justify-between gap-4 py-2 text-sm"
              >
                <div>
                  <span className="font-medium">
                    {metricDisplayName(a.metric_name)}
                  </span>
                  <span className="ml-2 text-black/40 dark:text-white/40">
                    {a.date}
                  </span>
                </div>
                <span
                  className="font-mono"
                  style={{ color: "var(--series-3)" }}
                >
                  {formatDelta(a)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-xl border border-black/10 p-4 dark:border-white/15">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-sm font-medium">Sleep Coaching</h2>
          <button
            type="button"
            onClick={runSleepCoaching}
            disabled={coaching.status === "loading"}
            className="rounded-lg bg-black px-4 py-1.5 text-sm font-medium text-white disabled:opacity-40 dark:bg-white dark:text-black"
          >
            {coaching.status === "loading" ? "Analyzing…" : "Get sleep coaching"}
          </button>
        </div>

        {coaching.status === "idle" && (
          <p className="mt-3 text-sm text-black/40 dark:text-white/40">
            Generate a focused summary of your recent sleep, correlated with
            heart rate and activity.
          </p>
        )}
        {coaching.status === "loading" && (
          <p className="mt-3 text-sm text-black/40 dark:text-white/40">
            Reviewing your last 30 days of sleep, heart rate, and activity…
          </p>
        )}
        {coaching.status === "error" && (
          <p className="mt-3 text-sm text-red-700 dark:text-red-300">
            {coaching.message}
          </p>
        )}
        {coaching.status === "ready" && (
          <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed">
            {coaching.text}
          </p>
        )}
        <p className="mt-3 text-xs text-black/40 dark:text-white/40">
          General wellness information, not medical advice.
        </p>
      </section>
    </div>
  );
}
