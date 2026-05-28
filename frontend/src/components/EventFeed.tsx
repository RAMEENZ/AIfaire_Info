"use client";

import { useState } from "react";
import { formatDistanceToNow, parseISO } from "date-fns";
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
}

function formatRelative(iso: string): string {
  try {
    return formatDistanceToNow(parseISO(iso), { locale: fr, addSuffix: true });
  } catch {
    return iso;
  }
}

function EventCard({ event }: { event: Event }) {
  const catConfig = CATEGORY_CONFIG[event.categorie];
  const sourceLabel =
    event.source === "presse_rss" && event.auteur
      ? event.auteur
      : SOURCE_LABELS[event.source] ?? event.source;
  const isLocalized = event.lieu_lat !== null && event.lieu_lon !== null;
  const borderColor = GRAVITE_BORDER[event.gravite] ?? "transparent";

  return (
    <article
      className="px-4 py-3 border-b border-gray-100 hover:bg-gray-50 transition-colors"
      style={{ borderLeft: `3px solid ${borderColor}` }}
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
        <span
          className="inline-block px-1.5 py-0.5 rounded text-white font-medium shrink-0"
          style={{ backgroundColor: catConfig?.color ?? "#6B7280" }}
        >
          {sourceLabel}
        </span>
        <time dateTime={event.date_publication} className="text-right">
          {formatRelative(event.date_publication)}
        </time>
      </div>
    </article>
  );
}

function AlertBanner({ events }: { events: Event[] }) {
  const urgent = events
    .filter((e) => e.gravite >= 2)
    .sort((a, b) => b.gravite - a.gravite || new Date(b.date_publication).getTime() - new Date(a.date_publication).getTime())
    .slice(0, 4);

  if (urgent.length === 0) return null;

  const hasCritical = urgent.some((e) => e.gravite >= 3);
  const bg = hasCritical ? "bg-red-50 border-red-200" : "bg-orange-50 border-orange-200";
  const titleColor = hasCritical ? "text-red-700" : "text-orange-700";
  const linkColor = hasCritical ? "text-red-800 hover:text-red-600" : "text-orange-800 hover:text-orange-600";

  return (
    <div className={`px-3 py-2 border-b ${bg}`}>
      <p className={`text-xs font-semibold mb-1.5 flex items-center gap-1 ${titleColor}`}>
        <svg className="w-3.5 h-3.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
        </svg>
        {urgent.length} alerte{urgent.length > 1 ? "s" : ""} importante{urgent.length > 1 ? "s" : ""}
      </p>
      <ul className="space-y-1">
        {urgent.map((e) => (
          <li key={e.id} className="flex items-start gap-1.5">
            <span
              className="mt-0.5 w-1.5 h-1.5 rounded-full flex-shrink-0"
              style={{ backgroundColor: GRAVITE_CONFIG[e.gravite]?.color }}
            />
            <a
              href={e.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className={`text-xs line-clamp-1 ${linkColor}`}
            >
              {e.titre}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function EventFeed({ events, isLoading, error }: EventFeedProps) {
  const [tab, setTab] = useState<Tab>("all");

  const localCount = events.filter((e) => e.lieu_lat !== null && e.lieu_lon !== null).length;
  const nationalCount = events.length - localCount;

  const filtered = events.filter((e) => {
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
      <AlertBanner events={events} />

      {/* Header + tabs */}
      <div className="px-4 pt-2.5 pb-2 border-b border-gray-200 flex-shrink-0">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-gray-700">Actualités</h2>
          {sorted.length > 0 && (
            <span className="text-xs text-gray-400">{sorted.length}</span>
          )}
        </div>
        <div className="flex gap-1">
          <button className={tabClass("all")} onClick={() => setTab("all")}>
            Tous ({events.length})
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
      <div className="flex-1 overflow-y-auto">
        {error && !isLoading && sorted.length === 0 && (
          <div className="flex flex-col items-center justify-center h-32 gap-2 text-sm text-red-500 px-4">
            <svg className="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
            </svg>
            <span className="text-center text-xs">Impossible de joindre le serveur</span>
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

        {!isLoading && sorted.length === 0 && (
          <div className="flex items-center justify-center h-32 text-sm text-gray-400">
            Aucun événement
          </div>
        )}

        {sorted.map((event) => (
          <EventCard key={event.id} event={event} />
        ))}
      </div>
    </div>
  );
}
