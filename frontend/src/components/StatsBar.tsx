"use client";

import { parseISO, format, formatDistanceToNow } from "date-fns";
import { fr } from "date-fns/locale";

import { CATEGORY_CONFIG } from "@/lib/constants";
import { Categorie, Event } from "@/lib/types";

interface StatsBarProps {
  localCount: number;
  nationalCount: number;
  newestEventDate: string | null;
  events: Event[];
  activeCategoryFilter?: Categorie | null;
  onCategorySelect?: (cat: Categorie) => void;
}

function formatNewestDate(iso: string | null): string {
  if (!iso) return "";
  try {
    const d = parseISO(iso);
    const diffMs = Date.now() - d.getTime();
    if (diffMs < 60_000) return "à l'instant";
    if (diffMs < 86_400_000) return formatDistanceToNow(d, { locale: fr, addSuffix: true });
    return format(d, "d MMM", { locale: fr });
  } catch {
    return "";
  }
}

export default function StatsBar({ localCount, nationalCount, newestEventDate, events, activeCategoryFilter, onCategorySelect }: StatsBarProps) {
  const time = formatNewestDate(newestEventDate);
  const total = localCount + nationalCount;

  const catCounts: Partial<Record<Categorie, number>> = {};
  for (const e of events) {
    catCounts[e.categorie] = (catCounts[e.categorie] ?? 0) + 1;
  }
  const activeCats = (Object.entries(catCounts) as [Categorie, number][]).sort((a, b) => b[1] - a[1]);

  return (
    <div className="px-4 py-1.5 bg-gray-50 border-b border-gray-200 flex-shrink-0">
      <div className="flex items-center gap-2 text-xs">
        <span className="font-semibold text-gray-700">{total}</span>
        <span className="text-gray-400">événements</span>

        <span className="text-gray-200 mx-1">|</span>

        <span className="inline-flex items-center gap-1 text-blue-600 font-medium">
          <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z" clipRule="evenodd" />
          </svg>
          {localCount} localisé{localCount !== 1 ? "s" : ""}
        </span>

        <span className="text-gray-400">
          · {nationalCount} national{nationalCount !== 1 ? "aux" : ""}
        </span>

        {time && (
          <span className="ml-auto text-gray-400" title="Date du dernier article reçu">
            Dernier article {time}
          </span>
        )}
      </div>

      {activeCats.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1.5">
          {activeCats.map(([cat, count]) => {
            const cfg = CATEGORY_CONFIG[cat];
            if (!cfg) return null;
            const isActive = activeCategoryFilter === cat;
            return (
              <button
                key={cat}
                onClick={() => onCategorySelect?.(cat)}
                className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-white text-[10px] font-medium transition-opacity ${
                  onCategorySelect ? "cursor-pointer hover:opacity-80" : "cursor-default"
                } ${isActive ? "ring-2 ring-white ring-offset-1" : ""}`}
                style={{ backgroundColor: cfg.color }}
                title={isActive ? `Afficher toutes les catégories` : `Filtrer : ${cfg.label}`}
              >
                {cfg.icon} {count}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
