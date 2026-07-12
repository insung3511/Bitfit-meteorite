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

  const signalSummary = chartablePanels.slice(0, 3).map((panel) => {
    const state = charts[panel.id];
    const points = state?.status === "ready" ? state.data : [];
    const latest = [...points].reverse().find((point) => point.mean_7d != null);
    return {
      panel,
      value: latest?.mean_7d == null ? "—" : latest.mean_7d.toLocaleString(undefined, { maximumFractionDigits: 0 }),
      date: latest?.date,
    };
  });

  const boardStatus =
    metricsState.status === "loading"
      ? "Syncing"
      : metricsState.status === "error"
        ? "Offline"
        : availableMetrics.size > 0
          ? "Live"
          : "Awaiting data";

  return (
    <div className="board-shell -mx-5 -my-6 min-h-[calc(100vh-74px)] px-5 py-6 lg:-mx-8 lg:-my-8 lg:px-8 lg:py-8">
      <div className="mx-auto max-w-[1360px]">
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_280px] xl:items-end">
          <div>
            <div className="eyebrow flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-[var(--signal-green)]" />
              Personal health telemetry / board 01
            </div>
            <h1 className="mt-3 max-w-3xl text-4xl font-black leading-[0.94] tracking-[-0.06em] text-[var(--ink)] sm:text-6xl">
              Daily signals,<br />made legible.
            </h1>
            <p className="mt-4 max-w-2xl text-sm leading-relaxed text-[var(--ink-soft)]">
              A focused view of your wearable data. Scan the board for the current
              reading, the direction of travel, and anything that needs a closer look.
            </p>
          </div>

          <div className="board-card-dark rounded-[4px] p-4">
            <div className="flex items-center justify-between border-b border-white/15 pb-3">
              <span className="eyebrow !text-white/55">Board status</span>
              <span className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.12em]">
                <span className={`h-2 w-2 rounded-full ${boardStatus === "Live" ? "bg-[var(--signal-green)]" : boardStatus === "Offline" ? "bg-[var(--signal-red)]" : "bg-[var(--signal-yellow)]"}`} />
                {boardStatus}
              </span>
            </div>
            <div className="mt-4 flex items-end justify-between gap-4">
              <div>
                <div className="text-4xl font-black tracking-[-0.06em]">{availableMetrics.size}</div>
                <div className="mt-1 text-[10px] font-bold uppercase tracking-[0.12em] text-white/45">signals connected</div>
              </div>
              <div className="text-right">
                <div className="text-2xl font-black tracking-[-0.04em]">{anomalies.status === "ready" ? anomalies.data.length : "—"}</div>
                <div className="mt-1 text-[10px] font-bold uppercase tracking-[0.12em] text-white/45">flags / 30 days</div>
              </div>
            </div>
          </div>
        </div>

        {metricsState.status === "error" && (
          <div role="alert" className="mt-6 border-l-4 border-[var(--signal-red)] bg-[var(--paper)] px-4 py-3 text-sm text-[var(--ink)]">
            Could not reach the backend at {API_BASE_URL}.
          </div>
        )}

        {noDataYet && (
          <div className="mt-6 board-card flex flex-wrap items-center justify-between gap-4 rounded-[4px] px-5 py-4">
            <div>
              <div className="eyebrow">Awaiting first reading</div>
              <p className="mt-1 text-sm text-[var(--ink-soft)]">Connect Google Health or import a Takeout export to populate the board.</p>
            </div>
            <span className="rounded bg-[var(--signal-yellow)] px-2 py-1 text-[10px] font-black uppercase tracking-[0.1em] text-[var(--ink)]">No data yet</span>
          </div>
        )}

        <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
          {signalSummary.map(({ panel, value, date }) => (
            <div key={panel.id} className="board-card relative overflow-hidden rounded-[4px] p-4">
              <div className="absolute inset-y-0 left-0 w-1" style={{ backgroundColor: panel.color }} />
              <div className="flex items-start justify-between gap-2 pl-2">
                <div>
                  <div className="eyebrow">Latest reading</div>
                  <div className="mt-1 text-sm font-black tracking-tight">{panel.title}</div>
                </div>
                <span className="flex h-6 min-w-6 items-center justify-center rounded-full text-[10px] font-black text-white" style={{ backgroundColor: panel.color }}>{panel.title.slice(0, 1)}</span>
              </div>
              <div className="mt-5 flex items-baseline gap-2 pl-2">
                <span className="stat-number text-4xl font-black tracking-[-0.07em]">{value}</span>
                <span className="text-xs font-bold uppercase text-[var(--ink-soft)]">{metricDefinition(panel.metric).unit}</span>
              </div>
              <div className="mt-2 pl-2 text-[10px] font-bold uppercase tracking-[0.1em] text-[var(--ink-soft)]">{date ? `Recorded ${date}` : "Waiting for summary"}</div>
            </div>
          ))}
          {signalSummary.length === 0 && (
            <div className="board-card rounded-[4px] p-4 text-sm text-[var(--ink-soft)] sm:col-span-3">No connected signals in this workspace.</div>
          )}
        </div>

        <section className="board-card mt-6 rounded-[4px] p-4 sm:p-5">
          <div className="-mx-4 -mt-4 mb-5 flex flex-wrap items-center justify-between gap-3 bg-[var(--ink)] px-4 py-3 text-[var(--paper)] sm:-mx-5 sm:-mt-5 sm:px-5">
            <div>
              <div className="eyebrow !text-white/55">Primary workspace</div>
              <h2 className="mt-1 text-lg font-black tracking-tight">{workspace.active.label}</h2>
              <p className="mt-0.5 text-[10px] font-bold uppercase tracking-[0.1em] text-white/45">Version {workspace.active.id === "version-default" ? "default" : workspace.active.id.slice(-5)} · {workspace.history.length > 0 ? "undo available" : "saved locally"}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" onClick={addPanel} disabled={!METRIC_CATALOG.some((entry) => availableMetrics.has(entry.metric) && !workspace.active.panels.some((panel) => panel.metric === entry.metric))} className="rounded bg-[var(--signal-yellow)] px-3 py-2 text-[10px] font-black uppercase tracking-[0.1em] text-[var(--ink)] hover:brightness-105 disabled:opacity-40">Add signal +</button>
              <button type="button" onClick={undoWorkspace} disabled={workspace.history.length === 0} className="rounded border border-white/25 px-3 py-2 text-[10px] font-black uppercase tracking-[0.1em] text-white hover:bg-white/10 disabled:opacity-40">Undo</button>
              <button type="button" onClick={resetWorkspace} className="rounded border border-white/25 px-3 py-2 text-[10px] font-black uppercase tracking-[0.1em] text-white hover:bg-white/10">Reset</button>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_260px]">
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
              <p className="col-span-full text-xs text-[var(--ink-soft)]">
                {workspace.active.panels.length - chartablePanels.length} saved signal(s) are not present in the current data source.
              </p>
            )}
            </div>

            <aside className="space-y-4 border-t border-[var(--line)] pt-4 xl:border-l xl:border-t-0 xl:pl-5">
            <div>
              <div className="eyebrow">Evidence context</div>
              <p className="mt-2 text-xs leading-relaxed text-[var(--ink-soft)]">
                Select a panel to keep the assistant anchored to the visible data.
              </p>
            </div>
            {selectedPanel ? (
              <div className="rounded border border-[var(--line)] bg-black/[0.025] p-3 text-xs dark:bg-white/[0.03]">
                <div className="flex items-center gap-2 font-black"><span className="h-2 w-2 rounded-full" style={{ backgroundColor: selectedPanel.color }} />{selectedPanel.title}</div>
                <div className="mt-1 text-[var(--ink-soft)]">
                  {selectedPanel.rangeDays}-day window · {selectedPanel.chartType} chart
                </div>
                <div className="mt-3 space-y-2">
                  <div className="eyebrow mt-3">
                    References
                  </div>
                  <div className="rounded bg-black/5 px-2 py-1.5 dark:bg-white/10">
                    {selectedPanel.title} summary points
                  </div>
                  {anomalies.status === "ready" &&
                    anomalies.data
                      .filter((item) => item.metric_name === selectedPanel.metric)
                      .slice(0, 3)
                      .map((item) => (
                        <div key={`${item.date}-${item.metric_name}`} className="rounded bg-black/5 px-2 py-1.5 dark:bg-white/10">
                          {item.date}: {formatDelta(item)}
                        </div>
                      ))}
                </div>
              </div>
            ) : (
              <p className="text-xs text-[var(--ink-soft)]">No panel selected.</p>
            )}
            <button
              type="button"
              onClick={prepareInsightProposal}
              disabled={!selectedPanel || !METRIC_CATALOG.some((entry) => availableMetrics.has(entry.metric) && !workspace.active.panels.some((panel) => panel.metric === entry.metric))}
              className="w-full rounded bg-[var(--signal-blue)] px-3 py-2.5 text-[10px] font-black uppercase tracking-[0.1em] text-white disabled:opacity-40"
            >
              Prepare assistant comparison
            </button>
            {proposal && (
              <div className="rounded border border-[var(--signal-blue)]/40 bg-[var(--signal-blue)]/5 p-3 text-xs">
                <div className="font-black">{proposal.title}</div>
                <p className="mt-1 leading-relaxed text-black/60 dark:text-white/60">{proposal.rationale}</p>
                <div className="mt-3 space-y-1.5">
                  {proposal.evidence.map((reference) => (
                    <button
                      type="button"
                      key={reference.id}
                      onClick={() => setSelectedPanelId(reference.panelId)}
                      className="block w-full rounded bg-white/70 px-2 py-1.5 text-left hover:bg-white dark:bg-black/20 dark:hover:bg-black/30"
                    >
                      {reference.label}{reference.date ? ` · ${reference.date}` : ""}
                    </button>
                  ))}
                </div>
                <div className="mt-3 flex gap-2">
                  <button type="button" onClick={approveProposal} className="rounded bg-[var(--ink)] px-2.5 py-1.5 font-bold text-[var(--paper)]">Approve</button>
                  <button type="button" onClick={() => setProposal(null)} className="rounded border border-black/15 px-2.5 py-1.5 dark:border-white/20">Dismiss</button>
                </div>
              </div>
            )}
            <p className="text-[11px] leading-relaxed text-[var(--ink-soft)]">
              Workspace changes are local and reversible. Approved assistant proposals
              create a new workspace version and can be undone.
            </p>
            </aside>
          </div>
        </section>

        <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section className="board-card rounded-[4px] p-4 sm:p-5">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div><div className="eyebrow">Exception log / 30 days</div><h2 className="mt-1 text-xl font-black tracking-tight">Anomalies</h2></div>
          <span className="rounded bg-[var(--signal-red)] px-2 py-1 text-[10px] font-black uppercase tracking-[0.1em] text-white">{anomalies.status === "ready" ? `${anomalies.data.length} flags` : "Scanning"}</span>
        </div>
        {anomalies.status === "loading" && (
            <p className="text-sm text-[var(--ink-soft)]">Loading…</p>
        )}
        {anomalies.status === "error" && (
          <p className="text-sm text-[var(--signal-red)]">
            Could not load anomalies.
          </p>
        )}
        {anomalies.status === "ready" && anomalies.data.length === 0 && (
          <p className="text-sm text-[var(--ink-soft)]">
            Nothing flagged — every metric is within its normal range.
          </p>
        )}
        {anomalies.status === "ready" && anomalies.data.length > 0 && (
          <ul className="divide-y divide-[var(--line)]">
            {anomalies.data.map((a, i) => (
              <li
                key={`${a.date}-${a.metric_name}-${i}`}
                className="flex items-center justify-between gap-4 py-3 text-sm"
              >
                <div>
                  <span className="font-medium">
                    {metricDisplayName(a.metric_name)}
                  </span>
                  <span className="ml-2 text-black/40 dark:text-white/40">
                    <span className="ml-2 text-[10px] font-bold uppercase tracking-[0.08em] text-[var(--ink-soft)]">{a.date}</span>
                  </span>
                </div>
              <span
                  className="rounded bg-[var(--signal-yellow)] px-2 py-1 text-[10px] font-black uppercase tracking-[0.06em] text-[var(--ink)]"
                >
                  {formatDelta(a)}
                </span>
              </li>
            ))}
          </ul>
        )}
        </section>

      <section className="board-card-dark rounded-[4px] p-4 sm:p-5">
        <div className="flex items-center justify-between gap-4">
          <div><div className="eyebrow !text-white/55">Assistant / clinical summary</div><h2 className="mt-1 text-xl font-black tracking-tight">Sleep coaching</h2></div>
          <button
            type="button"
            onClick={runSleepCoaching}
            disabled={coaching.status === "loading"}
            className="rounded bg-[var(--signal-yellow)] px-3 py-2 text-[10px] font-black uppercase tracking-[0.1em] text-[var(--ink)] disabled:opacity-40"
          >
            {coaching.status === "loading" ? "Analyzing…" : "Get sleep coaching"}
          </button>
        </div>

        {coaching.status === "idle" && (
          <p className="mt-4 text-sm text-white/60">
            Generate a focused summary of your recent sleep, correlated with
            heart rate and activity.
          </p>
        )}
        {coaching.status === "loading" && (
          <p className="mt-4 text-sm text-white/60">
            Reviewing your last 30 days of sleep, heart rate, and activity…
          </p>
        )}
        {coaching.status === "error" && (
          <p className="mt-4 text-sm text-[#ff8a8a]">
            {coaching.message}
          </p>
        )}
        {coaching.status === "ready" && (
          <p className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-white/85">
            {coaching.text}
          </p>
        )}
        <p className="mt-4 text-xs text-white/40">
          General wellness information, not medical advice.
        </p>
      </section>
        </div>
      </div>
    </div>
  );
}
