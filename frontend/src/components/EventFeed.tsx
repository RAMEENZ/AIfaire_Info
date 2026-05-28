"use client";

import { useEffect, useRef, useState } from "react";
import { format, formatDistanceToNow, parseISO } from "date-fns";
import { fr } from "date-fns/locale";

import { CATEGORY_CONFIG, GRAVITE_CONFIG, SOURCE_LABELS } from "@/lib/constants";
import { Event } from "@/lib/types";

type Tab = "all" | "local" | "national";

const GRAVITE_BORDER: Record<number, string> = {
  0: "transparent",
  1: "#F59E0B",
  2: "#F97316",
  3: "#EF4444",
};

interface EventFeedProps {
  events: Event[];
  isLoading: boolean;
  error?: Error | null;
  selectedEventId?: string | null;
  onSelectEvent?: (event: Event) => void;
  onRetry?: () => void;
}

function formatRelative(iso: string): string {
  try {
    return formatDistanceToNow(parseISO(iso), { locale: fr, addSuffix: true });
  } catch {
    return iso;
  }
}

function EventCard({
  event,
  selected,
  onSelect,
}: {
  event: Event;
  selected?: boolean;
  onSelect?: (event: Event) => void;
}) {
  const catConfig = CATEGORY_CONFIG[event.categorie];
  const sourceLabel =
    event.source === "presse_rss" && event.auteur
      ? event.auteur
      : SOURCE_LABELS[event.source] ?? event.source;
  const isLocalized = event.lieu_lat !== null && event.lieu_lon !== null;
  const borderColor = GRAVITE_BORDER[event.gravite] ?? "transparent";

  return (
    <article
      id={`event-card-${event.id}`}
      className={`px-4 py-3 border-b border-gray-100 transition-colors cursor-pointer ${
        selected ? "bg-blue-50 hover:bg-blue-100" : "hover:bg-gray-50"
      }`}
      style={{ borderLeft: `3px solid ${borderColor}` }}
      onClick={() => onSelect?.(event)}
    >
      <a
        href={event.source_url}
        target="_blank"
        rel="noopener noreferrer"
        className="block group"
      >
        <p className="text-sm font-medium text-gray-900 group-hover:text-blue-700 leading-snug line-clamp-2">
          {event.titre}
        </p>
      </a>

      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <span
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-white text-xs font-medium"
          style={{ backgroundColor: catConfig?.color ?? "#6B7280" }}
        >
          {catConfig?.icon}{" "}
          <span className="hidden sm:inline">{catConfig?.label ?? event.categorie}</span>
        </span>

        {event.gravite >= 1 && (
          <span
            className="inline-flex items-center px-1.5 py-0.5 rounded text-white text-xs font-medium"
            style={{ backgroundColor: GRAVITE_CONFIG[event.gravite]?.color ?? "#6B7280" }}
          >
            {GRAVITE_CONFIG[event.gravite]?.label}
          </span>
        )}

        {isLocalized && event.lieu_nom && event.lieu_nom !== "national" && (
          <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 text-xs">
            <svg className="w-3 h-3 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z" clipRule="evenodd" />
            </svg>
            {event.lieu_nom}
          </span>
        )}

        {!isLocalized && event.lieu_nom && event.lieu_nom !== "national" && (
          <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 text-xs">
            {event.lieu_nom}
          </span>
        )}

        {event.resume_ia && (
          <p className="w-full text-xs text-gray-500 line-clamp-2 mt-0.5">
            {event.resume_ia}
          </p>
        )}
      </div>

      <div className="mt-1.5 flex items-center justify-between gap-2 text-xs text-gray-400">
        <span className="inline-block px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 font-medium shrink-0 truncate max-w-[120px]">
          {sourceLabel}
        </span>
        <time
          dateTime={event.date_publication}
          className="text-right shrink-0"
          title={(() => {
            try { return format(parseISO(event.date_publication), "d MMM yyyy HH:mm", { locale: fr }); }
            catch { return event.date_publication; }
          })()}
        >
          {formatRelative(event.date_publication)}
        </time>
      </div>
    </article>
  );
}

