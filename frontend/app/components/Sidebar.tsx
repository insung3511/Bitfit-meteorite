"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "framer-motion";
import LogoutButton from "../LogoutButton";

export default function Sidebar() {
  const pathname = usePathname();
  if (pathname === "/login") return null;

  function toggleLayout() {
    window.dispatchEvent(new Event("bitfit:toggle-layout"));
  }

  function toggleTheme() {
    if (typeof document === "undefined") return;
    const root = document.documentElement;
    const current = root.getAttribute("data-theme");
    root.setAttribute("data-theme", current === "dark" ? "light" : "dark");
  }

  const navItems = [
    {
      href: "/dashboard",
      label: "Dashboard",
      icon: "⌂",
    },
    {
      href: "/chat",
      label: "Chat",
      icon: "✦",
    },
  ];

  const actionItems = [
    {
      onClick: toggleLayout,
      label: "Edit layout",
      icon: "⌘",
    },
    {
      onClick: toggleTheme,
      label: "Toggle theme",
      icon: "◐",
    },
  ];

  return (
    <motion.aside
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] as const }}
      className="nav-rail"
      aria-label="Main navigation"
    >
      {/* Top nav links */}
      <div className="flex flex-col items-center gap-1">
        {navItems.map((item) => {
          const isActive = pathname.startsWith(item.href);
          return (
            <Link
              key={item.label}
              href={item.href}
              className={`nav-rail-btn ${isActive ? "nav-rail-btn-active" : ""}`}
              title={item.label}
              aria-label={item.label}
            >
              {item.icon}
            </Link>
          );
        })}
      </div>

      {/* Action buttons */}
      <div className="flex flex-col items-center gap-1">
        {actionItems.map((item) => (
          <button
            key={item.label}
            type="button"
            onClick={item.onClick}
            className="nav-rail-btn"
            title={item.label}
            aria-label={item.label}
          >
            {item.icon}
          </button>
        ))}
      </div>

      {/* Spacer to push bottom content down */}
      <div className="flex-1" />

      {/* Bottom section: divider + logout + version label */}
      <div className="flex flex-col items-center gap-2 w-full px-2">
        <div className="w-full h-px" style={{ background: "var(--border-subtle)" }} />
        <LogoutButton compact />
        <span
          className="text-[9px] font-bold tracking-widest uppercase mt-1"
          style={{
            color: "var(--text-muted)",
            writingMode: "vertical-rl",
            transform: "rotate(180deg)",
            letterSpacing: "0.15em",
          }}
        >
          SIGNAL v1.0
        </span>
      </div>
    </motion.aside>
  );
}
