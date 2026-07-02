"use client";

import { useEffect, useState } from "react";
import { ToastItem, subscribeToToasts } from "@/lib/toast";

const KIND_STYLE: Record<ToastItem["kind"], string> = {
  success: "bg-green-600 text-white",
  error: "bg-red-600 text-white",
  info: "bg-gray-800 text-white dark:bg-gray-700",
};

const AUTO_DISMISS_MS = 3000;

/** Affiche les toasts émis via toast() — empilés en bas au centre,
 * auto-effacés, annoncés aux lecteurs d'écran (aria-live). */
export default function Toaster() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  useEffect(() => {
    return subscribeToToasts((t) => {
      setToasts((prev) => [...prev, t]);
      setTimeout(() => {
        setToasts((prev) => prev.filter((x) => x.id !== t.id));
      }, AUTO_DISMISS_MS);
    });
  }, []);

  return (
    <div
      aria-live="polite"
      aria-atomic="false"
      className="fixed bottom-12 left-1/2 -translate-x-1/2 z-[2000] flex flex-col items-center gap-2 pointer-events-none"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          className={`px-3 py-1.5 rounded-lg shadow-lg text-xs font-medium animate-toast-in ${KIND_STYLE[t.kind]}`}
        >
          {t.message}
        </div>
      ))}
    </div>
  );
}
