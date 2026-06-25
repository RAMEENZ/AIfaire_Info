"use client";

import { useState } from "react";
import useSWR from "swr";
import { API_BASE_URL } from "@/lib/constants";
import { Categorie } from "@/lib/types";

interface TimelineBucket {
  time: string;
  count: number;
  max_gravite: number;
}

interface TimelineBarProps {
  categories: Categorie[];
  graviteMin: number;
  historyDate: Date | null;
  onHistoryDateChange: (date: Date | null) => void;
}

const fetcher = (url: string) => fetch(url).then((r) => r.json());

const GRAVITE_COLORS: Record<number, string> = {
  0: "#93C5FD",
  1: "#F59E0B",
  2: "#F97316",
  3: "#EF4444",
};

export default function TimelineBar({
  categories,
  graviteMin,
  historyDate,
  onHistoryDateChange,
}: TimelineBarProps) {
  const [mode, setMode] = useState<"live" | "history">(
    historyDate ? "history" : "live"
  );
  const [inputDate, setInputDate] = useState(
    historyDate ? historyDate.toISOString().slice(0, 10) : ""
  );

  const params = new URLSearchParams({ bucket: "day" });
  categories.forEach((c) => params.append("categories", c));
  if (graviteMin > 0) params.set("gravite_min", String(graviteMin));

  const { data } = useSWR<{ buckets: TimelineBucket[] }>(
    mode === "live" ? `${API_BASE_URL}/events/timeline?${params}` : null,
    fetcher,
    { refreshInterval: 3_600_000, revalidateOnFocus: false }
  );

  const buckets = data?.buckets ?? [];
  const maxCount = Math.max(...buckets.map((b) => b.count), 1);
  const today = new Date().toISOString().slice(0, 10);

  function switchToLive() {
    setMode("live");
    setInputDate("");
    onHistoryDateChange(null);
  }

  function switchToHistory(dateStr?: string) {
    setMode("history");
    if (dateStr) {
      setInputDate(dateStr);
      onHistoryDateChange(new Date(dateStr + "T00:00:00Z"));
    }
  }

  return (
    <div className="border-b border-gray-100 dark:border-gray-700 px-3 pt-2 pb-1.5 bg-white dark:bg-gray-800 flex-shrink-0">
      <div className="flex items-center gap-2 mb-1.5">
        <button
          onClick={switchToLive}
          className={`text-[10px] font-semibold px-2 py-0.5 rounded transition-colors ${
            mode === "live"
              ? "bg-green-100 text-green-700"
              : "text-gray-400 hover:text-gray-600 dark:text-gray-500"
          }`}
        >
          ● Live
        </button>
        <button
          onClick={() => switchToHistory(inputDate || today)}
          className={`text-[10px] font-semibold px-2 py-0.5 rounded transition-colors ${
            mode === "history"
              ? "bg-blue-100 text-blue-700"
              : "text-gray-400 hover:text-gray-600 dark:text-gray-500"
          }`}
        >
          ⏪ Historique
        </button>

        {mode === "history" && (
          <>
            <input
              type="date"
              value={inputDate}
              max={today}
              onChange={(e) => {
                setInputDate(e.target.value);
                if (e.target.value) {
                  onHistoryDateChange(new Date(e.target.value + "T00:00:00Z"));
                }
              }}
              className="text-[10px] px-2 py-0.5 border border-gray-200 dark:border-gray-600 rounded focus:outline-none focus:border-blue-400 dark:bg-gray-700 dark:text-gray-200"
            />
            <span className="text-[10px] text-blue-600 font-medium">
              — 48h
            </span>
          </>
        )}
      </div>

      {mode === "live" && buckets.length > 0 && (
        <div className="flex items-end gap-px" style={{ height: 28 }}>
          {buckets.slice(-30).map((b) => {
            const pct = b.count / maxCount;
            const height = Math.max(2, Math.round(pct * 28));
            const color = GRAVITE_COLORS[Math.min(b.max_gravite, 3)] ?? "#93C5FD";
            const dateLabel = new Date(b.time).toLocaleDateString("fr-FR", {
              day: "numeric",
              month: "short",
            });
            return (
              <button
                key={b.time}
                onClick={() => switchToHistory(b.time.slice(0, 10))}
                style={{ height, backgroundColor: color, flexGrow: 1, minWidth: 3 }}
                className="rounded-sm opacity-60 hover:opacity-100 transition-opacity"
                title={`${dateLabel} : ${b.count} événement${b.count !== 1 ? "s" : ""}`}
              />
            );
          })}
        </div>
      )}

      {mode === "live" && buckets.length === 0 && (
        <div style={{ height: 28 }} className="flex items-center">
          <span className="text-[10px] text-gray-300 dark:text-gray-600 italic">
            Chargement de l'historique…
          </span>
        </div>
      )}
    </div>
  );
}
