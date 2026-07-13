"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "framer-motion";
import LogoutButton from "./LogoutButton";

export default function FloatingUtilityDock() {
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

  const buttons = [
    {
      href: "/dashboard",
      label: "Dashboard",
      icon: "⌂",
      isLink: true,
    },
    {
      href: "/chat",
      label: "Assistant",
      icon: "✦",
      isLink: true,
    },
    {
      onClick: toggleLayout,
      label: "Edit layout",
      icon: "⌘",
      isLink: false,
    },
    {
      onClick: toggleTheme,
      label: "Toggle theme",
      icon: "◐",
      isLink: false,
    },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.5, duration: 0.5, ease: [0.16, 1, 0.3, 1] as const }}
      className="utility-dock"
      aria-label="Workspace utilities"
    >
      {buttons.map((button) => {
        const isActive = button.isLink && pathname.startsWith(button.href!);
        const className = `dock-button ${isActive ? "dock-button-active" : ""}`;

        if (button.isLink) {
          return (
            <motion.div
              key={button.label}
              whileHover={{ scale: 1.1 }}
              whileTap={{ scale: 0.95 }}
            >
              <Link
                href={button.href!}
                className={className}
                title={button.label}
                aria-label={button.label}
              >
                {button.icon}
              </Link>
            </motion.div>
          );
        }

        return (
          <motion.button
            key={button.label}
            type="button"
            whileHover={{ scale: 1.1 }}
            whileTap={{ scale: 0.95 }}
            onClick={button.onClick}
            className={className}
            title={button.label}
            aria-label={button.label}
          >
            {button.icon}
          </motion.button>
        );
      })}

      <span className="dock-divider" />
      <motion.div whileHover={{ scale: 1.1 }} whileTap={{ scale: 0.95 }}>
        <LogoutButton compact />
      </motion.div>
    </motion.div>
  );
}
