import type { ReactNode } from "react";

export type NavLink = { label: string; href: string };

export type AppHeaderProps = {
  brand: ReactNode;
  brandHref?: string;
  links?: NavLink[];
  right?: ReactNode;
  className?: string;
};

/**
 * Top navigation bar (from the app layout). Plain anchors so it renders
 * standalone in any runtime — no framework router dependency.
 */
export function AppHeader({
  brand,
  brandHref = "#",
  links = [],
  right,
  className = "",
}: AppHeaderProps) {
  return (
    <header className={`border-b border-black/10 dark:border-white/15 ${className}`}>
      <nav className="mx-auto flex max-w-4xl items-center gap-6 px-6 py-4">
        <a href={brandHref} className="font-semibold">
          {brand}
        </a>
        <div className="flex gap-4 text-sm">
          {links.map((link) => (
            <a key={link.href} href={link.href} className="hover:underline">
              {link.label}
            </a>
          ))}
        </div>
        {right && <div className="ml-auto">{right}</div>}
      </nav>
    </header>
  );
}
