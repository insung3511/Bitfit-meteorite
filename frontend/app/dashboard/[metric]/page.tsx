"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { motion } from "framer-motion";
import MetricChart, { type SummaryPoint } from "../MetricChart";
import AnimatedCounter from "../../components/AnimatedCounter";
import { metricDefinition } from "../workspace";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type RawRecord = {
  record_id: string | number;
  timestamp: string;
  end_timestamp?: string | null;
  metric: string;
  signal_type: string;
  value: number | string | Record<string, unknown> | null;
  unit?: string | null;
  source: string;
  source_kind: string;
  source_file: string;
};

type RawResponse = {
  metric: string | null;
  count: number;
  truncated: boolean;
  source_metadata: {
    sources: string[];
    source_kinds: string[];
    source_files: string[];
  };
  records: RawRecord[];
};

type SummaryResponse = { points: SummaryPoint[] };

async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
  });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json() as Promise<T>;
}

function rawValue(value: RawRecord["value"]): string {
  return value && typeof value === "object"
    ? JSON.stringify(value)
    : String(value ?? "—");
}

const sectionVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1] as const },
  },
};

const tableRowVariants = {
  hidden: { opacity: 0, x: -8 },
  visible: (i: number) => ({
    opacity: 1,
    x: 0,
    transition: { delay: i * 0.03, duration: 0.3, ease: [0.16, 1, 0.3, 1] as const },
  }),
};

