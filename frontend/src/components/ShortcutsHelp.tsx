"use client";

import { useEffect, useState } from "react";

const SHORTCUTS: { keys: string; action: string }[] = [
  { keys: "/", action: "Rechercher dans le fil" },
  { keys: "↑ / ↓", action: "Naviguer entre les événements" },
  { keys: "Échap", action: "Effacer la recherche / fermer" },
  { keys: "?", action: "Afficher cette aide" },
];

/** Panneau d'aide des raccourcis clavier — ouvert via la touche « ? » ou le
 * bouton d'aide du header. Rendait les raccourcis existants découvrables. */
export default function ShortcutsHelp() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const inInput =
        document.activeElement?.tagName === "INPUT" ||
        document.activeElement?.tagName === "TEXTAREA" ||
        document.activeElement?.tagName === "SELECT";
      if (e.key === "?" && !inInput) {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        aria-label="Aide et raccourcis clavier"
        title="Raccourcis clavier (?)"
        className="hidden md:flex items-center justify-center w-7 h-7 rounded border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors text-xs font-semibold"
      >
        ?
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[1500] flex items-center justify-center bg-black/40 p-4"
          onClick={() => setOpen(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Raccourcis clavier"
            className="bg-white dark:bg-gray-800 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700 p-5 w-full max-w-xs"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-gray-800 dark:text-gray-100">
                Raccourcis clavier
              </h2>
              <button
                onClick={() => setOpen(false)}
                aria-label="Fermer"
                className="text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <ul className="space-y-2">
              {SHORTCUTS.map((s) => (
                <li key={s.keys} className="flex items-center justify-between gap-3 text-xs">
                  <span className="text-gray-600 dark:text-gray-300">{s.action}</span>
                  <kbd className="px-1.5 py-0.5 rounded border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-900/40 text-gray-700 dark:text-gray-200 font-mono text-[10px] whitespace-nowrap">
                    {s.keys}
                  </kbd>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </>
  );
}
