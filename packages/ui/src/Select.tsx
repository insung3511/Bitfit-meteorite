import type { SelectHTMLAttributes, ReactNode } from "react";

export type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & {
  label?: ReactNode;
};

/** Bordered transparent select, optionally with a stacked label (workspace controls). */
export function Select({ label, className = "", children, ...props }: SelectProps) {
  const select = (
    <select
      className={`rounded-md border border-black/10 bg-transparent px-2 py-1 text-xs text-inherit dark:border-white/15 ${className}`}
      {...props}
    >
      {children}
    </select>
  );
  if (!label) return select;
  return (
    <label className="flex flex-col gap-1 text-black/50 dark:text-white/50">
      {label}
      {select}
    </label>
  );
}
