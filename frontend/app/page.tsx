"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import Link from "next/link";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type Status = "checking" | "connected" | "unreachable";

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.08, delayChildren: 0.1 },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 24, scale: 0.97 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1] as const },
  },
};

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
      ? "Checking connection…"
      : status === "connected"
        ? "Backend connected"
        : "Backend unreachable";

  return (
    <div className="board-shell flex min-h-screen flex-col items-center justify-center px-4 pb-32 pt-8 sm:px-8">
      <motion.div
        className="mx-auto max-w-3xl text-center"
        variants={containerVariants}
        initial="hidden"
        animate="visible"
      >
        {/* Hero badge */}
        <motion.div variants={itemVariants} className="mb-6 flex justify-center">
          <div className="glass-chip glass-chip-active">
            {status === "connected" ? (
              <span className="status-orbital status-dot status-dot-good" />
            ) : status === "checking" ? (
              <span className="status-dot status-dot-warn" />
            ) : (
              <span className="status-dot status-dot-bad" />
            )}
            <span>{label}</span>
          </div>
        </motion.div>

        {/* Main headline */}
        <motion.h1
          variants={itemVariants}
          className="text-5xl font-bold tracking-[-0.04em] sm:text-7xl lg:text-8xl"
        >
          <span className="gradient-text">Your body</span>
          <br />
          <span className="text-[var(--ink)]">in signals.</span>
        </motion.h1>

        <motion.p
          variants={itemVariants}
          className="mx-auto mt-6 max-w-lg text-base leading-relaxed text-[var(--ink-soft)] sm:text-lg"
        >
          A personal health telemetry board for your Fitbit and Google Health data.
          Scan trends, find anomalies, and chat with your own history.
        </motion.p>

        {/* Quick actions */}
        <motion.div
          variants={itemVariants}
          className="mt-10 flex flex-wrap items-center justify-center gap-3"
        >
          <Link
            href="/dashboard"
            className="glass-chip glass-chip-active min-h-11 px-6 text-sm"
          >
            Open dashboard →
          </Link>
          <Link href="/chat" className="glass-chip min-h-11 px-6 text-sm">
            Ask your history ✦
          </Link>
        </motion.div>

        {/* Feature cards */}
        <motion.div
          variants={containerVariants}
          className="mt-16 grid gap-4 sm:grid-cols-3"
        >
          {[
            {
              icon: "📊",
              title: "Trends",
              desc: "Rolling 7-day and 30-day summaries across every metric.",
              color: "var(--metric-steps)",
            },
            {
              icon: "🔍",
              title: "Anomalies",
              desc: "Automatic deviation detection from your personal baseline.",
              color: "var(--metric-resting_heart_rate)",
            },
            {
              icon: "💬",
              title: "Chat",
              desc: "Ask questions grounded in your actual health records.",
              color: "var(--metric-sleep_deep_minutes)",
            },
          ].map((feature) => (
            <motion.div
              key={feature.title}
              variants={itemVariants}
              whileHover={{ y: -4, scale: 1.02 }}
              transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] as const }}
              className="glass-card spotlight-card p-5 text-left"
            >
              <div
                className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl text-lg"
                style={{
                  background: `color-mix(in srgb, ${feature.color} 15%, transparent)`,
                }}
              >
                {feature.icon}
              </div>
              <h3 className="text-sm font-semibold">{feature.title}</h3>
              <p className="mt-1 text-xs leading-relaxed text-[var(--ink-soft)]">
                {feature.desc}
              </p>
            </motion.div>
          ))}
        </motion.div>

        {/* API endpoint */}
        <motion.p
          variants={itemVariants}
          className="mt-12 font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ink-soft)] opacity-50"
        >
          {API_BASE_URL}
        </motion.p>
      </motion.div>
    </div>
  );
}
