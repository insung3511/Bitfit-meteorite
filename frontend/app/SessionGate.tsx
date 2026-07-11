"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type SessionStatus = "authenticated" | "unauthenticated" | "unavailable";

type SessionCheck = {
  pathname: string;
  status: SessionStatus;
};

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
  const [sessionCheck, setSessionCheck] = useState<SessionCheck | null>(null);

  useEffect(() => {
    let cancelled = false;

    if (pathname === "/login") {
      return;
    }

    fetch(`${API_BASE_URL}/session/me`, { credentials: "include" })
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`Session check returned ${res.status}`);
        }
        return res.json() as Promise<{ authenticated?: unknown }>;
      })
      .then((data: { authenticated?: unknown }) => {
        if (cancelled) return;
        const authenticated = data.authenticated === true;
        setSessionCheck({
          pathname,
          status: authenticated ? "authenticated" : "unauthenticated",
        });
        if (!authenticated) {
          router.replace("/login");
        }
      })
      .catch(() => {
        if (cancelled) return;
        // A failed check is not proof that the visitor is unauthenticated.
        // Render the page so its existing unavailable state can be shown.
        setSessionCheck({ pathname, status: "unavailable" });
      });

    return () => {
      cancelled = true;
    };
  }, [pathname, router]);

  if (pathname === "/login") {
    return <>{children}</>;
  }

  const status =
    sessionCheck?.pathname === pathname ? sessionCheck.status : undefined;

  if (status === undefined) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-sm text-black/40 dark:text-white/40">
        Loading…
      </div>
    );
  }

  if (status === "unauthenticated") {
    // Redirect is already in flight; render nothing to avoid a flash of
    // protected content.
    return null;
  }

  return <>{children}</>;
}
