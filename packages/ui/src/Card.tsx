import type { ReactNode } from "react";

export type CardProps = {
  title?: ReactNode;
  subtitle?: ReactNode;
  /** Adds the selected border/shadow treatment. */
  selected?: boolean;
  onClick?: () => void;
  className?: string;
  children?: ReactNode;
};

/**
 * Surface container used across the app — rounded, bordered, on the viz surface.
 * `selected` mirrors the WorkspacePanel active state.
 */
export function Card({
  title,
  subtitle,
  selected = false,
  onClick,
  className = "",
  children,
}: CardProps) {
  return (
    <div
      onClick={onClick}
      onKeyDown={
        onClick
          ? (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      className={`rounded-xl border bg-[var(--viz-surface)] p-4 transition ${
        selected
          ? "border-black/50 shadow-sm dark:border-white/60"
          : "border-black/10 dark:border-white/15"
      } ${onClick ? "cursor-pointer" : ""} ${className}`}
    >
      {(title || subtitle) && (
        <div className="mb-3">
          {title && <h3 className="text-sm font-medium">{title}</h3>}
          {subtitle && (
            <p className="mt-0.5 text-xs text-black/45 dark:text-white/45">
              {subtitle}
            </p>
          )}
        </div>
      )}
      {children}
    </div>
  );
}
