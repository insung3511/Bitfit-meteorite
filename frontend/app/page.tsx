"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import Link from "next/link";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type Status = "checking" | "connected" | "unreachable";

/* ── Snappier staggered entrance ── */
const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.05, delayChildren: 0.05 },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 14, scale: 0.98 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { duration: 0.35, ease: [0.16, 1, 0.3, 1] as const },
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

  const statusConfig: Record<
    Status,
    { label: string; pipClass: string; color: string }
  > = {
    checking: {
      label: "CHECKING SIGNAL…",
      pipClass: "status-pip-warn",
      color: "#ffb703",
    },
    connected: {
      label: "SYSTEM ONLINE",
      pipClass: "status-pip-good",
      color: "#00f5d4",
    },
    unreachable: {
      label: "SIGNAL LOST",
      pipClass: "status-pip-danger",
      color: "#ff4d6d",
    },
  };

  const config = statusConfig[status];

  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4 pb-32 pt-8 sm:px-8">
      {/* ── Inline design-system classes (new aesthetic) ── */}
      <style>{`
        :root {
          --bg-surface: #050508;
          --bg-elevated: #0c0c12;
          --text-primary: #e8e8f0;
          --text-secondary: #6b6b80;
          --text-muted: #3d3d52;
          --border-subtle: rgba(255, 255, 255, 0.06);
          --border-default: rgba(255, 255, 255, 0.10);
          --accent-cyan: #00d4ff;
          --accent-violet: #9d4edd;
          --signal-good: #00f5d4;
          --signal-warn: #ffb703;
          --signal-danger: #ff4d6d;
          --metric-steps: #ffb703;
          --metric-resting_heart_rate: #ff4d6d;
          --metric-sleep_deep_minutes: #00d4ff;
        }

        .cmd-label {
          color: var(--text-secondary);
          font-size: 10px;
          font-weight: 700;
          letter-spacing: 0.12em;
          line-height: 1.2;
          text-transform: uppercase;
        }

        .cmd-btn {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          height: 32px;
          padding: 0 14px;
          border: 1px solid var(--border-subtle);
          border-radius: 4px;
          background: var(--bg-surface);
          color: var(--text-secondary);
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.05em;
          text-transform: uppercase;
          text-decoration: none;
          transition: all 300ms cubic-bezier(0.16, 1, 0.3, 1);
        }
        .cmd-btn:hover {
          border-color: var(--border-default);
          color: var(--text-primary);
          background: var(--bg-elevated);
        }
        .cmd-btn-primary {
          border-color: var(--accent-cyan);
          color: var(--accent-cyan);
          background: rgba(0, 212, 255, 0.08);
        }
        .cmd-btn-primary:hover {
          background: rgba(0, 212, 255, 0.12);
          box-shadow: 0 0 15px rgba(0, 212, 255, 0.10);
        }

        .status-pip {
          display: inline-block;
          width: 6px;
          height: 6px;
          border-radius: 999px;
        }
        .status-pip-good { background: var(--signal-good); box-shadow: 0 0 0 3px rgba(0, 245, 212, 0.15); }
        .status-pip-warn { background: var(--signal-warn); }
        .status-pip-danger { background: var(--signal-danger); }
        .status-pip-active { background: var(--accent-cyan); box-shadow: 0 0 0 3px rgba(0, 212, 255, 0.15); }

        @keyframes signal-ping {
          0% { transform: scale(0.8); opacity: 0.7; }
          100% { transform: scale(2); opacity: 0; }
        }
        .signal-ping {
          animation: signal-ping 1.5s cubic-bezier(0, 0, 0.2, 1) infinite;
        }

        .module-card {
          background: var(--bg-surface);
          border: 1px solid var(--border-subtle);
          border-radius: 4px;
          transition: border-color 300ms cubic-bezier(0.16, 1, 0.3, 1),
                      box-shadow 300ms cubic-bezier(0.16, 1, 0.3, 1);
        }
        .module-card:hover {
          border-color: var(--border-default);
          box-shadow: 0 0 20px rgba(0, 212, 255, 0.06), 0 0 60px rgba(0, 212, 255, 0.02);
        }

        .module-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
          gap: 12px;
        }
        @media (min-width: 640px) {
          .module-grid { grid-template-columns: repeat(3, 1fr); }
        }

        .gradient-text {
          background: linear-gradient(135deg, var(--accent-cyan), var(--accent-violet));
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
        }
      `}</style>

      <motion.div
        className="mx-auto max-w-3xl text-center"
        variants={containerVariants}
        initial="hidden"
        animate="visible"
      >
        {/* ── Status telemetry ── */}
        <motion.div
          variants={itemVariants}
          className="mb-8 flex items-center justify-center gap-3"
        >
          <span className="cmd-label">&gt; STATUS:</span>
          <span className="relative inline-block" style={{ width: 6, height: 6 }}>
            <span
              className={`status-pip ${config.pipClass}`}
              style={{ position: "absolute", inset: 0 }}
            />
            {status === "connected" && (
              <span
                className={`status-pip ${config.pipClass} signal-ping`}
                style={{ position: "absolute", inset: 0 }}
              />
            )}
          </span>
          <span className="cmd-label" style={{ color: config.color }}>
            {config.label}
          </span>
        </motion.div>

        {/* ── Hero headline ── */}
        <motion.h1
          variants={itemVariants}
          className="text-5xl font-bold tracking-[-0.04em] sm:text-7xl lg:text-8xl"
        >
          <span className="gradient-text">Your body</span>
          <br />
          <span style={{ color: "var(--text-primary)" }}>in signals.</span>
        </motion.h1>

        <motion.p
          variants={itemVariants}
          className="mx-auto mt-6 max-w-lg text-base leading-relaxed sm:text-lg"
          style={{ color: "var(--text-secondary)" }}
        >
          Welcome to your personal telemetry station. A health dashboard for
          Fitbit and Google Health data — scan trends, detect anomalies, and
          query your history.
        </motion.p>

        {/* ── Command buttons ── */}
        <motion.div
          variants={itemVariants}
          className="mt-10 flex flex-wrap items-center justify-center gap-3"
        >
          <Link href="/dashboard" className="cmd-btn cmd-btn-primary">
            OPEN DASHBOARD
          </Link>
          <Link href="/chat" className="cmd-btn">
            ASK HISTORY
          </Link>
        </motion.div>

        {/* ── Feature modules ── */}
        <motion.div variants={itemVariants} className="mt-14 mb-2 flex justify-center">
          <span className="cmd-label">&gt; MODULES:</span>
        </motion.div>

        <motion.div
          variants={containerVariants}
          className="module-grid"
        >
          {[
            {
              icon: "◈",
              title: "TRENDS",
              desc: "Rolling 7-day and 30-day summaries across every tracked metric.",
              accent: "var(--metric-steps)",
            },
            {
              icon: "◉",
              title: "ANOMALIES",
              desc: "Automatic deviation detection from your personal baseline.",
              accent: "var(--metric-resting_heart_rate)",
            },
            {
              icon: "◆",
              title: "CHAT",
              desc: "Ask questions grounded in your actual health records.",
              accent: "var(--metric-sleep_deep_minutes)",
            },
          ].map((feature) => (
            <motion.div
              key={feature.title}
              variants={itemVariants}
              whileHover={{ y: -2, scale: 1.01 }}
              transition={{
                duration: 0.2,
                ease: [0.16, 1, 0.3, 1] as const,
              }}
              className="module-card p-5 text-left"
            >
              <div className="mb-3 flex items-center gap-2">
                <span className="text-lg" style={{ color: feature.accent }}>
                  {feature.icon}
                </span>
                <h3
                  className="text-xs font-bold tracking-[0.05em]"
                  style={{ color: "var(--text-primary)" }}
                >
                  {feature.title}
                </h3>
              </div>
              <p
                className="text-xs leading-relaxed"
                style={{ color: "var(--text-secondary)" }}
              >
                {feature.desc}
              </p>
            </motion.div>
          ))}
        </motion.div>

        {/* ── API endpoint readout ── */}
        <motion.p
          variants={itemVariants}
          className="mt-12 font-mono text-[10px] uppercase tracking-[0.15em]"
          style={{ color: "var(--text-muted)" }}
        >
          <span className="cmd-label">&gt; API_ENDPOINT:</span> {API_BASE_URL}
        </motion.p>
      </motion.div>
    </div>
  );
}
