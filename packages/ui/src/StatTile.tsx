import type { ReactNode } from "react";

export type StatTileTone = "light" | "dark";

export type StatTileProps = {
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
  caption?: ReactNode;
  /** Accent color for the value, e.g. "var(--series-1)". */
  accent?: string;
  /** Slot for a sparkline / mini-chart under the value. */
  chart?: ReactNode;
  tone?: StatTileTone;
  className?: string;
};

/**
 * Compact metric tile — big number + label + unit, optional mini-chart.
 * Reference lean: Apple Watch / Velovories widgets. `dark` tone gives the
 * black-canvas widget look; `light` sits on the app surface.
 */
export function StatTile({
  label,
  value,
  unit,
  caption,
  accent,
  chart,
  tone = "light",
  className = "",
}: StatTileProps) {
  const toneClasses =
    tone === "dark"
      ? "bg-neutral-950 text-white"
      : "border border-black/10 bg-[var(--viz-surface)] dark:border-white/15";
  const labelClasses =
    tone === "dark" ? "text-white/60" : "text-black/50 dark:text-white/50";
  const captionClasses =
    tone === "dark" ? "text-white/45" : "text-black/45 dark:text-white/45";

  return (
    <div className={`rounded-xl p-4 ${toneClasses} ${className}`}>
      <div className={`text-xs font-medium uppercase tracking-wide ${labelClasses}`}>
        {label}
      </div>
      <div className="mt-2 flex items-baseline gap-1">
        <span
          className="stat-number text-3xl"
          style={accent ? { color: accent } : undefined}
        >
          {value}
        </span>
        {unit && (
          <span className={`text-sm font-medium ${labelClasses}`}>{unit}</span>
        )}
      </div>
      {chart && <div className="mt-3">{chart}</div>}
      {caption && <div className={`mt-2 text-xs ${captionClasses}`}>{caption}</div>}
    </div>
  );
}
