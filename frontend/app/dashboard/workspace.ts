export type ChartType = "area" | "line" | "bar";
export type RangeDays = 7 | 30 | 90;
export type PanelSize = "small" | "medium" | "large";

export type MetricDefinition = {
  metric: string;
  label: string;
  color: string;
  unit: string;
};

export type WorkspacePanel = {
  id: string;
  metric: string;
  title: string;
  chartType: ChartType;
  rangeDays: RangeDays;
  showBaseline: boolean;
  color: string;
  size?: PanelSize;
};

export type WorkspaceVersion = {
  id: string;
  label: string;
  createdAt: string;
  panels: WorkspacePanel[];
};

export type WorkspaceDocument = {
  active: WorkspaceVersion;
  history: WorkspaceVersion[];
};

export type EvidenceReference = {
  id: string;
  label: string;
  panelId: string;
  date?: string;
  detail?: string;
};

export type WorkspacePatch = {
  kind: "add_panel" | "update_panel" | "focus_panel";
  panel?: WorkspacePanel;
  panelId?: string;
};

export type WorkspaceActionProposal = {
  id: string;
  title: string;
  rationale: string;
  patch: WorkspacePatch;
  evidence: EvidenceReference[];
};

/* ── Metric catalog with unique colors (inspired by Velovories / Zürich Card) ── */
export const METRIC_CATALOG: MetricDefinition[] = [
  { metric: "steps", label: "Steps", color: "var(--metric-steps)", unit: "steps" },
  {
    metric: "resting_heart_rate",
    label: "Resting Heart Rate",
    color: "var(--metric-resting_heart_rate)",
    unit: "bpm",
  },
  {
    metric: "sleep_deep_minutes",
    label: "Deep Sleep",
    color: "var(--metric-sleep_deep_minutes)",
    unit: "minutes",
  },
  {
    metric: "sleep_rem_minutes",
    label: "REM Sleep",
    color: "var(--metric-sleep_rem_minutes)",
    unit: "minutes",
  },
  {
    metric: "sleep_minutes",
    label: "Total Sleep",
    color: "var(--metric-sleep_minutes)",
    unit: "minutes",
  },
  { metric: "hrv", label: "HRV", color: "var(--metric-hrv)", unit: "ms" },
  { metric: "spo2", label: "SpO2", color: "var(--metric-spo2)", unit: "%" },
  { metric: "weight", label: "Weight", color: "var(--metric-weight)", unit: "kg" },
];

export function metricDefinition(metric: string): MetricDefinition {
  const known = METRIC_CATALOG.find((entry) => entry.metric === metric);
  if (known) return known;
  return {
    metric,
    label: metric
      .split("_")
      .map((word) => word[0]?.toUpperCase() + word.slice(1))
      .join(" "),
    color: "var(--signal-active)",
    unit: "value",
  };
}

function stablePanel(metric: string, index: number): WorkspacePanel {
  const definition = metricDefinition(metric);
  return {
    id: `panel-${metric}-${index}`,
    metric,
    title: definition.label,
    chartType: "area",
    rangeDays: 30,
    showBaseline: true,
    color: definition.color,
    size: index === 0 ? "large" : "medium",
  };
}

export function createDefaultWorkspace(): WorkspaceDocument {
  const panels = ["steps", "sleep_minutes", "weight"].map(stablePanel);
  return {
    active: {
      id: "version-default",
      label: "Personal overview",
      createdAt: "2020-01-01T00:00:00.000Z",
      panels,
    },
    history: [],
  };
}

export function createVersionId(): string {
  return `version-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

export function commitWorkspaceVersion(
  workspace: WorkspaceDocument,
  panels: WorkspacePanel[],
  label: string,
): WorkspaceDocument {
  return {
    active: {
      id: createVersionId(),
      label,
      createdAt: new Date().toISOString(),
      panels,
    },
    history: [...workspace.history, workspace.active].slice(-12),
  };
}

export function isWorkspaceDocument(value: unknown): value is WorkspaceDocument {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<WorkspaceDocument>;
  return Boolean(
    candidate.active &&
      typeof candidate.active.id === "string" &&
      Array.isArray(candidate.active.panels) &&
      Array.isArray(candidate.history),
  );
}

export function createPanel(metric: string, index: number): WorkspacePanel {
  return stablePanel(metric, index);
}
