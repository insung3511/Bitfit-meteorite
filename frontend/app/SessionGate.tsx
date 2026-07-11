"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/**
 * Gates every page except /login behind the backend session cookie. Checks
 * `/session/me` on mount and on every navigation; redirects to /login if the
 * visitor isn't authenticated. This is a single-user personal app with one
 * shared password, so there's no user object to load — just a boolean.
 */
export default function SessionGate({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [checked, setChecked] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);

  useEffect(() => {
    let cancelled = false;

    if (pathname === "/login") {
      setChecked(true);
      return;
    }

    fetch(`${API_BASE_URL}/session/me`, { credentials: "include" })
      .then((res) => (res.ok ? res.json() : { authenticated: false }))
      .then((data: { authenticated: boolean }) => {
        if (cancelled) return;
        setAuthenticated(Boolean(data.authenticated));
        setChecked(true);
        if (!data.authenticated) {
          router.replace("/login");
        }
      })
      .catch(() => {
        if (cancelled) return;
        // Backend unreachable — let the page render; its own fetches will
        // surface the "backend unreachable" state rather than looping here.
        setChecked(true);
        setAuthenticated(false);
      });

    return () => {
      cancelled = true;
    };
  }, [pathname, router]);

  if (pathname === "/login") {
    return <>{children}</>;
  }

  if (!checked) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-sm text-black/40 dark:text-white/40">
        Loading…
      </div>
    );
  }

  if (!authenticated) {
    // Redirect is already in flight; render nothing to avoid a flash of
    // protected content.
    return null;
  }

  return <>{children}</>;
}
