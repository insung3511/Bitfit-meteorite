import type { ReactNode } from "react";

export type AlertTone = "error" | "info";

export type AlertProps = {
  tone?: AlertTone;
  className?: string;
  children: ReactNode;
};

const TONES: Record<AlertTone, string> = {
  error:
    "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300",
  info: "border-[var(--series-1)]/40 bg-[var(--series-1)]/10 text-[var(--series-1)]",
};

/** Bordered callout with role=alert (dashboard error/backend states). */
export function Alert({ tone = "error", className = "", children }: AlertProps) {
  return (
    <div
      role="alert"
      className={`rounded-lg border px-4 py-2 text-sm ${TONES[tone]} ${className}`}
    >
      {children}
    </div>
  );
}
