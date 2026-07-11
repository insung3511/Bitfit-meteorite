"use client";

import { useEffect, useState } from "react";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type Status = "checking" | "connected" | "unreachable";

export default function Home() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    let cancelled = false;

    async function checkHealth() {
      try {
        const res = await fetch(`${API_BASE_URL}/health`);
        if (!cancelled) {
          setStatus(res.ok ? "connected" : "unreachable");
        }
      } catch {
        if (!cancelled) {
          setStatus("unreachable");
        }
      }
    }

    checkHealth();
    return () => {
      cancelled = true;
    };
  }, []);

  const label =
    status === "checking"
      ? "Backend: checking…"
      : status === "connected"
        ? "Backend: connected"
        : "Backend: unreachable";

  const dotColor =
    status === "checking"
      ? "bg-yellow-500"
      : status === "connected"
        ? "bg-green-500"
        : "bg-red-500";

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold">Personal Health Assistant</h1>
        <p className="mt-2 text-sm text-black/60 dark:text-white/60">
          Chat with and get insights from your own wearable health data.
        </p>
      </div>

      <div className="flex items-center gap-2 rounded-lg border border-black/10 px-4 py-3 text-sm dark:border-white/15">
        <span className={`inline-block h-2.5 w-2.5 rounded-full ${dotColor}`} />
        <span>{label}</span>
        <span className="ml-auto font-mono text-xs text-black/40 dark:text-white/40">
          {API_BASE_URL}
        </span>
      </div>
    </div>
  );
}
