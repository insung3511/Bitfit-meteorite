import type { ReactNode } from "react";
import { Button } from "./Button";

export type CoachingState = "idle" | "loading" | "ready" | "error";

export type CoachingCardProps = {
  title?: ReactNode;
  state: CoachingState;
  text?: string;
  error?: string;
  idleText?: ReactNode;
  loadingText?: ReactNode;
  actionLabel?: string;
  onRun?: () => void;
  disclaimer?: ReactNode;
};

const noop = () => {};

/** Presentational coaching card: header + action button + state-driven body. */
export function CoachingCard({
  title = "Sleep Coaching",
  state,
  text,
  error,
  idleText = "Generate a focused summary of your recent sleep, correlated with heart rate and activity.",
  loadingText = "Reviewing your last 30 days of sleep, heart rate, and activity…",
  actionLabel = "Get sleep coaching",
  onRun = noop,
  disclaimer = "General wellness information, not medical advice.",
}: CoachingCardProps) {
  return (
    <section className="rounded-xl border border-black/10 p-4 dark:border-white/15">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-sm font-medium">{title}</h2>
        <Button onClick={onRun} disabled={state === "loading"} className="px-4 py-1.5">
          {state === "loading" ? "Analyzing…" : actionLabel}
        </Button>
      </div>

      {state === "idle" && (
        <p className="mt-3 text-sm text-black/40 dark:text-white/40">{idleText}</p>
      )}
      {state === "loading" && (
        <p className="mt-3 text-sm text-black/40 dark:text-white/40">{loadingText}</p>
      )}
      {state === "error" && (
        <p className="mt-3 text-sm text-red-700 dark:text-red-300">
          {error ?? "Coaching is unavailable right now."}
        </p>
      )}
      {state === "ready" && (
        <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed">{text}</p>
      )}
      {disclaimer && (
        <p className="mt-3 text-xs text-black/40 dark:text-white/40">{disclaimer}</p>
      )}
    </section>
  );
}
