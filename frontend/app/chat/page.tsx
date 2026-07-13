"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import TypingIndicator from "../components/TypingIndicator";

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

const messageVariants = {
  user: {
    initial: { opacity: 0, x: 20, scale: 0.95 },
    animate: { opacity: 1, x: 0, scale: 1 },
  },
  assistant: {
    initial: { opacity: 0, x: -20, scale: 0.95 },
    animate: { opacity: 1, x: 0, scale: 1 },
  },
};

const transition = {
  duration: 0.4,
  ease: [0.16, 1, 0.3, 1] as const,
};

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
        let detail =
          "Chat is unavailable — check that ANTHROPIC_API_KEY is configured.";
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

  function readWorkspaceContext():
    | Record<string, unknown>
    | undefined {
    try {
      const raw = window.localStorage.getItem(
        "bitfit-analytical-workspace-v1",
      );
      if (!raw) return undefined;
      const workspace = JSON.parse(raw) as {
        active?: { id?: string; panels?: Array<{ id?: string }> };
      };
      const panels = workspace.active?.panels ?? [];
      return {
        workspace_version: workspace.active?.id,
        visible_panel_ids: panels
          .map((panel) => panel.id)
          .filter(Boolean),
      };
    } catch {
      return undefined;
    }
  }

  function approveAction(action: WorkspaceActionProposal) {
    window.localStorage.setItem(
      AGENT_PROPOSAL_KEY,
      JSON.stringify(action),
    );
    setAnalyses((current) =>
      current.map((analysis) => ({
        ...analysis,
        actions: analysis.actions.filter(
          (item) => item.action_id !== action.action_id,
        ),
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

  const quickPrompts = [
    "How did my sleep trend over the last 30 days?",
    "Show unusual Fitbit readings in my history.",
    "Compare my steps and sleep patterns.",
  ];

  return (
    <div className="board-shell min-h-screen px-4 pb-32 pt-8 sm:px-8 lg:px-12">
      <div className="mx-auto flex min-h-[calc(100vh-10rem)] max-w-[1180px] flex-col gap-6">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] as const }}
          className="flex flex-wrap items-end justify-between gap-5"
        >
          <div>
            <div className="eyebrow flex items-center gap-2">
              <span className="status-dot status-dot-good" /> Fitbit history
              assistant · grounded chat
            </div>
            <h1 className="mt-3 text-5xl font-bold tracking-[-0.04em] sm:text-7xl">
              Ask your{" "}
              <span className="gradient-text">history.</span>
            </h1>
            <p className="mt-4 max-w-xl text-sm leading-relaxed text-[var(--ink-soft)]">
              Ask questions about your imported Fitbit records. Answers are
              based on the historical data available in your workspace, not a
              live health feed.
            </p>
          </div>
          <div className="glass-card p-4">
            <div className="eyebrow">Data mode</div>
            <div className="mt-2 flex items-center gap-2 text-sm font-semibold">
              <span className="status-dot status-dot-good" /> Historical
              archive
            </div>
          </div>
        </motion.div>

        {/* Chat area */}
        <div
          ref={scrollRef}
          className="glass-card flex-1 space-y-4 overflow-y-auto p-4 sm:p-6"
        >
          <AnimatePresence>
            {messages.length === 0 && !loading && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] as const }}
                className="flex min-h-[28rem] flex-col justify-center"
              >
                <div className="mx-auto w-full max-w-2xl text-center">
                  <motion.div
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{
                      delay: 0.2,
                      type: "spring",
                      stiffness: 200,
                      damping: 15,
                    }}
                    className="signal-mark mx-auto h-14 w-14 rounded-2xl text-xl"
                  >
                    ✦
                  </motion.div>
                  <h2 className="mt-5 text-2xl font-bold tracking-tight">
                    What do you want to understand?
                  </h2>
                  <p className="mt-2 text-sm text-[var(--ink-soft)]">
                    Start with a question, then inspect the evidence the
                    assistant used.
                  </p>
                  <div className="mt-7 grid gap-2 text-left sm:grid-cols-3">
                    {quickPrompts.map((prompt, i) => (
                      <motion.button
                        key={prompt}
                        type="button"
                        initial={{ opacity: 0, y: 12 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{
                          delay: 0.3 + i * 0.1,
                          duration: 0.4,
                          ease: [0.16, 1, 0.3, 1] as const,
                        }}
                        whileHover={{ scale: 1.03, y: -2 }}
                        whileTap={{ scale: 0.98 }}
                        onClick={() => setInput(prompt)}
                        className="glass-chip h-auto min-h-12 justify-start rounded-2xl px-3 py-3 normal-case tracking-normal"
                      >
                        {prompt}
                      </motion.button>
                    ))}
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <AnimatePresence initial={false}>
            {messages.map((message, index) => {
              const analysis = analyses.find(
                (item) => item.messageIndex === index,
              );
              const isUser = message.role === "user";

              return (
                <motion.div
                  key={index}
                  initial={
                    isUser
                      ? messageVariants.user.initial
                      : messageVariants.assistant.initial
                  }
                  animate={
                    isUser
                      ? messageVariants.user.animate
                      : messageVariants.assistant.animate
                  }
                  transition={transition}
                  className={isUser ? "flex justify-end" : "flex justify-start"}
                >
                  <div className="max-w-[86%] space-y-2">
                    <div
                      className={
                        isUser
                          ? "whitespace-pre-wrap rounded-2xl rounded-br-md bg-[var(--signal-active)] px-4 py-3 text-sm text-white shadow-lg"
                          : "glass-card-strong whitespace-pre-wrap rounded-2xl rounded-bl-md px-4 py-3 text-sm"
                      }
                    >
                      {message.text}
                    </div>

                    {/* Evidence */}
                    {message.role === "assistant" &&
                      analysis?.evidence.length ? (
                      <motion.div
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.2, ...transition }}
                        className="glass-card-strong p-3 text-xs"
                      >
                        <div className="eyebrow">Evidence used</div>
                        <div className="mt-2 space-y-1 text-[var(--ink-soft)]">
                          {analysis.evidence.slice(0, 6).map((reference) => (
                            <div key={reference.evidence_id}>
                              {reference.metric ?? "Health signal"} ·{" "}
                              {reference.start_date ?? ""} to{" "}
                              {reference.end_date ?? ""}
                              {reference.point_count != null
                                ? ` · ${reference.point_count} points`
                                : ""}
                            </div>
                          ))}
                        </div>
                      </motion.div>
                    ) : null}

                    {/* Workspace proposals */}
                    {message.role === "assistant" &&
                      analysis?.actions.length ? (
                      <motion.div
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.3, ...transition }}
                        className="glass-card-strong space-y-2 border border-[var(--signal-active)]/25 p-3 text-xs"
                      >
                        <div className="eyebrow">Workspace proposal</div>
                        {analysis.actions.map((action) => (
                          <div key={action.action_id} className="space-y-2">
                            <p className="text-[var(--ink-soft)]">
                              {action.rationale || action.action_type}
                            </p>
                            <motion.button
                              type="button"
                              whileHover={{ scale: 1.05 }}
                              whileTap={{ scale: 0.95 }}
                              onClick={() => approveAction(action)}
                              className="glass-chip glass-chip-active"
                            >
                              Approve layout change
                            </motion.button>
                          </div>
                        ))}
                        <p className="text-[11px] text-[var(--ink-soft)]">
                          Approval stores a reversible dashboard proposal.
                        </p>
                      </motion.div>
                    ) : null}
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>

          {/* Typing indicator */}
          <AnimatePresence>
            {loading && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -5 }}
                transition={transition}
                className="flex justify-start"
              >
                <div className="glass-card-strong rounded-2xl rounded-bl-md px-4 py-3 text-sm text-[var(--ink-soft)]">
                  <TypingIndicator />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Error */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              role="alert"
              className="glass-card border-l-4 border-[var(--signal-danger)] px-4 py-3 text-sm text-[var(--signal-danger)]"
            >
              {error}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Input */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2, duration: 0.5, ease: [0.16, 1, 0.3, 1] as const }}
          className="glass-card p-3 sm:p-4"
        >
          <div className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Ask about your Fitbit history…"
              disabled={loading}
              className="glass-select flex-1 rounded-2xl px-4 py-3 text-sm"
            />
            <motion.button
              type="button"
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              onClick={sendMessage}
              disabled={loading || input.trim() === ""}
              className="glass-chip glass-chip-active min-h-11 px-5 disabled:opacity-40"
            >
              {loading ? "Thinking…" : "Send ↗"}
            </motion.button>
          </div>
          <p className="mt-3 px-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
            Historical wellness context only · not medical advice
          </p>
        </motion.div>
      </div>
    </div>
  );
}
