"use client";

import { useEffect, useMemo, useState } from "react";
import WorkspacePanel from "./WorkspacePanel";
import { type SummaryPoint } from "./MetricChart";
import {
  commitWorkspaceVersion,
  createDefaultWorkspace,
  createPanel,
  isWorkspaceDocument,
  METRIC_CATALOG,
  metricDefinition,
  type EvidenceReference,
  type WorkspaceActionProposal,
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

type AnomaliesResponse = { count: number; anomalies: Anomaly[] };
type MetricsResponse = { metrics: string[] };
type SummaryResponse = { metric: string; points: SummaryPoint[] };
type AgentAction = {
  action_id: string;
  action_type: string;
  panel_id?: string | null;
  payload?: Record<string, unknown>;
};

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
  return metricDefinition(metric).label;
}

export default function DashboardPage() {
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
  const [proposal, setProposal] = useState<WorkspaceActionProposal | null>(null);
  const [pendingAgentAction, setPendingAgentAction] = useState<AgentAction | null>(null);
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
    let cancelled = false;
    const hydrate = window.setTimeout(() => {
      try {
        const saved = window.localStorage.getItem(WORKSPACE_STORAGE_KEY);
        if (saved) {
          const parsed: unknown = JSON.parse(saved);
          if (!cancelled && isWorkspaceDocument(parsed)) setWorkspace(parsed);
        }
      } catch {
        // A malformed local workspace should never prevent the dashboard loading.
      } finally {
        if (!cancelled) setWorkspaceReady(true);
      }
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(hydrate);
    };
  }, []);

  useEffect(() => {
    if (!workspaceReady) return;
    window.localStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify(workspace));
  }, [workspace, workspaceReady]);

  useEffect(() => {
    if (!workspaceReady) return;
    const timer = window.setTimeout(() => {
      try {
        const saved = window.localStorage.getItem(AGENT_PROPOSAL_KEY);
        if (saved) {
          const parsed = JSON.parse(saved) as AgentAction;
          if (parsed && typeof parsed.action_id === "string") {
            setPendingAgentAction(parsed);
            window.localStorage.removeItem(AGENT_PROPOSAL_KEY);
          }
        }
      } catch {
        window.localStorage.removeItem(AGENT_PROPOSAL_KEY);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [workspaceReady]);

  useEffect(() => {
    if (!pendingAgentAction) return;
    const action = pendingAgentAction;
    const timer = window.setTimeout(() => setWorkspace((current) => {
      if (action.action_type === "add_chart") {
        const chart = action.payload?.chart;
        if (chart && typeof chart === "object") {
          const candidate = chart as Record<string, unknown>;
          const metric = typeof candidate.metric === "string" ? candidate.metric : null;
          if (metric && availableMetrics.has(metric) && !current.active.panels.some((panel) => panel.metric === metric)) {
            const panel = createPanel(metric, current.active.panels.length);
            setSelectedPanelId(panel.id);
            return commitWorkspaceVersion(current, [...current.active.panels, panel], "Approved AI chart proposal");
          }
        }
      }
      if (action.action_type === "set_date_range" && action.panel_id) {
        const range = Number(action.payload?.range_days);
        if (range === 7 || range === 30 || range === 90) {
          return commitWorkspaceVersion(
            current,
            current.active.panels.map((panel) =>
              panel.id === action.panel_id ? { ...panel, rangeDays: range as Panel["rangeDays"] } : panel,
            ),
            "Applied AI date-range proposal",
          );
        }
      }
      if (action.action_type === "focus_panel" && action.panel_id) {
        setSelectedPanelId(action.panel_id);
      }
      return current;
    }), 0);
    const clear = window.setTimeout(() => setPendingAgentAction(null), 0);
    return () => {
      window.clearTimeout(timer);
      window.clearTimeout(clear);
    };
  }, [availableMetrics, pendingAgentAction]);

  useEffect(() => {
    if (metricsState.status !== "ready") return;
    let cancelled = false;

    for (const panel of workspace.active.panels) {
      const { metric } = panel;
      if (!availableMetrics.has(metric)) continue;
      getJSON<SummaryResponse>(
        `/dashboard/summary?metric=${encodeURIComponent(metric)}&days=${panel.rangeDays}`,
      )
        .then((res) => {
          if (cancelled) return;
          setCharts((prev) => ({
            ...prev,
            [panel.id]: { status: "ready", data: res.points },
          }));
        })
        .catch((err) => {
          if (cancelled) return;
          setCharts((prev) => ({
            ...prev,
            [panel.id]: { status: "error", message: String(err) },
          }));
        });
    }

    return () => {
      cancelled = true;
    };
  }, [metricsState.status, availableMetrics, workspace.active.panels]);

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

  const chartablePanels = useMemo(
    () => workspace.active.panels.filter((panel) => availableMetrics.has(panel.metric)),
    [availableMetrics, workspace.active.panels],
  );
  const selectedPanel =
    workspace.active.panels.find((panel) => panel.id === selectedPanelId) ??
    chartablePanels[0] ??
    null;

  function updatePanel(panelId: string, patch: Partial<Panel>) {
    const panels = workspace.active.panels.map((panel) =>
      panel.id === panelId ? { ...panel, ...patch } : panel,
    );
    commitPanels(panels, "Updated panel settings");
  }

  function commitPanels(panels: Panel[], label: string) {
    setWorkspace((current) => commitWorkspaceVersion(current, panels, label));
  }

  function removePanel(panelId: string) {
    const panels = workspace.active.panels.filter((panel) => panel.id !== panelId);
    commitPanels(panels, "Removed a panel");
    if (selectedPanelId === panelId) setSelectedPanelId(null);
  }

  function addPanel() {
    const nextMetric = METRIC_CATALOG.find(
      (entry) =>
        availableMetrics.has(entry.metric) &&
        !workspace.active.panels.some((panel) => panel.metric === entry.metric),
    );
    if (!nextMetric) return;
    const panel = createPanel(nextMetric.metric, workspace.active.panels.length);
    commitPanels([...workspace.active.panels, panel], "Added a panel");
    setSelectedPanelId(panel.id);
  }

  function undoWorkspace() {
    setWorkspace((current) => {
      const previous = current.history.at(-1);
      if (!previous) return current;
      return { active: previous, history: current.history.slice(0, -1) };
    });
  }

  function resetWorkspace() {
    commitPanels(createDefaultWorkspace().active.panels, "Restored overview");
  }

  function prepareInsightProposal() {
    const comparisonMetric = METRIC_CATALOG.find(
      (entry) =>
        availableMetrics.has(entry.metric) &&
        !workspace.active.panels.some((panel) => panel.metric === entry.metric),
    );
    const sourcePanel = selectedPanel ?? chartablePanels[0];
    if (!sourcePanel || !comparisonMetric) return;
    const panel = createPanel(comparisonMetric.metric, workspace.active.panels.length);
    const evidence: EvidenceReference[] = [
      {
        id: `evidence-${sourcePanel.id}`,
        panelId: sourcePanel.id,
        label: sourcePanel.title,
        detail: `${sourcePanel.rangeDays}-day rolling view`,
      },
    ];
    if (anomalies.status === "ready" && anomalies.data.length > 0) {
      const anomaly = anomalies.data.find((item) => item.metric_name === sourcePanel.metric);
      if (anomaly) {
        evidence.push({
          id: `anomaly-${anomaly.date}-${anomaly.metric_name}`,
          panelId: sourcePanel.id,
          label: `${metricDisplayName(anomaly.metric_name)} anomaly`,
          date: anomaly.date,
          detail: formatDelta(anomaly),
        });
      }
    }
    setProposal({
      id: `proposal-${Date.now()}`,
      title: `Compare ${sourcePanel.title} with ${metricDefinition(comparisonMetric.metric).label}`,
      rationale:
        "The assistant can add a second signal to the current view so you can inspect the relationship before drawing conclusions.",
      patch: { kind: "add_panel", panel },
      evidence,
    });
  }

  function approveProposal() {
    if (!proposal) return;
    if (proposal.patch.kind === "add_panel" && proposal.patch.panel) {
      commitPanels(
        [...workspace.active.panels, proposal.patch.panel],
        "Approved assistant comparison",
      );
      setSelectedPanelId(proposal.patch.panel.id);
    }
    if (proposal.patch.kind === "focus_panel" && proposal.patch.panelId) {
      setSelectedPanelId(proposal.patch.panelId);
    }
    setProposal(null);
  }

  const noDataYet =
    metricsState.status === "ready" && availableMetrics.size === 0;

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <p className="mt-1 max-w-2xl text-sm text-black/60 dark:text-white/60">
          Build a saved view of your signals, then ask the assistant to focus on
          the evidence you are looking at.
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

      <section className="rounded-xl border border-black/10 p-4 dark:border-white/15">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-medium">Analytical workspace</h2>
            <p className="mt-1 text-xs text-black/45 dark:text-white/45">
              {workspace.active.label} · version {workspace.active.id.slice(-5)} ·
              {workspace.history.length > 0 ? " undo available" : " saved locally"}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={addPanel}
              disabled={!METRIC_CATALOG.some((entry) => availableMetrics.has(entry.metric) && !workspace.active.panels.some((panel) => panel.metric === entry.metric))}
              className="rounded-md border border-black/15 px-3 py-1.5 text-xs font-medium hover:bg-black/5 disabled:opacity-40 dark:border-white/20 dark:hover:bg-white/10"
            >
              Add signal
            </button>
            <button
              type="button"
              onClick={undoWorkspace}
              disabled={workspace.history.length === 0}
              className="rounded-md border border-black/15 px-3 py-1.5 text-xs hover:bg-black/5 disabled:opacity-40 dark:border-white/20 dark:hover:bg-white/10"
            >
              Undo
            </button>
            <button
              type="button"
              onClick={resetWorkspace}
              className="rounded-md border border-black/15 px-3 py-1.5 text-xs hover:bg-black/5 dark:border-white/20 dark:hover:bg-white/10"
            >
              Restore overview
            </button>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_18rem]">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {chartablePanels.map((panel) => {
              const state = charts[panel.id];
              return (
                <WorkspacePanel
                  key={panel.id}
                  panel={panel}
                  points={state?.status === "ready" ? state.data : null}
                  selected={selectedPanel?.id === panel.id}
                  onSelect={() => setSelectedPanelId(panel.id)}
                  onChange={(patch) => updatePanel(panel.id, patch)}
                  onRemove={() => removePanel(panel.id)}
                />
              );
            })}
            {workspace.active.panels.length === 0 && (
              <div className="flex min-h-52 items-center justify-center rounded-lg border border-dashed border-black/15 p-6 text-center text-sm text-black/45 dark:border-white/20 dark:text-white/45">
                Add a signal to begin your saved workspace.
              </div>
            )}
            {workspace.active.panels.length > chartablePanels.length && (
              <p className="col-span-full text-xs text-black/40 dark:text-white/40">
                {workspace.active.panels.length - chartablePanels.length} saved signal(s) are not present in the current data source.
              </p>
            )}
          </div>

          <aside className="space-y-4 border-t border-black/10 pt-4 xl:border-l xl:border-t-0 xl:pl-4 dark:border-white/15">
            <div>
              <h3 className="text-sm font-medium">Evidence context</h3>
              <p className="mt-1 text-xs leading-relaxed text-black/50 dark:text-white/50">
                Select a panel to keep the assistant anchored to the visible data.
              </p>
            </div>
            {selectedPanel ? (
              <div className="rounded-lg border border-black/10 p-3 text-xs dark:border-white/15">
                <div className="font-medium">{selectedPanel.title}</div>
                <div className="mt-1 text-black/50 dark:text-white/50">
                  {selectedPanel.rangeDays}-day window · {selectedPanel.chartType} chart
                </div>
                <div className="mt-3 space-y-2">
                  <div className="text-[11px] uppercase tracking-wide text-black/40 dark:text-white/40">
                    References
                  </div>
                  <div className="rounded-md bg-black/5 px-2 py-1.5 dark:bg-white/10">
                    {selectedPanel.title} summary points
                  </div>
                  {anomalies.status === "ready" &&
                    anomalies.data
                      .filter((item) => item.metric_name === selectedPanel.metric)
                      .slice(0, 3)
                      .map((item) => (
                        <div key={`${item.date}-${item.metric_name}`} className="rounded-md bg-black/5 px-2 py-1.5 dark:bg-white/10">
                          {item.date}: {formatDelta(item)}
                        </div>
                      ))}
                </div>
              </div>
            ) : (
              <p className="text-xs text-black/45 dark:text-white/45">No panel selected.</p>
            )}
            <button
              type="button"
              onClick={prepareInsightProposal}
              disabled={!selectedPanel || !METRIC_CATALOG.some((entry) => availableMetrics.has(entry.metric) && !workspace.active.panels.some((panel) => panel.metric === entry.metric))}
              className="w-full rounded-md bg-black px-3 py-2 text-xs font-medium text-white disabled:opacity-40 dark:bg-white dark:text-black"
            >
              Prepare assistant comparison
            </button>
            {proposal && (
              <div className="rounded-lg border border-[var(--series-1)]/40 bg-[var(--series-1)]/5 p-3 text-xs">
                <div className="font-medium">{proposal.title}</div>
                <p className="mt-1 leading-relaxed text-black/60 dark:text-white/60">{proposal.rationale}</p>
                <div className="mt-3 space-y-1.5">
                  {proposal.evidence.map((reference) => (
                    <button
                      type="button"
                      key={reference.id}
                      onClick={() => setSelectedPanelId(reference.panelId)}
                      className="block w-full rounded-md bg-white/70 px-2 py-1.5 text-left hover:bg-white dark:bg-black/20 dark:hover:bg-black/30"
                    >
                      {reference.label}{reference.date ? ` · ${reference.date}` : ""}
                    </button>
                  ))}
                </div>
                <div className="mt-3 flex gap-2">
                  <button type="button" onClick={approveProposal} className="rounded-md bg-black px-2.5 py-1.5 font-medium text-white dark:bg-white dark:text-black">Approve</button>
                  <button type="button" onClick={() => setProposal(null)} className="rounded-md border border-black/15 px-2.5 py-1.5 dark:border-white/20">Dismiss</button>
                </div>
              </div>
            )}
            <p className="text-[11px] leading-relaxed text-black/40 dark:text-white/40">
              Workspace changes are local and reversible. Approved assistant proposals
              create a new workspace version and can be undone.
            </p>
          </aside>
        </div>
      </section>

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
