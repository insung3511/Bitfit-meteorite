export type QueuedWorkspaceAction = {
  action_id: string;
  action_type: string;
  panel_id?: string | null;
  payload?: Record<string, unknown>;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isQueuedWorkspaceAction(
  value: unknown,
): value is QueuedWorkspaceAction {
  if (!isRecord(value)) return false;
  if (typeof value.action_id !== "string" || !value.action_id) return false;
  if (typeof value.action_type !== "string" || !value.action_type) return false;
  if (
    value.panel_id !== undefined &&
    value.panel_id !== null &&
    typeof value.panel_id !== "string"
  )
    return false;
  return value.payload === undefined || isRecord(value.payload);
}

export function validQueuedWorkspaceActions(
  value: unknown,
): QueuedWorkspaceAction[] {
  const candidates = Array.isArray(value) ? value : [value];
  return candidates.filter(isQueuedWorkspaceAction);
}
