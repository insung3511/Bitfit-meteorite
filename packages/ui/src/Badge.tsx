import type { ReactNode } from "react";

export type BadgeVariant = "pill" | "bullet";

export type BadgeProps = {
  /** CSS color or var ref, e.g. "var(--series-1)". Defaults to series-1. */
  color?: string;
  variant?: BadgeVariant;
  className?: string;
  children: ReactNode;
};

/**
 * Color-coded label — Swiss route-bullet / Zürich-card energy.
 * `pill` is a rounded filled tag; `bullet` is a compact circular marker.
 */
export function Badge({
  color = "var(--series-1)",
  variant = "pill",
  className = "",
  children,
}: BadgeProps) {
  if (variant === "bullet") {
    return (
      <span
        className={`inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-xs font-bold text-white ${className}`}
        style={{ backgroundColor: color }}
      >
        {children}
      </span>
    );
  }
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-bold uppercase tracking-wide text-white ${className}`}
      style={{ backgroundColor: color }}
    >
      {children}
    </span>
  );
}
