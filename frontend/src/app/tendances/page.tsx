"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { format, parseISO } from "date-fns";
import { fr } from "date-fns/locale";

import { CATEGORY_CONFIG, API_BASE_URL, readableTextColor } from "@/lib/constants";
import { DEPT_CODE_TO_NAME } from "@/lib/departments";
import Wordmark from "@/components/Wordmark";

// Ligne brute de /api/stats/history : agrégat jour × catégorie × département
// (département "" = national/non localisé). Alimenté chaque nuit avant la
// purge — contrairement aux événements bruts, cet historique ne s'efface pas.
interface HistoryRow {
  jour: string;
  categorie: string;
  departement: string;
  count: number;
}

const PERIODS = [
  { days: 30, label: "30 jours" },
  { days: 90, label: "90 jours" },
  { days: 365, label: "1 an" },
];

function catColor(cat: string): string {
  return CATEGORY_CONFIG[cat as keyof typeof CATEGORY_CONFIG]?.color ?? "#6B7280";
}

function catLabel(cat: string): string {
  return CATEGORY_CONFIG[cat as keyof typeof CATEGORY_CONFIG]?.label ?? cat;
}

/** Barres quotidiennes empilées par catégorie — SVG maison, zéro dépendance. */
function StackedDailyChart({ rows }: { rows: HistoryRow[] }) {
  const { days, byDay, maxTotal } = useMemo(() => {
    const byDay = new Map<string, Map<string, number>>();
    for (const r of rows) {
      const cats = byDay.get(r.jour) ?? new Map<string, number>();
      cats.set(r.categorie, (cats.get(r.categorie) ?? 0) + r.count);
      byDay.set(r.jour, cats);
    }
    const days = Array.from(byDay.keys()).sort();
    const maxTotal = Math.max(
      1,
      ...days.map((d) => Array.from(byDay.get(d)!.values()).reduce((a, b) => a + b, 0))
    );
    return { days, byDay, maxTotal };
  }, [rows]);

  if (days.length === 0) {
    return (
      <p className="text-xs text-gray-500 dark:text-gray-400 py-8 text-center">
        Pas encore d&apos;historique — les agrégats se remplissent chaque nuit à 3h00.
      </p>
    );
  }

  const BAR_W = 10;
  const GAP = 2;
  const H = 160;
  const width = days.length * (BAR_W + GAP);

  return (
    <div>
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${width} ${H}`}
          className="h-40"
          style={{ minWidth: "100%", width: Math.max(width, 300) }}
          role="img"
          aria-label="Événements par jour, empilés par catégorie"
        >
          {days.map((day, i) => {
            const cats = Array.from(byDay.get(day)!.entries()).sort((a, b) => b[1] - a[1]);
            const total = cats.reduce((a, [, v]) => a + v, 0);
            let y = H;
            return (
              <g key={day}>
                <title>{`${format(parseISO(day), "d MMM yyyy", { locale: fr })} — ${total} événement${total > 1 ? "s" : ""}`}</title>
                {cats.map(([cat, count]) => {
                  const h = (count / maxTotal) * (H - 4);
                  y -= h;
                  return (
                    <rect
                      key={cat}
                      x={i * (BAR_W + GAP)}
                      y={y}
                      width={BAR_W}
                      height={Math.max(h, 0.5)}
                      fill={catColor(cat)}
                      rx={1}
                    />
                  );
                })}
              </g>
            );
          })}
        </svg>
      </div>
      <div className="flex justify-between text-[10px] text-gray-500 dark:text-gray-400 mt-1">
        <span>{format(parseISO(days[0]), "d MMM yyyy", { locale: fr })}</span>
        <span>{format(parseISO(days[days.length - 1]), "d MMM yyyy", { locale: fr })}</span>
      </div>
    </div>
  );
}

function HorizontalBars({
  data,
  colorFn,
}: {
  data: { key: string; label: string; count: number }[];
  colorFn?: (key: string) => string;
}) {
  const max = Math.max(...data.map((d) => d.count), 1);
  return (
    <div className="space-y-2">
      {data.map(({ key, label, count }) => (
        <div key={key} className="flex items-center gap-2 text-xs">
          <span className="w-36 shrink-0 text-gray-600 dark:text-gray-300 truncate text-right pr-1">
            {label}
          </span>
          <div className="flex-1 bg-gray-100 dark:bg-gray-700 rounded-full h-4 overflow-hidden">
            <div
              className="h-full rounded-full flex items-center justify-end pr-1.5 transition-all duration-500"
              style={{
                width: `${Math.max(Math.round((count / max) * 100), 2)}%`,
                backgroundColor: colorFn?.(key) ?? "#3B82F6",
              }}
            >
              <span className="text-[9px] font-semibold whitespace-nowrap" style={{ color: readableTextColor(colorFn?.(key) ?? "#3B82F6") }}>{count}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function TendancesPage() {
  const [days, setDays] = useState(90);
  const [rows, setRows] = useState<HistoryRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRows(null);
    setError(null);
    fetch(`${API_BASE_URL}/stats/history?days=${days}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<{ stats: HistoryRow[] }>;
      })
      .then((data) => setRows(data.stats))
      .catch((e: Error) => setError(e.message));
  }, [days]);

  const totalByCat = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of rows ?? []) m.set(r.categorie, (m.get(r.categorie) ?? 0) + r.count);
    return Array.from(m.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([key, count]) => ({ key, label: catLabel(key), count }));
  }, [rows]);

  const topDepts = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of rows ?? []) {
      if (!r.departement) continue; // "" = national/non localisé
      m.set(r.departement, (m.get(r.departement) ?? 0) + r.count);
    }
    return Array.from(m.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 15)
      .map(([key, count]) => ({
        key,
        label: `${DEPT_CODE_TO_NAME[key] ?? "?"} (${key})`,
        count,
      }));
  }, [rows]);

  const total = useMemo(() => (rows ?? []).reduce((a, r) => a + r.count, 0), [rows]);
  const dayCount = useMemo(() => new Set((rows ?? []).map((r) => r.jour)).size, [rows]);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <header className="flex items-center gap-4 px-4 py-3 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 shadow-xs">
        <Link
          href="/"
          className="flex items-center gap-1 text-xs text-gray-500 hover:text-blue-600 transition-colors"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          Retour
        </Link>
        <Wordmark taille="sm" avecInfo={false} />
        <h1 className="text-sm font-semibold text-gray-700 dark:text-gray-200">Tendances</h1>
        <Link href="/stats" className="ml-auto text-xs text-gray-500 hover:text-blue-600 transition-colors">
          Statistiques →
        </Link>
      </header>

      <main className="max-w-3xl mx-auto px-4 py-8 space-y-8">
        {/* Sélecteur de période */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500 dark:text-gray-400">Période :</span>
          {PERIODS.map((p) => (
            <button
              key={p.days}
              onClick={() => setDays(p.days)}
              className={`text-xs px-2.5 py-1 rounded border transition-colors ${
                days === p.days
                  ? "bg-gray-700 dark:bg-gray-600 text-white border-gray-700 dark:border-gray-500"
                  : "bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 border-gray-300 dark:border-gray-600 hover:border-gray-500"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>

        {error && (
          <div className="text-center py-16 text-red-500">
            <p className="font-medium mb-1">Erreur de chargement</p>
            <p className="text-sm text-gray-500 dark:text-gray-400">{error}</p>
          </div>
        )}

        {!rows && !error && <div className="text-center py-16 text-gray-500 dark:text-gray-400">Chargement…</div>}

        {rows && (
          <>
            <div className="grid grid-cols-2 gap-4">
              {[
                { label: "Événements sur la période", value: total.toLocaleString("fr") },
                { label: "Jours d'historique", value: dayCount.toLocaleString("fr") },
              ].map(({ label, value }) => (
                <div
                  key={label}
                  className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 text-center shadow-xs"
                >
                  <p className="text-2xl font-black text-blue-700 dark:text-blue-400">{value}</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{label}</p>
                </div>
              ))}
            </div>

            <section className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-xs">
              <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-4">
                Événements par jour
              </h2>
              <StackedDailyChart rows={rows} />
              {/* Légende */}
              <div className="flex flex-wrap gap-x-3 gap-y-1 mt-3">
                {totalByCat.map(({ key, label }) => (
                  <span key={key} className="flex items-center gap-1 text-[10px] text-gray-500 dark:text-gray-400">
                    <span className="w-2 h-2 rounded-xs inline-block" style={{ backgroundColor: catColor(key) }} />
                    {label}
                  </span>
                ))}
              </div>
            </section>

            <section className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-xs">
              <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-4">
                Par catégorie <span className="font-normal text-gray-500 dark:text-gray-400">(cumul sur la période)</span>
              </h2>
              <HorizontalBars data={totalByCat} colorFn={catColor} />
            </section>

            <section className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-xs">
              <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-4">
                Départements les plus actifs <span className="font-normal text-gray-500 dark:text-gray-400">(top 15)</span>
              </h2>
              {topDepts.length > 0 ? (
                <HorizontalBars data={topDepts} />
              ) : (
                <p className="text-xs text-gray-500 dark:text-gray-400">Pas encore de données localisées.</p>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
