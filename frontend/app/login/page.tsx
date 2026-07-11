"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function LoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!password || loading) return;
    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE_URL}/session/login`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });

      if (!res.ok) {
        setError(
          res.status === 401
            ? "Incorrect password."
            : "Could not log in — check the backend is running and configured.",
        );
        return;
      }

      router.replace("/");
      router.refresh();
    } catch {
      setError(`Could not reach the backend at ${API_BASE_URL}.`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-[70vh] items-center justify-center">
      <form
        onSubmit={handleSubmit}
        className="flex w-full max-w-sm flex-col gap-4 rounded-xl border border-black/10 p-6 dark:border-white/15"
      >
        <div>
          <h1 className="text-lg font-semibold">Health Assistant</h1>
          <p className="mt-1 text-sm text-black/60 dark:text-white/60">
            Enter your password to continue.
          </p>
        </div>

        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          autoFocus
          disabled={loading}
          className="rounded-lg border border-black/10 bg-transparent px-4 py-2 text-sm outline-none placeholder:text-black/40 focus:border-black/30 disabled:opacity-60 dark:border-white/15 dark:placeholder:text-white/40 dark:focus:border-white/30"
        />

        {error && (
          <p role="alert" className="text-sm text-red-700 dark:text-red-300">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading || !password}
          className="rounded-lg bg-black px-4 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-white dark:text-black"
        >
          {loading ? "Logging in…" : "Log in"}
        </button>
      </form>
    </div>
  );
}