function AlertBanner({ events, onSelect }: { events: Event[]; onSelect?: (e: Event) => void }) {
  const allUrgent = events
    .filter((e) => e.gravite >= 2)
    .sort((a, b) => b.gravite - a.gravite || new Date(b.date_publication).getTime() - new Date(a.date_publication).getTime());
  const urgent = allUrgent.slice(0, 4);
  const totalUrgent = allUrgent.length;

  if (totalUrgent === 0) return null;

  const hasCritical = allUrgent.some((e) => e.gravite >= 3);
  const bg = hasCritical ? "bg-red-50 border-red-200" : "bg-orange-50 border-orange-200";
  const titleColor = hasCritical ? "text-red-700" : "text-orange-700";
  const textColor = hasCritical ? "text-red-800 hover:text-red-600" : "text-orange-800 hover:text-orange-600";

  return (
    <div className={`px-3 py-2 border-b ${bg}`}>
      <p className={`text-xs font-semibold mb-1.5 flex items-center gap-1 ${titleColor}`}>
        <svg className="w-3.5 h-3.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
        </svg>
        {totalUrgent} alerte{totalUrgent > 1 ? "s" : ""} importante{totalUrgent > 1 ? "s" : ""}
        {totalUrgent > 4 && <span className="font-normal opacity-70"> (top 4)</span>}
      </p>
      <ul className="space-y-1">
        {urgent.map((e) => (
          <li key={e.id} className="flex items-center gap-1.5">
            <span
              className="w-1.5 h-1.5 rounded-full flex-shrink-0"
              style={{ backgroundColor: GRAVITE_CONFIG[e.gravite]?.color }}
            />
            <button
              className={`text-xs line-clamp-1 text-left flex-1 min-w-0 ${textColor} hover:underline`}
              onClick={() => onSelect?.(e)}
            >
              {e.titre}
            </button>
            <a
              href={e.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex-shrink-0 text-gray-400 hover:text-gray-600"
              title="Ouvrir l'article"
              onClick={(ev) => ev.stopPropagation()}
            >
              <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function EventFeed({ events, isLoading, error, selectedEventId, onSelectEvent, onRetry }: EventFeedProps) {
  const [tab, setTab] = useState<Tab>("all");
  const [search, setSearch] = useState("");
  const searchInputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (selectedEventId == null) return;
    const el = document.getElementById(`event-card-${selectedEventId}`);
    el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [selectedEventId]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT") {
        e.preventDefault();
        searchInputRef.current?.focus();
      } else if (e.key === "Escape" && document.activeElement === searchInputRef.current) {
        setSearch("");
        searchInputRef.current?.blur();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  const searchLower = search.trim().toLowerCase();

  const matchesSearch = (e: Event) => {
    if (!searchLower) return true;
    return (
      e.titre.toLowerCase().includes(searchLower) ||
      (e.lieu_nom?.toLowerCase().includes(searchLower) ?? false) ||
      (e.resume_ia?.toLowerCase().includes(searchLower) ?? false) ||
      (e.auteur?.toLowerCase().includes(searchLower) ?? false)
    );
  };

  const searchFiltered = events.filter(matchesSearch);
  const localCount = searchFiltered.filter((e) => e.lieu_lat !== null && e.lieu_lon !== null).length;
  const nationalCount = searchFiltered.length - localCount;

  const filtered = searchFiltered.filter((e) => {
    if (tab === "local") return e.lieu_lat !== null && e.lieu_lon !== null;
    if (tab === "national") return e.lieu_lat === null || e.lieu_lon === null;
    return true;
  });

  const sorted = [...filtered].sort(
    (a, b) =>
      b.gravite - a.gravite ||
      new Date(b.date_publication).getTime() - new Date(a.date_publication).getTime()
  );

  const tabClass = (t: Tab) =>
    `px-2 py-0.5 text-xs rounded transition-colors ${
      tab === t
        ? "bg-blue-100 text-blue-700 font-medium"
        : "text-gray-500 hover:bg-gray-100"
    }`;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Alert banner */}
      <AlertBanner events={events} onSelect={onSelectEvent} />

      {/* Header + tabs */}
      <div className="px-4 pt-2.5 pb-2 border-b border-gray-200 flex-shrink-0">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-gray-700">Actualités</h2>
          {sorted.length > 0 && (
            <span className="text-xs text-gray-400">{sorted.length}</span>
          )}
        </div>
        <div className="relative mb-2">
          <svg className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-gray-400 pointer-events-none" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            ref={searchInputRef}
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Rechercher… (/)"
            className="w-full pl-6 pr-3 py-1 text-xs rounded border border-gray-200 bg-gray-50 focus:outline-none focus:border-blue-400 focus:bg-white transition-colors"
          />
        </div>
        <div className="flex gap-1">
          <button className={tabClass("all")} onClick={() => setTab("all")}>
            Tous ({searchFiltered.length})
          </button>
          <button className={tabClass("local")} onClick={() => setTab("local")}>
            <span className="inline-flex items-center gap-0.5">
              <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z" clipRule="evenodd" />
              </svg>
              Carte ({localCount})
            </span>
          </button>
          <button className={tabClass("national")} onClick={() => setTab("national")}>
            National ({nationalCount})
          </button>
        </div>
      </div>

      {/* List */}
      <div ref={listRef} className="flex-1 overflow-y-auto relative">
        {error && !isLoading && sorted.length === 0 && (
          <div className="flex flex-col items-center justify-center h-40 gap-3 px-4">
            <svg className="w-8 h-8 text-red-400 flex-shrink-0" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
            </svg>
            <div className="text-center">
              <p className="text-sm font-medium text-red-600 mb-1">Serveur inaccessible</p>
              <p className="text-xs text-gray-400">Vérifiez que le backend est en ligne</p>
            </div>
            {onRetry && (
              <button
                onClick={onRetry}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border border-blue-300 text-blue-700 bg-blue-50 hover:bg-blue-100 transition-colors"
              >
                <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                Réessayer
              </button>
            )}
          </div>
        )}

        {isLoading && sorted.length === 0 && (
          <div className="flex flex-col gap-3 p-4">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="animate-pulse">
                <div className="h-3 bg-gray-200 rounded w-full mb-1.5" />
                <div className="h-3 bg-gray-200 rounded w-3/4 mb-2" />
                <div className="h-2 bg-gray-100 rounded w-1/2" />
              </div>
            ))}
          </div>
        )}

        {!isLoading && !error && sorted.length === 0 && (
          <div className="flex flex-col items-center justify-center h-32 text-sm text-gray-400 gap-1">
            {searchLower ? (
              <>
                <span>Aucun résultat pour « {search} »</span>
                <button onClick={() => setSearch("")} className="text-xs text-blue-500 hover:underline">
                  Effacer la recherche
                </button>
              </>
            ) : (
              <span>Aucun événement</span>
            )}
          </div>
        )}

        {sorted.map((event) => (
          <EventCard
            key={event.id}
            event={event}
            selected={event.id === selectedEventId}
            onSelect={onSelectEvent}
          />
        ))}

        {sorted.length > 8 && (
          <div className="sticky bottom-2 flex justify-center pb-2 pointer-events-none">
            <button
              onClick={() => listRef.current?.scrollTo({ top: 0, behavior: "smooth" })}
              className="pointer-events-auto bg-white border border-gray-200 shadow-sm rounded-full px-3 py-1 text-xs text-gray-500 hover:text-blue-600 hover:border-blue-300 transition-colors"
            >
              ↑ Haut
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
