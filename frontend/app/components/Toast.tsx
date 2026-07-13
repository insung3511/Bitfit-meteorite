"use client";

import { useEffect, useState, type ReactNode } from "react";

interface Toast {
  id: string;
  message: ReactNode;
  type?: "info" | "success" | "warning" | "error";
}

let toastListeners: ((toasts: Toast[]) => void)[] = [];
let toasts: Toast[] = [];

function notify() {
  toastListeners.forEach((listener) => listener([...toasts]));
}

export function showToast(
  message: ReactNode,
  type: Toast["type"] = "info",
  duration = 3000
) {
  const id = `${Date.now()}-${Math.random()}`;
  toasts = [...toasts, { id, message, type }];
  notify();
  setTimeout(() => {
    toasts = toasts.filter((t) => t.id !== id);
    notify();
  }, duration);
}

export default function ToastContainer() {
  const [activeToasts, setActiveToasts] = useState<Toast[]>([]);

  useEffect(() => {
    toastListeners.push(setActiveToasts);
    return () => {
      toastListeners = toastListeners.filter((l) => l !== setActiveToasts);
    };
  }, []);

  const typeStyles = {
    info: "border-l-[var(--signal-active)]",
    success: "border-l-[var(--signal-good)]",
    warning: "border-l-[var(--signal-warning)]",
    error: "border-l-[var(--signal-danger)]",
  };

  return (
    <div className="fixed bottom-24 left-1/2 z-[60] flex -translate-x-1/2 flex-col gap-2">
      {activeToasts.map((toast) => (
        <div
          key={toast.id}
          className={`glass-card-strong toast-enter min-w-[240px] border-l-4 px-4 py-3 text-sm ${typeStyles[toast.type ?? "info"]}`}
        >
          {toast.message}
        </div>
      ))}
    </div>
  );
}