export default function MetricDetailPage() {
  const params = useParams<{ metric: string }>();
  const router = useRouter();
  const metric = params.metric;
  const definition = metricDefinition(metric);
  const [days, setDays] = useState<7 | 30 | 90>(30);
  const [summary, setSummary] = useState<SummaryPoint[]>([]);
  const [raw, setRaw] = useState<RawResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metric) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) {
        setLoading(true);
        setError(null);
      }
    });
    Promise.all([
      getJSON<SummaryResponse>(
        `/dashboard/summary?metric=${encodeURIComponent(metric)}&days=${days}`,
      ),
      getJSON<RawResponse>(
        `/dashboard/raw?metric=${encodeURIComponent(metric)}&limit=200`,
      ),
    ])
      .then(([summaryResponse, rawResponse]) => {
        if (cancelled) return;
        setError(null);
        setSummary(summaryResponse.points);
        setRaw(rawResponse);
        setLoading(false);
      })
      .catch((reason) => {
        if (cancelled) return;
        setError(String(reason));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days, metric]);

  const latest = useMemo(
    () =>
      [...summary].reverse().find((point) => point.mean_7d != null)?.mean_7d,
    [summary],
  );
  const baseline = useMemo(
    () =>
      [...summary]
        .reverse()
        .find((point) => point.mean_30d != null)?.mean_30d,
    [summary],
  );
  const delta =
    latest != null && baseline ? ((latest - baseline) / baseline) * 100 : null;

  return (
    <div className="board-shell min-h-screen px-4 pb-32 pt-8 sm:px-8 lg:px-12">
      <div className="mx-auto max-w-[1320px]">
        {/* Back button */}
        <motion.button
          type="button"
          initial={{ opacity: 0, x: -12 }}
          animate={{ opacity: 1, x: 0 }}
          whileHover={{ x: -4 }}
          transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] as const }}
          onClick={() => router.push("/dashboard")}
          className="glass-chip mb-8"
        >
          ← Back to canvas
        </motion.button>

        {/* Header */}
        <motion.div
          initial="hidden"
          animate="visible"
          variants={{
            hidden: { opacity: 0 },
            visible: {
              opacity: 1,
              transition: { staggerChildren: 0.1 },
            },
          }}
          className="flex flex-wrap items-end justify-between gap-6"
        >
          <motion.div variants={sectionVariants}>
            <div className="eyebrow flex items-center gap-2">
              <span className="status-dot status-dot-good" /> Fitbit signal
              detail · raw + derived
            </div>
            <h1
              className="mt-3 text-5xl font-bold tracking-[-0.04em] sm:text-7xl"
              style={{ color: definition.color }}
            >
              {definition.label}
            </h1>
            <p className="mt-4 max-w-xl text-sm leading-relaxed text-[var(--ink-soft)]">
              One signal from the summary layer down to the original Fitbit
              record. The chart is derived; the table below is the source
              trail.
            </p>
          </motion.div>

          <motion.label
            variants={sectionVariants}
            className="glass-card flex flex-col gap-2 p-4"
          >
            <span className="eyebrow">Chart window</span>
            <select
              value={days}
              onChange={(event) =>
                setDays(Number(event.target.value) as 7 | 30 | 90)
              }
              className="glass-select"
            >
              <option value={7}>7 days</option>
              <option value={30}>30 days</option>
              <option value={90}>90 days</option>
            </select>
          </motion.label>
        </motion.div>

        {/* Error */}
        {error && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            role="alert"
            className="glass-card mt-7 border-l-4 border-[var(--signal-danger)] p-4 text-sm"
          >
            Could not load this Fitbit signal: {error}
          </motion.div>
        )}

        {/* Loading */}
        {loading && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="glass-card mt-7 p-8 text-sm text-[var(--ink-soft)]"
          >
            <div className="flex items-center gap-3">
              <div className="skeleton-shimmer h-4 w-4 rounded-full" />
              Loading signal detail…
            </div>
          </motion.div>
        )}

        {/* Content */}
        {!loading && !error && (
          <>
            {/* Stat cards */}
            <motion.div
              initial="hidden"
              animate="visible"
              variants={{
                hidden: { opacity: 0 },
                visible: {
                  opacity: 1,
                  transition: { staggerChildren: 0.1, delayChildren: 0.1 },
                },
              }}
              className="mt-7 grid gap-3 sm:grid-cols-3"
            >
              <motion.div
                variants={sectionVariants}
                className="glass-card p-5"
              >
                <div className="eyebrow">Latest 7-day mean</div>
                <div className="mt-3 text-4xl font-bold tracking-[-0.04em]">
                  {latest == null ? (
                    "—"
                  ) : (
                    <AnimatedCounter
                      value={latest}
                      decimals={1}
                      suffix={` ${definition.unit}`}
                    />
                  )}
                </div>
              </motion.div>

              <motion.div
                variants={sectionVariants}
                className="glass-card p-5"
              >
                <div className="eyebrow">30-day baseline</div>
                <div className="mt-3 text-4xl font-bold tracking-[-0.04em]">
                  {baseline == null ? (
                    "—"
                  ) : (
                    <AnimatedCounter
                      value={baseline}
                      decimals={1}
                      suffix={` ${definition.unit}`}
                    />
                  )}
                </div>
              </motion.div>

              <motion.div
                variants={sectionVariants}
                className="glass-card p-5"
              >
                <div className="eyebrow">Delta vs baseline</div>
                <div
                  className={`mt-3 text-4xl font-bold tracking-[-0.04em] ${
                    delta != null && delta < 0
                      ? "text-[var(--signal-danger)]"
                      : "text-[var(--signal-good)]"
                  }`}
                >
                  {delta == null ? (
                    "—"
                  ) : (
                    <AnimatedCounter
                      value={delta}
                      decimals={1}
                      prefix={`${delta > 0 ? "+" : ""}`}
                      suffix="%"
                    />
                  )}
                </div>
              </motion.div>
            </motion.div>

            {/* Chart */}
            <motion.section
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                delay: 0.3,
                duration: 0.5,
                ease: [0.16, 1, 0.3, 1] as const,
              }}
              className="glass-card mt-6 p-5 sm:p-7"
            >
              <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="eyebrow">Derived trend</div>
                  <h2 className="mt-1 text-xl font-bold">Rolling view</h2>
                </div>
                <span className="glass-chip glass-chip-active">
                  Fitbit / {days} days
                </span>
              </div>
              <MetricChart
                label={definition.label}
                color={definition.color}
                points={summary}
                chartType="area"
                showBaseline
              />
            </motion.section>

            {/* Raw data table */}
            <motion.section
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                delay: 0.4,
                duration: 0.5,
                ease: [0.16, 1, 0.3, 1] as const,
              }}
              className="glass-card mt-6 overflow-hidden p-5 sm:p-7"
            >
              <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="eyebrow">Raw data explorer</div>
                  <h2 className="mt-1 text-xl font-bold">
                    Every source record
                  </h2>
                  <p className="mt-1 text-xs text-[var(--ink-soft)]">
                    {raw?.count ?? 0} rows ·{" "}
                    {raw?.source_metadata.sources.join(", ") || "Fitbit"}
                    {raw?.truncated ? " · sample truncated" : ""}
                  </p>
                </div>
                <span className="glass-chip">Read only</span>
              </div>

              <div className="glass-table-wrap">
                <table className="glass-table">
                  <thead>
                    <tr>
                      <th>Timestamp</th>
                      <th>Metric</th>
                      <th>Signal type</th>
                      <th>Value</th>
                      <th>Unit</th>
                      <th>Source file</th>
                    </tr>
                  </thead>
                  <tbody>
                    {raw?.records.map((record, i) => (
                      <motion.tr
                        key={record.record_id}
                        custom={i}
                        initial="hidden"
                        animate="visible"
                        variants={tableRowVariants}
                      >
                        <td>{new Date(record.timestamp).toLocaleString()}</td>
                        <td>{record.metric}</td>
                        <td>{record.signal_type}</td>
                        <td className="font-mono text-[var(--ink)]">
                          {rawValue(record.value)}
                        </td>
                        <td>{record.unit || "—"}</td>
                        <td title={record.source_file}>
                          {record.source_file}
                        </td>
                      </motion.tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {raw?.records.length === 0 && (
                <p className="py-8 text-center text-sm text-[var(--ink-soft)]">
                  No raw records found for this signal.
                </p>
              )}
            </motion.section>
          </>
        )}
      </div>
    </div>
  );
}
