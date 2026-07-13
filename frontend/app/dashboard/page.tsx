"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import WorkspacePanel from "./WorkspacePanel";
import { type SummaryPoint } from "./MetricChart";
import AnimatedCounter from "../components/AnimatedCounter";
import {
  commitWorkspaceVersion,
  createDefaultWorkspace,
  createPanel,
  isWorkspaceDocument,
  METRIC_CATALOG,
  metricDefinition,
  type WorkspaceDocument,
  type WorkspacePanel as Panel,
} from "./workspace";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const WORKSPACE_STORAGE_KEY = "bitfit-analytical-workspace-v1";
const AGENT_PROPOSAL_KEY = "bitfit-agent-workspace-proposal-v1";

type Anomaly = {
  date: string;
  metric_name: string;
  delta_vs_baseline: number | null;
  sigma: number | null;
};
type MetricsResponse = { metrics: string[] };
type SummaryResponse = { metric: string; points: SummaryPoint[] };
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
type FetchState<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T };
type AgentAction = {
  action_id: string;
  action_type: string;
  panel_id?: string | null;
  payload?: Record<string, unknown>;
};

type ConnectionStatus = {
  connected: boolean;
  provider: string;
  token_fresh?: boolean;
  expires_at?: string | null;
};

type SyncResult = {
  status: string;
  records_synced?: number;
  error?: string;
};

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
  });
  if (!res.ok) throw new Error(`${path} returned ${res.status}`);
  return res.json() as Promise<T>;
}

function formatDelta(anomaly: Anomaly): string {
  if (anomaly.delta_vs_baseline == null) return "Review signal";
  const sign = anomaly.delta_vs_baseline > 0 ? "+" : "";
  return `${sign}${anomaly.delta_vs_baseline.toFixed(1)} vs baseline`;
}

function formatRawValue(value: RawRecord["value"]): string {
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "—");
}

const sectionVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1] as const },
  },
};

const listItemVariants = {
  hidden: { opacity: 0, x: -12 },
  visible: {
    opacity: 1,
    x: 0,
    transition: { duration: 0.35, ease: [0.16, 1, 0.3, 1] as const },
  },
};

