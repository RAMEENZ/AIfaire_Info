"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { format, parseISO } from "date-fns";
import { fr } from "date-fns/locale";

import { CATEGORY_CONFIG, SOURCE_LABELS, API_BASE_URL } from "@/lib/constants";
import type { StatsData } from "@/lib/api";

function BarChart({ data, colorFn }: { data: [string, number][]; colorFn?: (key: string) => string }) {
  const max = Math.max(...data.map(([, v]) => v), 1);
  return (
    <div className="space-y-2">
      {data.map(([key, count]) => {
        const pct = Math.round((count / max) * 100);
        const color = colorFn?.(key) ?? "#3B82F6";
        return (
          <div key={key} className="flex items-center gap-2 text-xs">
            <span className="w-28 shrink-0 text-gray-600 dark:text-gray-300 truncate text-right pr-1">
              {CATEGORY_CONFIG[key as keyof typeof CATEGORY_CONFIG]?.label ?? SOURCE_LABELS[key] ?? key}
            </span>
            <div className="flex-1 bg-gray-100 dark:bg-gray-700 rounded-full h-4 overflow-hidden">
              <div
                className="h-full rounded-full flex items-center justify-end pr-1.5 transition-all duration-500"
                style={{ width: `${Math.max(pct, 2)}%`, backgroundColor: color }}
              >
                <span className="text-white text-[9px] font-semibold whitespace-nowrap">
                  {count}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function StatsPage() {
  const [stats, setStats] = useState<StatsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE_URL}/stats`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<StatsData>;
      })
      .then((data) => {
        setStats(data);
        setLoading(false);
      })
      .catch((e: Error) => {
        setError(e.message);
        setLoading(false);
      });
  }, []);

  const catEntries = stats
    ? (Object.entries(stats.by_categorie) as [string, number][]).sort((a, b) => b[1] - a[1])
    : [];

  const sourceEntries = stats
    ? (Object.entries(stats.by_source) as [string, number][]).sort((a, b) => b[1] - a[1]).slice(0, 15)
    : [];

  function fmtDate(iso: string | null) {
    if (!iso) return "—";
    try {
      return format(parseISO(iso), "d MMM yyyy HH:mm", { locale: fr });
    } catch {
      return iso;
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <header className="flex items-center gap-4 px-4 py-3 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 shadow-sm">
        <Link
          href="/"
          className="flex items-center gap-1 text-xs text-gray-500 hover:text-blue-600 transition-colors"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          Retour
        </Link>
        <span className="text-blue-700 font-black text-lg tracking-tight">FAIRE</span>
        <h1 className="text-sm font-semibold text-gray-700 dark:text-gray-200">Statistiques</h1>
      </header>

      <main className="max-w-3xl mx-auto px-4 py-8 space-y-8">
        {loading && (
          <div className="text-center py-16 text-gray-400">Chargement…</div>
        )}

        {error && (
          <div className="text-center py-16 text-red-500">
            <p className="font-medium mb-1">Erreur de chargement</p>
            <p className="text-sm text-gray-400">{error}</p>
          </div>
        )}

        {stats && (
          <>
            {/* Summary cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {[
                { label: "Événements total", value: stats.total_events.toLocaleString("fr") },
                { label: "Localisés", value: stats.localized.toLocaleString("fr") },
                { label: "Nationaux", value: stats.national.toLocaleString("fr") },
                {
                  label: "Ratio localisé",
                  value:
                    stats.total_events > 0
                      ? `${Math.round((stats.localized / stats.total_events) * 100)} %`
                      : "—",
                },
              ].map(({ label, value }) => (
                <div
                  key={label}
                  className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 text-center shadow-sm"
                >
                  <p className="text-2xl font-black text-blue-700 dark:text-blue-400">{value}</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{label}</p>
                </div>
              ))}
            </div>

            {/* Date range */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 shadow-sm text-sm text-gray-600 dark:text-gray-300">
              <p>
                Premier événement :{" "}
                <span className="font-medium text-gray-800 dark:text-gray-100">{fmtDate(stats.oldest_event)}</span>
              </p>
              <p className="mt-1">
                Dernier événement :{" "}
                <span className="font-medium text-gray-800 dark:text-gray-100">{fmtDate(stats.newest_event)}</span>
              </p>
            </div>

            {/* By category */}
            <section className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
              <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-4">Par catégorie</h2>
              <BarChart
                data={catEntries}
                colorFn={(k) => CATEGORY_CONFIG[k as keyof typeof CATEGORY_CONFIG]?.color ?? "#6B7280"}
              />
            </section>

            {/* By source */}
            <section className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
              <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-4">
                Par source <span className="font-normal text-gray-400">(top 15)</span>
              </h2>
              <BarChart data={sourceEntries} />
            </section>
          </>
        )}
      </main>
    </div>
  );
}
