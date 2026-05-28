"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import dynamic from "next/dynamic";

import EventFeed from "@/components/EventFeed";
import FilterBar from "@/components/FilterBar";
import StatusBar from "@/components/StatusBar";
import StatsBar from "@/components/StatsBar";
import { fetchEvents, fetchHealth } from "@/lib/api";
import { ALL_CATEGORIES, REFRESH_INTERVAL } from "@/lib/constants";
import { Categorie, Event, EventFilters } from "@/lib/types";

function exportToCSV(events: Event[]) {
  const headers = ["id", "titre", "source", "auteur", "categorie", "gravite", "lieu_nom", "lieu_niveau", "lieu_lat", "lieu_lon", "date_publication", "source_url", "resume_ia"];
  const esc = (v: string | null | undefined) => `"${(v ?? "").replace(/"/g, '""')}"`;
  const rows = events.map((e) => [
    e.id, esc(e.titre), e.source, esc(e.auteur), e.categorie,
    e.gravite, esc(e.lieu_nom), e.lieu_niveau,
    e.lieu_lat ?? "", e.lieu_lon ?? "",
    e.date_publication, esc(e.source_url), esc(e.resume_ia),
  ]);
  const csv = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `faire-info-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

const MapWrapper = dynamic(() => import("@/components/MapWrapper"), {
  ssr: false,
  loading: () => (
    <div className="flex-1 flex items-center justify-center bg-gray-100">
      <span className="text-gray-500 text-sm">Chargement de la carte…</span>
    </div>
  ),
});

function readFiltersFromURL(): EventFilters {
  if (typeof window === "undefined") {
    return { categories: ALL_CATEGORIES, gravite_min: 0, depuis_heures: 48 };
  }
  const p = new URLSearchParams(window.location.search);
  const cats = p.get("cats");
  const categories: Categorie[] = cats
    ? (cats.split(",").filter((c) => ALL_CATEGORIES.includes(c as Categorie)) as Categorie[])
    : ALL_CATEGORIES;
  const gravite_min = Math.max(0, Math.min(3, parseInt(p.get("g") ?? "0", 10) || 0));
  const depuis_heures_raw = parseInt(p.get("h") ?? "48", 10);
  const depuis_heures = [24, 48, 168, 720].includes(depuis_heures_raw) ? depuis_heures_raw : 48;
  return { categories, gravite_min, depuis_heures };
}

export default function HomePage() {
  const [filters, setFilters] = useState<EventFilters>(readFiltersFromURL);

  useEffect(() => {
    const p = new URLSearchParams();
    if (filters.categories.length !== ALL_CATEGORIES.length) {
      p.set("cats", filters.categories.join(","));
    }
    if (filters.gravite_min > 0) p.set("g", String(filters.gravite_min));
    if (filters.depuis_heures !== 48) p.set("h", String(filters.depuis_heures));
    const qs = p.toString();
    const newUrl = qs ? `?${qs}` : window.location.pathname;
    window.history.replaceState(null, "", newUrl);
  }, [filters]);

  // SWR key uses stable primitive values (no datetime string that changes every render)
  const swrKey = ["events", filters.categories, filters.gravite_min, filters.depuis_heures];

  const {
    data: eventsData,
    isLoading: eventsLoading,
    error: eventsError,
    mutate: refreshEvents,
  } = useSWR(
    swrKey,
    () =>
      fetchEvents({
        categories: filters.categories,
        gravite_min: filters.gravite_min > 0 ? filters.gravite_min : undefined,
        depuis: new Date(Date.now() - filters.depuis_heures * 3600 * 1000).toISOString(),
      }),
    {
      refreshInterval: REFRESH_INTERVAL,
      revalidateOnFocus: false,
    }
  );

  const { data: healthData } = useSWR("health", fetchHealth, {
    refreshInterval: REFRESH_INTERVAL,
    revalidateOnFocus: false,
  });

  const allEvents: Event[] = eventsData?.events ?? [];

  const localEvents = allEvents.filter(
    (e) => e.lieu_lat !== null && e.lieu_lon !== null
  );

  const nationalEvents = allEvents.filter(
    (e) => e.lieu_niveau === "national" || (e.lieu_lat === null && e.lieu_lon === null)
  );

  const handleCategoriesChange = (categories: Categorie[]) => {
    setFilters((prev) => ({ ...prev, categories }));
  };

  const handleGraviteChange = (gravite_min: number) => {
    setFilters((prev) => ({ ...prev, gravite_min }));
  };

  const handleDepuisHeuresChange = (depuis_heures: number) => {
    setFilters((prev) => ({ ...prev, depuis_heures }));
  };

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {/* Header */}
      <header className="flex items-center gap-4 px-4 py-2 bg-white border-b border-gray-200 shadow-sm z-10 flex-shrink-0">
        <div className="flex items-center gap-2 mr-4">
          <span className="text-blue-700 font-black text-xl tracking-tight">FAIRE</span>
          <span className="text-gray-500 text-sm font-medium hidden sm:inline">Info</span>
        </div>
        <FilterBar
          filters={filters}
          onCategoriesChange={handleCategoriesChange}
          onGraviteChange={handleGraviteChange}
          onDepuisHeuresChange={handleDepuisHeuresChange}
          onRefresh={() => refreshEvents()}
          isLoading={eventsLoading}
        />
        {allEvents.length > 0 && (
          <button
            onClick={() => exportToCSV(allEvents)}
            className="hidden lg:flex items-center gap-1 text-xs px-2 py-1 rounded border border-gray-300 text-gray-600 hover:bg-gray-50 transition-colors"
            title={`Télécharger ${allEvents.length} événements en CSV`}
          >
            <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            CSV
          </button>
        )}
        <div className="ml-auto text-xs text-gray-400 hidden md:block whitespace-nowrap">
          {eventsData
            ? localEvents.length > 0
              ? `${eventsData.total} événement${eventsData.total > 1 ? "s" : ""} (${localEvents.length} localisé${localEvents.length > 1 ? "s" : ""} · ${nationalEvents.length} national${nationalEvents.length > 1 ? "aux" : ""})`
              : `${eventsData.total} événement${eventsData.total > 1 ? "s" : ""} · tout national`
            : eventsLoading
            ? "Chargement…"
            : ""}
        </div>
      </header>

      {/* Main content */}
      <main className="flex flex-1 overflow-hidden">
        {/* Map — 70% */}
        <div className="flex-1 min-w-0 relative">
          <MapWrapper events={localEvents} />
        </div>

        {/* Sidebar — 30% */}
        <aside className="w-[30%] min-w-[260px] max-w-sm border-l border-gray-200 bg-white flex flex-col overflow-hidden">
          <StatsBar
            localCount={localEvents.length}
            nationalCount={nationalEvents.length}
            generatedAt={eventsData?.generated_at ?? null}
          />
          <EventFeed events={allEvents} isLoading={eventsLoading} error={eventsError} />
        </aside>
      </main>

      {/* Status bar */}
      <StatusBar connectors={healthData?.connectors ?? []} />
    </div>
  );
}
