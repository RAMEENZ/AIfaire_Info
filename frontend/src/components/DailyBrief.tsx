"use client";
import { useState } from "react";
import useSWR from "swr";
import { API_BASE_URL } from "@/lib/constants";

interface BriefData {
  date: string;
  content: string;
  event_count: number;
  generated_at: string;
  brief?: null;
  message?: string;
}

const fetcher = (url: string) => fetch(url).then(r => r.json());

export default function DailyBrief() {
  const [open, setOpen] = useState(false);
  const { data, isLoading } = useSWR<BriefData>(`${API_BASE_URL}/brief`, fetcher, {
    refreshInterval: 3600_000, // 1h
    revalidateOnFocus: false,
  });

  const hasBrief = data && !data.message && data.content;

  return (
    <div className="border-b border-gray-100">
      <button
        onClick={() => setOpen(v => !v)}
        className={`w-full flex items-center gap-2 px-3 py-2 text-left text-xs font-medium hover:bg-gray-50 transition-colors ${hasBrief ? "text-blue-700" : "text-gray-400"}`}
        disabled={!hasBrief && !isLoading}
      >
        <span className="text-base">📰</span>
        <span className="flex-1">
          {isLoading
            ? "Chargement du brief..."
            : hasBrief
            ? `Brief du ${new Date(data.date).toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}`
            : "Aucun brief disponible"}
        </span>
        {hasBrief && <span className="text-gray-400">{open ? "▲" : "▼"}</span>}
      </button>
      {open && hasBrief && (
        <div className="px-3 pb-3 text-xs text-gray-700 leading-relaxed whitespace-pre-line bg-blue-50 border-t border-blue-100">
          <p className="mt-2">{data.content}</p>
          <p className="mt-2 text-[10px] text-gray-400">
            Généré à {new Date(data.generated_at).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })} · {data.event_count} événements analysés
          </p>
        </div>
      )}
    </div>
  );
}
