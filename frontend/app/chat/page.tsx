"use client";

import { useEffect, useRef, useState } from "react";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// A single bubble in the visible transcript. This is display-only state; the
// authoritative conversation_history (below) is an opaque blob from the backend.
type DisplayMessage = { role: "user" | "assistant"; text: string };

// The backend threads this back on every turn. We never interpret its internal
// structure — just hold it and send it back unchanged on the next request.
type ConversationHistory = unknown[];
type EvidenceReference = {
  evidence_id: string;
  metric?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  point_count?: number | null;
};
type WorkspaceActionProposal = {
  action_id: string;
  action_type: string;
  panel_id?: string | null;
  payload: Record<string, unknown>;
  rationale: string;
  requires_approval: true;
  reversible: true;
};
type AgentResult = {
  conversation_history: ConversationHistory;
  reply: string;
  evidence_refs?: EvidenceReference[];
  workspace_actions?: WorkspaceActionProposal[];
};
type DisplayAnalysis = {
  messageIndex: number;
  evidence: EvidenceReference[];
  actions: WorkspaceActionProposal[];
};

const AGENT_PROPOSAL_KEY = "bitfit-agent-workspace-proposal-v1";

export default function ChatPage() {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [history, setHistory] = useState<ConversationHistory | null>(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [analyses, setAnalyses] = useState<DisplayAnalysis[]>([]);

  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to the latest message whenever the transcript or typing state
  // changes.
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, loading]);

  async function sendMessage() {
    const text = input.trim();
    if (!text || loading) return;

    setInput("");
    setError(null);
    setMessages((prev) => [...prev, { role: "user", text }]);
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE_URL}/chat`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          conversation_history: history,
          workspace_context: readWorkspaceContext(),
        }),
      });

      if (!res.ok) {
        // The backend returns a 503 with a JSON { detail } message when chat is
        // unavailable (e.g. ANTHROPIC_API_KEY not configured).
        let detail = "Chat is unavailable — check that ANTHROPIC_API_KEY is configured.";
        try {
          const body = await res.json();
          if (body?.detail) detail = body.detail;
        } catch {
          // Non-JSON error body; keep the default message.
        }
        setError(detail);
        return;
      }

      const data = (await res.json()) as AgentResult;
      setHistory(data.conversation_history as ConversationHistory);
      setMessages((prev) => {
        const messageIndex = prev.length;
        setAnalyses((current) => [
          ...current,
          {
            messageIndex,
            evidence: data.evidence_refs ?? [],
            actions: data.workspace_actions ?? [],
          },
        ]);
        return [...prev, { role: "assistant", text: data.reply }];
      });
    } catch {
      setError(
        "Could not reach the assistant. Is the backend running at " +
          API_BASE_URL +
          "?",
      );
    } finally {
      setLoading(false);
    }
  }

  function readWorkspaceContext(): Record<string, unknown> | undefined {
    try {
      const raw = window.localStorage.getItem("bitfit-analytical-workspace-v1");
      if (!raw) return undefined;
      const workspace = JSON.parse(raw) as {
        active?: { id?: string; panels?: Array<{ id?: string }> };
      };
      const panels = workspace.active?.panels ?? [];
      return {
        workspace_version: workspace.active?.id,
        visible_panel_ids: panels.map((panel) => panel.id).filter(Boolean),
      };
    } catch {
      return undefined;
    }
  }

  function approveAction(action: WorkspaceActionProposal) {
    window.localStorage.setItem(AGENT_PROPOSAL_KEY, JSON.stringify(action));
    setAnalyses((current) =>
      current.map((analysis) => ({
        ...analysis,
        actions: analysis.actions.filter((item) => item.action_id !== action.action_id),
      })),
    );
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    // Enter sends; Shift+Enter is intentionally not used since this is a
    // single-line input.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  return (
    <div className="flex h-[calc(100vh-10rem)] flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Chat</h1>
        <p className="mt-1 text-sm text-black/60 dark:text-white/60">
          Ask questions about your own wearable health data.
        </p>
      </div>

      <div
        ref={scrollRef}
        className="flex-1 space-y-3 overflow-y-auto rounded-lg border border-black/10 p-4 dark:border-white/15"
      >
        {messages.length === 0 && !loading && (
          <p className="text-sm text-black/40 dark:text-white/40">
            Try: &ldquo;How did I sleep last week?&rdquo; or &ldquo;Any unusual
            readings recently?&rdquo;
          </p>
        )}

        {messages.map((m, i) => {
          const analysis = analyses.find((item) => item.messageIndex === i);
          return (
            <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
              <div className="max-w-[86%] space-y-2">
                <div
                  className={
                    "whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm " +
                    (m.role === "user"
                      ? "bg-black text-white dark:bg-white dark:text-black"
                      : "border border-black/10 dark:border-white/15")
                  }
                >
                  {m.text}
                </div>
                {m.role === "assistant" && analysis && analysis.evidence.length > 0 && (
                  <div className="rounded-lg border border-black/10 p-3 text-xs dark:border-white/15">
                    <div className="font-medium">Evidence used</div>
                    <div className="mt-2 space-y-1 text-black/55 dark:text-white/55">
                      {analysis.evidence.slice(0, 6).map((reference) => (
                        <div key={reference.evidence_id}>
                          {reference.metric ?? "Health signal"} · {reference.start_date ?? ""} to {reference.end_date ?? ""}
                          {reference.point_count != null ? ` · ${reference.point_count} points` : ""}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {m.role === "assistant" && analysis && analysis.actions.length > 0 && (
                  <div className="space-y-2 rounded-lg border border-[var(--series-1)]/40 bg-[var(--series-1)]/5 p-3 text-xs">
                    <div className="font-medium">Workspace proposal</div>
                    {analysis.actions.map((action) => (
                      <div key={action.action_id} className="space-y-2">
                        <p className="text-black/60 dark:text-white/60">{action.rationale || action.action_type}</p>
                        <button
                          type="button"
                          onClick={() => approveAction(action)}
                          className="rounded-md bg-black px-2.5 py-1.5 font-medium text-white dark:bg-white dark:text-black"
                        >
                          Approve visual change
                        </button>
                      </div>
                    ))}
                    <p className="text-[11px] text-black/45 dark:text-white/45">
                      Approval stores a reversible proposal for the dashboard; the AI cannot change it directly.
                    </p>
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {loading && (
          <div className="flex justify-start">
            <div className="rounded-2xl border border-black/10 px-4 py-2 text-sm text-black/60 dark:border-white/15 dark:text-white/60">
              <span className="inline-flex gap-1">
                <span className="animate-bounce [animation-delay:-0.3s]">•</span>
                <span className="animate-bounce [animation-delay:-0.15s]">•</span>
                <span className="animate-bounce">•</span>
              </span>
            </div>
          </div>
        )}
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-2 text-sm text-red-700 dark:text-red-300"
        >
          {error}
        </div>
      )}

      <div className="flex flex-col gap-2">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask about your sleep, heart rate, activity…"
            disabled={loading}
            className="flex-1 rounded-lg border border-black/10 bg-transparent px-4 py-2 text-sm outline-none placeholder:text-black/40 focus:border-black/30 disabled:opacity-60 dark:border-white/15 dark:placeholder:text-white/40 dark:focus:border-white/30"
          />
          <button
            type="button"
            onClick={sendMessage}
            disabled={loading || input.trim() === ""}
            className="rounded-lg bg-black px-5 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-white dark:text-black"
          >
            Send
          </button>
        </div>
        <p className="text-xs text-black/40 dark:text-white/40">
          General wellness information, not medical advice.
        </p>
      </div>
    </div>
  );
}
