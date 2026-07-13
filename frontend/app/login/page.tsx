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
    <div className="mesh-gradient relative flex min-h-screen items-center justify-center px-4">
      {/* Floating orbs for depth */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <motion.div
          className="absolute h-64 w-64 rounded-full opacity-20"
          style={{
            background: "radial-gradient(circle, var(--signal-active), transparent 70%)",
            top: "10%",
            left: "20%",
          }}
          animate={{
            x: [0, 30, -20, 0],
            y: [0, -20, 15, 0],
          }}
          transition={{ duration: 12, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute h-48 w-48 rounded-full opacity-15"
          style={{
            background: "radial-gradient(circle, var(--signal-purple), transparent 70%)",
            top: "60%",
            right: "15%",
          }}
          animate={{
            x: [0, -25, 20, 0],
            y: [0, 20, -15, 0],
          }}
          transition={{ duration: 10, repeat: Infinity, ease: "easeInOut" }}
        />
      </div>

      <motion.form
        onSubmit={handleSubmit}
        initial={{ opacity: 0, y: 30, scale: 0.95 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] as const }}
        className="glass-card-strong relative z-10 flex w-full max-w-sm flex-col gap-5 p-8"
      >
        <div className="text-center">
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ delay: 0.2, type: "spring", stiffness: 200, damping: 15 }}
            className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl text-2xl"
            style={{
              background: "color-mix(in srgb, var(--signal-active) 15%, transparent)",
            }}
          >
            ✦
          </motion.div>
          <h1 className="text-xl font-bold tracking-tight">BitFit Meteorite</h1>
          <p className="mt-1.5 text-sm text-[var(--ink-soft)]">
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
            className="w-full rounded-xl border border-[var(--line)] bg-[var(--glass-subtle)] px-4 py-3 text-sm text-[var(--ink)] outline-none transition-all duration-300 placeholder:text-[var(--ink-soft)] focus:border-[var(--signal-active)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--signal-active)_12%,transparent)] disabled:opacity-60"
          />
        </div>

        {error && (
          <motion.p
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-sm text-[var(--signal-danger)]"
          >
            {error}
          </motion.p>
        )}

        <motion.button
          type="submit"
          disabled={loading || !password}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className="rounded-xl bg-[var(--signal-active)] px-4 py-3 text-sm font-semibold text-white transition-shadow duration-300 hover:shadow-[0_0_20px_color-mix(in_srgb,var(--signal-active)_30%,transparent)] disabled:opacity-40"
        >
          {loading ? "Logging in…" : "Log in"}
        </motion.button>

        <p className="text-center text-[10px] uppercase tracking-[0.12em] text-[var(--ink-soft)] opacity-50">
          Local-only · Encrypted tokens
        </p>
      </motion.form>
    </div>
  );
}
