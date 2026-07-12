import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "solid" | "outline" | "ghost";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
};

const VARIANTS: Record<ButtonVariant, string> = {
  solid:
    "rounded-lg bg-black px-4 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-white dark:text-black",
  outline:
    "rounded-md border border-black/15 px-3 py-1.5 text-xs font-medium hover:bg-black/5 disabled:opacity-40 dark:border-white/20 dark:hover:bg-white/10",
  ghost:
    "rounded-md px-2 py-1 text-xs text-black/60 hover:bg-black/5 hover:text-black disabled:opacity-40 dark:text-white/60 dark:hover:bg-white/10 dark:hover:text-white",
};

/** App button in its three real variants: solid (primary), outline, ghost. */
export function Button({
  variant = "solid",
  className = "",
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button type={type} className={`${VARIANTS[variant]} ${className}`} {...props} />
  );
}
