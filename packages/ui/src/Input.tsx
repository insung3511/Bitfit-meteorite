import type { InputHTMLAttributes } from "react";

export type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  invalid?: boolean;
};

/** Bordered transparent text field (from the login form). */
export function Input({ invalid = false, className = "", ...props }: InputProps) {
  return (
    <input
      aria-invalid={invalid || undefined}
      className={`rounded-lg border bg-transparent px-4 py-2 text-sm outline-none placeholder:text-black/40 disabled:opacity-60 dark:placeholder:text-white/40 ${
        invalid
          ? "border-red-500/60 focus:border-red-500"
          : "border-black/10 focus:border-black/30 dark:border-white/15 dark:focus:border-white/30"
      } ${className}`}
      {...props}
    />
  );
}
