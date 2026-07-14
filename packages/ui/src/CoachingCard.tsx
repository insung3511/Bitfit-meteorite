import type { ReactNode } from "react";
import { Button } from "./Button";

export type CoachingState = "idle" | "loading" | "ready" | "error";

type CoachingCardCommonProps = {
  title?: ReactNode;
  idleText?: ReactNode;
  loadingText?: ReactNode;
  actionLabel?: string;
  onRun?: () => void;
  disclaimer?: ReactNode;
};

export type CoachingCardProps = CoachingCardCommonProps &
  (
    | { state: "idle"; text?: never; error?: never }
    | { state: "loading"; text?: never; error?: never }
    | { state: "ready"; text: string; error?: never }
    | { state: "error"; text?: never; error?: string }
  );

/** Presentational coaching card: header + action button + state-driven body. */
export function CoachingCard({
  title = "Sleep Coaching",
  state,
  text,
  error,
  idleText = "Generate a focused summary of your recent sleep, correlated with heart rate and activity.",
  loadingText = "Reviewing your last 30 days of sleep, heart rate, and activity…",
  actionLabel = "Get sleep coaching",
  onRun,
  disclaimer = "General wellness information, not medical advice.",
}: CoachingCardProps) {
  return (
    <section className="rounded-xl border border-black/10 p-4 dark:border-white/15">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-sm font-medium">{title}</h2>
        {onRun && (
          <Button
            onClick={onRun}
            disabled={state === "loading"}
            className="px-4 py-1.5"
          >
            {state === "loading" ? "Analyzing…" : actionLabel}
          </Button>
        )}
      </div>

      <div
        role={state === "error" ? "alert" : "status"}
        aria-live={state === "error" ? "assertive" : "polite"}
        aria-atomic="true"
      >
        {state === "idle" && (
          <p className="mt-3 text-sm text-black/40 dark:text-white/40">
            {idleText}
          </p>
        )}
        {state === "loading" && (
          <p className="mt-3 text-sm text-black/40 dark:text-white/40">
            {loadingText}
          </p>
        )}
        {state === "error" && (
          <p className="mt-3 text-sm text-red-700 dark:text-red-300">
            {error ?? "Coaching is unavailable right now."}
          </p>
        )}
        {state === "ready" && (
          <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed">
            {text}
          </p>
        )}
      </div>
      {disclaimer && (
        <p className="mt-3 text-xs text-black/40 dark:text-white/40">
          {disclaimer}
        </p>
      )}
    </section>
  );
}