export default function DashboardPage() {
  const router = useRouter();
  const [availableMetrics, setAvailableMetrics] = useState<Set<string>>(
    new Set(),
  );
  const [metricsState, setMetricsState] = useState<FetchState<null>>({
    status: "loading",
  });
  const [workspace, setWorkspace] = useState<WorkspaceDocument>(
    createDefaultWorkspace(),
  );
  const [workspaceReady, setWorkspaceReady] = useState(false);
  const [selectedPanelId, setSelectedPanelId] = useState<string | null>(null);
  const [editingLayout, setEditingLayout] = useState(false);
  const [draggedPanelId, setDraggedPanelId] = useState<string | null>(null);
  const [charts, setCharts] = useState<
    Record<string, FetchState<SummaryPoint[]>>
  >({});
  const [anomalies, setAnomalies] = useState<FetchState<Anomaly[]>>({
    status: "loading",
  });
  const [rawData, setRawData] = useState<FetchState<RawResponse>>({
    status: "loading",
  });
  const [connection, setConnection] = useState<FetchState<ConnectionStatus>>({
    status: "loading",
  });
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    getJSON<MetricsResponse>("/dashboard/metrics")
      .then((res) => {
        if (!cancelled) {
          setAvailableMetrics(new Set(res.metrics));
          setMetricsState({ status: "ready", data: null });
        }
      })
      .catch((error) => {
        if (!cancelled)
          setMetricsState({ status: "error", message: String(error) });
      });
    getJSON<{ anomalies: Anomaly[] }>("/dashboard/anomalies?days=30")
      .then((res) => {
        if (!cancelled) setAnomalies({ status: "ready", data: res.anomalies });
      })
      .catch((error) => {
        if (!cancelled)
          setAnomalies({ status: "error", message: String(error) });
      });
    getJSON<ConnectionStatus>("/dashboard/connection")
      .then((res) => {
        if (!cancelled) setConnection({ status: "ready", data: res });
      })
      .catch((error) => {
        if (!cancelled)
          setConnection({ status: "error", message: String(error) });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const hydrate = window.setTimeout(() => {
      try {
        const saved = window.localStorage.getItem(WORKSPACE_STORAGE_KEY);
        if (saved) {
          const parsed: unknown = JSON.parse(saved);
          if (isWorkspaceDocument(parsed)) setWorkspace(parsed);
        }
      } catch {
        /* malformed local state is disposable */
      }
      setWorkspaceReady(true);
    }, 0);
    return () => window.clearTimeout(hydrate);
  }, []);

  useEffect(() => {
    if (workspaceReady)
      window.localStorage.setItem(
        WORKSPACE_STORAGE_KEY,
        JSON.stringify(workspace),
      );
  }, [workspace, workspaceReady]);

  useEffect(() => {
    if (!workspaceReady || availableMetrics.size === 0) return;
    const timer = window.setTimeout(
      () =>
        setWorkspace((current) => {
          const additions = METRIC_CATALOG.filter(
            (entry) =>
              availableMetrics.has(entry.metric) &&
              !current.active.panels.some(
                (panel) => panel.metric === entry.metric,
              ),
          ).map((entry, index) =>
            createPanel(entry.metric, current.active.panels.length + index),
          );
          return additions.length > 0
            ? commitWorkspaceVersion(
                current,
                [...current.active.panels, ...additions],
                "Added available Fitbit signals",
              )
            : current;
        }),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [availableMetrics, workspaceReady]);

  useEffect(() => {
    const onToggle = () => setEditingLayout((current) => !current);
    window.addEventListener("bitfit:toggle-layout", onToggle);
    return () => window.removeEventListener("bitfit:toggle-layout", onToggle);
  }, []);

  useEffect(() => {
    if (!workspaceReady) return;
    const timer = window.setTimeout(() => {
      try {
        const saved = window.localStorage.getItem(AGENT_PROPOSAL_KEY);
        if (!saved) return;
        const action = JSON.parse(saved) as AgentAction;
        if (
          action.action_type === "add_chart" &&
          action.payload?.chart &&
          typeof action.payload.chart === "object"
        ) {
          const metric = (action.payload.chart as Record<string, unknown>)
            .metric;
          if (
            typeof metric === "string" &&
            availableMetrics.has(metric)
          ) {
            setWorkspace((current) =>
              current.active.panels.some((panel) => panel.metric === metric)
                ? current
                : commitWorkspaceVersion(
                    current,
                    [
                      ...current.active.panels,
                      createPanel(metric, current.active.panels.length),
                    ],
                    "Added from assistant",
                  ),
            );
          }
        }
        if (action.action_type === "focus_panel" && action.panel_id)
          setSelectedPanelId(action.panel_id);
        window.localStorage.removeItem(AGENT_PROPOSAL_KEY);
      } catch {
        window.localStorage.removeItem(AGENT_PROPOSAL_KEY);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [availableMetrics, workspaceReady]);

  const chartablePanels = useMemo(
    () =>
      workspace.active.panels.filter((panel) =>
        availableMetrics.has(panel.metric),
      ),
    [availableMetrics, workspace.active.panels],
  );
  const selectedPanel =
    workspace.active.panels.find((panel) => panel.id === selectedPanelId) ??
    chartablePanels[0] ??
    null;

  useEffect(() => {
    if (metricsState.status !== "ready") return;
    let cancelled = false;
    for (const panel of chartablePanels) {
      getJSON<SummaryResponse>(
        `/dashboard/summary?metric=${encodeURIComponent(panel.metric)}&days=${panel.rangeDays}`,
      )
        .then((res) => {
          if (!cancelled)
            setCharts((current) => ({
              ...current,
              [panel.id]: { status: "ready", data: res.points },
            }));
        })
        .catch((error) => {
          if (!cancelled)
            setCharts((current) => ({
              ...current,
              [panel.id]: { status: "error", message: String(error) },
            }));
        });
    }
    return () => {
      cancelled = true;
    };
  }, [chartablePanels, metricsState.status]);

  useEffect(() => {
    if (!selectedPanel || !availableMetrics.has(selectedPanel.metric)) return;
    let cancelled = false;
    getJSON<RawResponse>(
      `/dashboard/raw?metric=${encodeURIComponent(selectedPanel.metric)}&limit=24`,
    )
      .then((data) => {
        if (!cancelled) setRawData({ status: "ready", data });
      })
      .catch((error) => {
        if (!cancelled)
          setRawData({ status: "error", message: String(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [availableMetrics, selectedPanel]);

  function commitPanels(panels: Panel[], label: string) {
    setWorkspace((current) => commitWorkspaceVersion(current, panels, label));
  }
  function updatePanel(panelId: string, patch: Partial<Panel>) {
    commitPanels(
      workspace.active.panels.map((panel) =>
        panel.id === panelId ? { ...panel, ...patch } : panel,
      ),
      "Updated layout",
    );
  }
  function removePanel(panelId: string) {
    commitPanels(
      workspace.active.panels.filter((panel) => panel.id !== panelId),
      "Removed widget",
    );
    if (selectedPanelId === panelId) setSelectedPanelId(null);
  }
  function movePanel(panelId: string, direction: -1 | 1) {
    const index = workspace.active.panels.findIndex(
      (panel) => panel.id === panelId,
    );
    const nextIndex = index + direction;
    if (
      index < 0 ||
      nextIndex < 0 ||
      nextIndex >= workspace.active.panels.length
    )
      return;
    const panels = [...workspace.active.panels];
    [panels[index], panels[nextIndex]] = [panels[nextIndex], panels[index]];
    commitPanels(panels, "Reordered widgets");
  }
  function dropPanel(targetId: string) {
    if (!draggedPanelId || draggedPanelId === targetId) return;
    const panels = [...workspace.active.panels];
    const from = panels.findIndex((panel) => panel.id === draggedPanelId);
    const to = panels.findIndex((panel) => panel.id === targetId);
    if (from < 0 || to < 0) return;
    const [moved] = panels.splice(from, 1);
    panels.splice(to, 0, moved);
    setDraggedPanelId(null);
    commitPanels(panels, "Reordered widgets");
  }
  function addPanel() {
    const next = METRIC_CATALOG.find(
      (entry) =>
        availableMetrics.has(entry.metric) &&
        !workspace.active.panels.some(
          (panel) => panel.metric === entry.metric,
        ),
    );
    if (!next) return;
    const panel = createPanel(next.metric, workspace.active.panels.length);
    commitPanels([...workspace.active.panels, panel], "Added widget");
    setSelectedPanelId(panel.id);
  }
  function undoWorkspace() {
    setWorkspace((current) => {
      const previous = current.history.at(-1);
      return previous
        ? { active: previous, history: current.history.slice(0, -1) }
        : current;
    });
  }
  function resetWorkspace() {
    commitPanels(createDefaultWorkspace().active.panels, "Restored overview");
  }

  async function connectGoogle() {
    window.location.href = `${API_BASE_URL}/auth/google/login`;
  }

  async function runSync() {
    setSyncing(true);
    setSyncResult(null);
    try {
      const res = await fetch(`${API_BASE_URL}/sync/run`, {
        method: "POST",
        credentials: "include",
      });
      const data = (await res.json()) as SyncResult;
      setSyncResult(data);
      // Refresh metrics after sync
      const metricsRes = await getJSON<MetricsResponse>("/dashboard/metrics");
      setAvailableMetrics(new Set(metricsRes.metrics));
      setMetricsState({ status: "ready", data: null });
      // Refresh connection status
      const connRes = await getJSON<ConnectionStatus>("/dashboard/connection");
      setConnection({ status: "ready", data: connRes });
    } catch (error) {
      setSyncResult({
        status: "error",
        error: String(error),
      });
    } finally {
      setSyncing(false);
    }
  }

  const boardStatus =
    metricsState.status === "loading"
      ? "Loading"
      : metricsState.status === "error"
        ? "Unavailable"
        : availableMetrics.size
          ? "Ready"
          : "Awaiting data";

  const isConnected =
    connection.status === "ready" && connection.data.connected;
  const isTokenFresh =
    connection.status === "ready" && connection.data.token_fresh;

  return (
    <div className="board-shell min-h-screen px-4 pb-32 pt-8 sm:px-8 lg:px-12">
      <div className="mx-auto max-w-[1480px]">
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
              <span className="status-dot status-dot-good" /> Fitbit health
              telemetry · personal board
            </div>
            <h1 className="mt-3 max-w-4xl text-4xl font-bold leading-[0.95] tracking-[-0.04em] sm:text-6xl">
              Your body,{" "}
              <span className="gradient-text">in signals.</span>
            </h1>
            <p className="mt-4 max-w-2xl text-sm leading-relaxed text-[var(--ink-soft)]">
              A calm, raw-data-first workspace for scanning trends, finding
              exceptions, and opening any signal all the way down to its source
              record.
            </p>
          </motion.div>

          <motion.div
            variants={sectionVariants}
            className="glass-card min-w-[210px] p-4"
          >
            <div className="flex items-center justify-between">
              <span className="eyebrow">Fitbit history</span>
              <span
                className={`status-dot ${
                  boardStatus === "Ready"
                    ? "status-dot-good"
                    : boardStatus === "Unavailable"
                      ? "status-dot-bad"
                      : "status-dot-warn"
                }`}
              />
            </div>
            <div className="mt-3 flex items-end justify-between">
              <strong className="text-3xl font-bold tracking-[-0.04em]">
                <AnimatedCounter value={availableMetrics.size} />
              </strong>
              <span className="eyebrow pb-1">signals loaded</span>
            </div>
          </motion.div>

          {/* Google OAuth + Sync card */}
          <motion.div
            variants={sectionVariants}
            className="glass-card min-w-[240px] p-4"
          >
            <div className="flex items-center justify-between">
              <span className="eyebrow">Google Health</span>
              {connection.status === "loading" ? (
                <span className="status-dot status-dot-warn" />
              ) : connection.status === "error" ? (
                <span className="status-dot status-dot-bad" />
              ) : isConnected ? (
                <span className="status-orbital status-dot status-dot-good" />
              ) : (
                <span className="status-dot status-dot-bad" />
              )}
            </div>
            <div className="mt-3 space-y-2">
              {connection.status === "loading" && (
                <p className="text-xs text-[var(--ink-soft)]">
                  Checking connection…
                </p>
              )}
              {connection.status === "error" && (
                <p className="text-xs text-[var(--signal-danger)]">
                  Could not check status
                </p>
              )}
              {connection.status === "ready" && (
                <>
                  <p className="text-xs text-[var(--ink-soft)]">
                    {isConnected
                      ? isTokenFresh
                        ? "Connected · token fresh"
                        : "Connected · token expired"
                      : "Not connected"}
                  </p>
                  <div className="flex gap-2">
                    {!isConnected && (
                      <motion.button
                        type="button"
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                        onClick={connectGoogle}
                        className="glass-chip glass-chip-active text-xs"
                      >
                        Connect Google ↗
                      </motion.button>
                    )}
                    {isConnected && (
                      <motion.button
                        type="button"
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                        onClick={runSync}
                        disabled={syncing}
                        className="glass-chip glass-chip-active text-xs disabled:opacity-40"
                      >
                        {syncing ? "Syncing…" : "Sync now ↻"}
                      </motion.button>
                    )}
                  </div>
                </>
              )}
            </div>

            {/* Sync result toast */}
            <AnimatePresence>
              {syncResult && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  className="mt-2 overflow-hidden"
                >
                  <div
                    className={`rounded-lg px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wider ${
                      syncResult.status === "error"
                        ? "bg-[var(--signal-danger)]/10 text-[var(--signal-danger)]"
                        : "bg-[var(--signal-good)]/10 text-[var(--signal-good)]"
                    }`}
                  >
                    {syncResult.status === "error"
                      ? syncResult.error || "Sync failed"
                      : `${syncResult.records_synced ?? 0} records synced`}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </motion.div>

        {/* Error / empty states */}
        <AnimatePresence>
          {metricsState.status === "error" && (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              role="alert"
              className="glass-card mt-6 border-l-4 border-[var(--signal-danger)] px-4 py-3 text-sm"
            >
              Could not reach the backend at {API_BASE_URL}.
            </motion.div>
          )}
          {metricsState.status === "ready" && availableMetrics.size === 0 && (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              className="glass-card mt-6 flex flex-wrap items-center justify-between gap-4 p-5"
            >
              <div>
                <div className="eyebrow">Awaiting first reading</div>
                <p className="mt-1 text-sm text-[var(--ink-soft)]">
                  Import your Fitbit export to populate this board.
                </p>
              </div>
              <span className="glass-chip glass-chip-warn">No data yet</span>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Widget canvas */}
        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2, duration: 0.5, ease: [0.16, 1, 0.3, 1] as const }}
          className="glass-card mt-7 p-4 sm:p-6"
        >
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="eyebrow">
                Widget canvas ·{" "}
                {workspace.active.id === "version-default"
                  ? "default"
                  : "saved locally"}
              </div>
              <h2 className="mt-1 text-xl font-bold tracking-tight">
                Fitbit signals
              </h2>
              <p className="mt-1 text-xs text-[var(--ink-soft)]">
                Click a widget for full detail. Edit mode saves order, size,
                chart, and window locally.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <motion.button
                type="button"
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                onClick={() => setEditingLayout((value) => !value)}
                className={`glass-chip ${editingLayout ? "glass-chip-active" : ""}`}
              >
                {editingLayout ? "Done editing" : "Edit layout"}
              </motion.button>
              <motion.button
                type="button"
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                onClick={addPanel}
                disabled={
                  !METRIC_CATALOG.some(
                    (entry) =>
                      availableMetrics.has(entry.metric) &&
                      !workspace.active.panels.some(
                        (panel) => panel.metric === entry.metric,
                      ),
                  )
                }
                className="glass-chip glass-chip-active disabled:opacity-40"
              >
                Add widget +
              </motion.button>
              <motion.button
                type="button"
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                onClick={undoWorkspace}
                disabled={!workspace.history.length}
                className="glass-chip disabled:opacity-40"
              >
                Undo
              </motion.button>
              <motion.button
                type="button"
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                onClick={resetWorkspace}
                className="glass-chip"
              >
                Reset
              </motion.button>
            </div>
          </div>

          {editingLayout && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="glass-chip mb-4 w-fit text-[var(--ink-soft)]"
            >
              Drag cards to reorder · use size presets to reshape the board
            </motion.div>
          )}

          <div className="widget-grid">
            {chartablePanels.map((panel) => {
              const chartState = charts[panel.id];
              return (
                <WorkspacePanel
                  key={panel.id}
                  panel={panel}
                  points={
                    chartState?.status === "ready" ? chartState.data : null
                  }
                  selected={selectedPanel?.id === panel.id}
                  editing={editingLayout}
                  onSelect={() => setSelectedPanelId(panel.id)}
                  onOpenDetail={() =>
                    router.push(`/dashboard/${panel.metric}`)
                  }
                  onChange={(patch) => updatePanel(panel.id, patch)}
                  onRemove={() => removePanel(panel.id)}
                  onMoveUp={() => movePanel(panel.id, -1)}
                  onMoveDown={() => movePanel(panel.id, 1)}
                  onDragStart={() => setDraggedPanelId(panel.id)}
                  onDrop={() => dropPanel(panel.id)}
                />
              );
            })}
            {workspace.active.panels.length === 0 && (
              <div className="glass-card-empty">
                Add a signal to begin your saved workspace.
              </div>
            )}
          </div>
        </motion.section>

        {/* Bottom grid: Anomalies + Raw data */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.35, duration: 0.5, ease: [0.16, 1, 0.3, 1] as const }}
          className="mt-7 grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]"
        >
          {/* Anomaly section */}
          <section className="glass-card p-5">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <div className="eyebrow">Exception log · 30 days</div>
                <h2 className="mt-1 text-xl font-bold">Anomaly heatmap</h2>
              </div>
              <span
                className={`glass-chip ${
                  anomalies.status === "ready" && anomalies.data.length > 0
                    ? "glass-chip-danger"
                    : ""
                }`}
              >
                {anomalies.status === "ready"
                  ? `${anomalies.data.length} flags`
                  : "Scanning"}
              </span>
            </div>

            {anomalies.status === "loading" && (
              <p className="text-sm text-[var(--ink-soft)]">
                Scanning baseline deviations…
              </p>
            )}
            {anomalies.status === "error" && (
              <p className="text-sm text-[var(--signal-danger)]">
                Could not load anomalies.
              </p>
            )}
            {anomalies.status === "ready" && anomalies.data.length === 0 && (
              <p className="text-sm text-[var(--ink-soft)]">
                Nothing flagged — every metric is within its normal range.
              </p>
            )}
            {anomalies.status === "ready" && anomalies.data.length > 0 && (
              <motion.ul
                initial="hidden"
                animate="visible"
                variants={{
                  hidden: { opacity: 0 },
                  visible: {
                    opacity: 1,
                    transition: { staggerChildren: 0.05 },
                  },
                }}
                className="space-y-2"
              >
                {anomalies.data.slice(0, 8).map((anomaly, index) => (
                  <motion.li
                    key={`${anomaly.date}-${anomaly.metric_name}-${index}`}
                    variants={listItemVariants}
                    className="flex items-center justify-between gap-3 rounded-xl bg-[var(--glass-subtle)] px-3 py-2.5 text-sm transition-colors duration-200 hover:bg-[var(--glass)]"
                  >
                    <div>
                      <span className="font-semibold">
                        {metricDefinition(anomaly.metric_name).label}
                      </span>
                      <span className="ml-2 text-xs text-[var(--ink-soft)]">
                        {anomaly.date}
                      </span>
                    </div>
                    <span className="glass-chip glass-chip-warn">
                      {formatDelta(anomaly)}
                    </span>
                  </motion.li>
                ))}
              </motion.ul>
            )}
          </section>

          {/* Raw data section */}
          <section className="glass-card overflow-hidden p-5">
            <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="eyebrow">
                  Historical Fitbit data ·{" "}
                  {selectedPanel
                    ? selectedPanel.title
                    : "select a widget"}
                </div>
                <h2 className="mt-1 text-xl font-bold">Source records</h2>
                <p className="mt-1 text-xs text-[var(--ink-soft)]">
                  No aggregation hidden. Every row keeps its timestamp, unit,
                  source, and original file.
                </p>
              </div>
              {selectedPanel && (
                <motion.button
                  type="button"
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={() =>
                    router.push(`/dashboard/${selectedPanel.metric}`)
                  }
                  className="glass-chip glass-chip-active"
                >
                  View all raw data ↗
                </motion.button>
              )}
            </div>

            {rawData.status === "loading" && (
              <p className="text-sm text-[var(--ink-soft)]">
                Loading historical records…
              </p>
            )}
            {rawData.status === "error" && (
              <p className="text-sm text-[var(--signal-danger)]">
                Could not load raw Fitbit records.
              </p>
            )}
            {rawData.status === "ready" && (
              <>
                <div className="mb-3 flex flex-wrap gap-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
                  <span>{rawData.data.count} rows returned</span>
                  <span>·</span>
                  <span>
                    {rawData.data.source_metadata.sources.join(", ") ||
                      "Fitbit"}
                  </span>
                  {rawData.data.truncated && (
                    <span className="text-[var(--signal-warning)]">
                      · sample truncated
                    </span>
                  )}
                </div>
                <div className="glass-table-wrap">
                  <table className="glass-table">
                    <thead>
                      <tr>
                        <th>Timestamp</th>
                        <th>Signal</th>
                        <th>Value</th>
                        <th>Unit</th>
                        <th>Origin</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rawData.data.records.slice(0, 8).map((record) => (
                        <tr key={record.record_id}>
                          <td>
                            {new Date(record.timestamp).toLocaleString([], {
                              month: "short",
                              day: "numeric",
                              hour: "numeric",
                              minute: "2-digit",
                            })}
                          </td>
                          <td>
                            {record.signal_type || record.metric}
                          </td>
                          <td className="font-mono text-[var(--ink)]">
                            {formatRawValue(record.value)}
                          </td>
                          <td>{record.unit || "—"}</td>
                          <td title={record.source_file}>
                            {record.source_kind}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </section>
        </motion.div>
      </div>
    </div>
  );
}
