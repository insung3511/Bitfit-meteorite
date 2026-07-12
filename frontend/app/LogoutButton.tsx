"use client";

import { usePathname, useRouter } from "next/navigation";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function LogoutButton() {
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
      className="ml-auto rounded border border-white/20 px-3 py-2 text-[10px] font-bold uppercase tracking-[0.1em] text-white/65 hover:bg-white/10 hover:text-white"
    >
      Log out
    </button>
  );
}
