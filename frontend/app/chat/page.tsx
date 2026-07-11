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

export default function ChatPage() {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [history, setHistory] = useState<ConversationHistory | null>(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
        body: JSON.stringify({ message: text, conversation_history: history }),
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

      const data = await res.json();
      setHistory(data.conversation_history as ConversationHistory);
      setMessages((prev) => [...prev, { role: "assistant", text: data.reply }]);
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

        {messages.map((m, i) => (
          <div
            key={i}
            className={
              m.role === "user" ? "flex justify-end" : "flex justify-start"
            }
          >
            <div
              className={
                "max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm " +
                (m.role === "user"
                  ? "bg-black text-white dark:bg-white dark:text-black"
                  : "border border-black/10 dark:border-white/15")
              }
            >
              {m.text}
            </div>
          </div>
        ))}

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
