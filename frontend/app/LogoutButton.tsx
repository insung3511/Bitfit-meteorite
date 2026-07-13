"use client";

import { usePathname, useRouter } from "next/navigation";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function LogoutButton({ compact = false }: { compact?: boolean }) {
  const pathname = usePathname();
  const router = useRouter();

  if (pathname === "/login") return null;

  async function handleLogout() {
    try {
      await fetch(`${API_BASE_URL}/session/logout`, {
        method: "POST",
        credentials: "include",
      });
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <button
      type="button"
      onClick={handleLogout}
      className={compact ? "dock-button" : "glass-chip"}
      title="Log out"
      aria-label="Log out"
    >
      {compact ? "↗" : "Log out"}
    </button>
  );
}
