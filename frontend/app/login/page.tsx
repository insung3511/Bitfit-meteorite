"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";

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
    <div className="relative flex min-h-screen items-center justify-center bg-[var(--bg-primary,#000000)] px-4">
      {/* Subtle grid background */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            "radial-gradient(circle at 1px 1px, rgba(255,255,255,0.04) 1px, transparent 0)",
          backgroundSize: "24px 24px",
          maskImage: "radial-gradient(ellipse at center, black 30%, transparent 70%)",
          WebkitMaskImage:
            "radial-gradient(ellipse at center, black 30%, transparent 70%)",
        }}
      />

      <motion.form
        onSubmit={handleSubmit}
        initial={{ opacity: 0, y: 30, scale: 0.95 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] as const }}
        className="module-card relative z-10 flex w-full max-w-sm flex-col gap-5 p-8"
      >
        <div className="text-center">
          {/* Terminal header */}
          <div className="mb-4 flex items-center justify-center gap-2 font-mono text-xs tracking-widest text-[var(--accent-cyan,#00d4ff)]">
            <span>&gt;</span>
            <span className="uppercase">Authentication Required</span>
          </div>

          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ delay: 0.2, type: "spring", stiffness: 200, damping: 15 }}
            className="mx-auto mb-4 flex h-12 w-12 items-center justify-center border border-[var(--accent-cyan,#00d4ff)] bg-[rgba(0,212,255,0.08)] text-2xl text-[var(--accent-cyan,#00d4ff)]"
            style={{ borderRadius: "4px" }}
          >
            ✦
          </motion.div>
          <h1 className="text-xl font-bold tracking-tight text-[var(--text-primary,#e8e8f0)]">
            BitFit Meteorite
          </h1>
          <p className="cmd-label mt-2">
            Enter your password to access your health data.
          </p>
        </div>

        <div className="relative">
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            autoFocus
            disabled={loading}
            className="cmd-input w-full"
            suppressHydrationWarning
          />
        </div>

        {error && (
          <motion.p
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-sm"
            style={{ color: "var(--signal-danger, #ff4d6d)" }}
          >
            {error}
          </motion.p>
        )}

        <motion.button
          type="submit"
          disabled={loading || !password}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className="cmd-btn-primary w-full justify-center"
        >
          {loading ? "Logging in…" : "Log in"}
        </motion.button>

        <p className="text-center text-[10px] uppercase tracking-[0.12em] text-[var(--text-muted,#3d3d52)]">
          Local-only · Encrypted tokens
        </p>
      </motion.form>
    </div>
  );
}
