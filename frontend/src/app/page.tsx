"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import dynamic from "next/dynamic";

import EventFeed from "@/components/EventFeed";
import FilterBar from "@/components/FilterBar";
import StatusBar from "@/components/StatusBar";
import StatsBar from "@/components/StatsBar";
import { fetchEvents, fetchHealth, triggerIngest } from "@/lib/api";
import { ALL_CATEGORIES, GRAVITE_CONFIG, REFRESH_INTERVAL } from "@/lib/constants";
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

  const [selectedEvent, setSelectedEvent] = useState<Event | null>(null);
  const [mobileView, setMobileView] = useState<"map" | "feed">("map");

  const allEvents: Event[] = eventsData?.events ?? [];

  const localEvents = allEvents.filter(
    (e) => e.lieu_lat !== null && e.lieu_lon !== null
  );

  const nationalEvents = allEvents.filter(
    (e) => e.lieu_niveau === "national" || (e.lieu_lat === null && e.lieu_lon === null)
  );

  const eventCounts: Partial<Record<Categorie, number>> = {};
  for (const e of allEvents) {
    eventCounts[e.categorie] = (eventCounts[e.categorie] ?? 0) + 1;
  }

  const maxGravite = allEvents.reduce((max, e) => Math.max(max, e.gravite), -1);

  const urgentCount = allEvents.filter((e) => e.gravite >= 3).length;
  useEffect(() => {
    const base = "FAIRE Info";
    if (urgentCount > 0) {
      document.title = `🔴 ${urgentCount} urgence${urgentCount > 1 ? "s" : ""} — ${base}`;
    } else {
      document.title = base;
    }
  }, [urgentCount]);

  const handleCategoriesChange = (categories: Categorie[]) => {
    setFilters((prev) => ({ ...prev, categories }));
  };

  const handleGraviteChange = (gravite_min: number) => {
    setFilters((prev) => ({ ...prev, gravite_min }));
  };

  const handleDepuisHeuresChange = (depuis_heures: number) => {
    setFilters((prev) => ({ ...prev, depuis_heures }));
  };

  const activeCategoryFilter: Categorie | null =
    filters.categories.length === 1 ? filters.categories[0] : null;

  const handleStatsBarCategorySelect = (cat: Categorie) => {
    if (activeCategoryFilter === cat) {
      handleCategoriesChange(ALL_CATEGORIES);
    } else {
      handleCategoriesChange([cat]);
    }
  };

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {/* Header */}
      <header className="flex flex-wrap items-center gap-2 px-3 py-2 bg-white border-b border-gray-200 shadow-sm z-10 flex-shrink-0">
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
          onResetFilters={() => setFilters({ categories: ALL_CATEGORIES, gravite_min: 0, depuis_heures: 48 })}
          isLoading={eventsLoading}
          eventCounts={eventCounts}
        />
        {maxGravite >= 2 && (
          <span
            className="hidden sm:inline-flex items-center gap-1 px-2 py-1 rounded-full text-white text-xs font-semibold animate-pulse"
            style={{ backgroundColor: GRAVITE_CONFIG[maxGravite]?.color }}
            title={GRAVITE_CONFIG[maxGravite]?.label}
          >
            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
            {GRAVITE_CONFIG[maxGravite]?.label}
          </span>
        )}
        <button
          onClick={() => {
            navigator.clipboard.writeText(window.location.href).catch(() => {});
          }}
          className="hidden md:flex items-center gap-1 text-xs px-2 py-1 rounded border border-gray-300 text-gray-600 hover:bg-gray-50 transition-colors"
          title="Copier le lien avec les filtres actuels"
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
          </svg>
          <span className="hidden lg:inline">Partager</span>
        </button>
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
        <div className="ml-auto flex items-center gap-2 hidden md:flex">
          {eventsError && allEvents.length > 0 && (
            <span className="text-xs text-amber-600 flex items-center gap-1" title="Données potentiellement périmées — la dernière mise à jour a échoué">
              <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
              </svg>
              Données possiblement périmées
            </span>
          )}
          <span className="text-xs text-gray-400 whitespace-nowrap">
            {eventsData
              ? localEvents.length > 0
                ? `${eventsData.total} événement${eventsData.total > 1 ? "s" : ""} (${localEvents.length} localisé${localEvents.length > 1 ? "s" : ""} · ${nationalEvents.length} national${nationalEvents.length > 1 ? "aux" : ""})`
                : `${eventsData.total} événement${eventsData.total > 1 ? "s" : ""} · tout national`
              : eventsLoading
              ? "Chargement…"
              : ""}
          </span>
        </div>
      </header>

      {/* Mobile toggle bar */}
      <div className="flex md:hidden border-b border-gray-200 bg-white flex-shrink-0">
        <button
          onClick={() => setMobileView("map")}
          className={`flex-1 py-1.5 text-xs font-medium flex items-center justify-center gap-1.5 transition-colors ${
            mobileView === "map" ? "text-blue-700 border-b-2 border-blue-700 bg-blue-50" : "text-gray-500"
          }`}
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
          </svg>
          Carte ({localEvents.length})
        </button>
        <button
          onClick={() => setMobileView("feed")}
          className={`flex-1 py-1.5 text-xs font-medium flex items-center justify-center gap-1.5 transition-colors ${
            mobileView === "feed" ? "text-blue-700 border-b-2 border-blue-700 bg-blue-50" : "text-gray-500"
          }`}
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 10h16M4 14h16M4 18h16" />
          </svg>
          Actualités ({allEvents.length})
        </button>
      </div>

      {/* Main content */}
      <main className="flex flex-col md:flex-row flex-1 overflow-hidden">
        {/* Map — full width on mobile (toggleable), 70% on desktop */}
        <div className={`${mobileView === "map" ? "flex" : "hidden"} md:flex flex-1 min-w-0 relative`}>
          <MapWrapper events={localEvents} selectedEvent={selectedEvent} onSelectEvent={(e) => { setSelectedEvent(e); setMobileView("feed"); }} />
        </div>

        {/* Sidebar — full width on mobile (toggleable), 30% on desktop */}
        <aside className={`${mobileView === "feed" ? "flex" : "hidden"} md:flex flex-col flex-1 md:flex-none md:w-[30%] md:min-w-[260px] md:max-w-sm border-t md:border-t-0 md:border-l border-gray-200 bg-white overflow-hidden`}>
          <StatsBar
            localCount={localEvents.length}
            nationalCount={nationalEvents.length}
            generatedAt={eventsData?.generated_at ?? null}
            events={allEvents}
            activeCategoryFilter={activeCategoryFilter}
            onCategorySelect={handleStatsBarCategorySelect}
          />
          <EventFeed
            events={allEvents}
            isLoading={eventsLoading}
            error={eventsError}
            selectedEventId={selectedEvent?.id ?? null}
            onSelectEvent={setSelectedEvent}
            onRetry={() => refreshEvents()}
          />
        </aside>
      </main>

      {/* Status bar */}
      <StatusBar
        connectors={healthData?.connectors ?? []}
        nextIngestAt={healthData?.next_ingest_at ?? null}
        onTriggerIngest={async () => {
          await triggerIngest();
          // Refresh twice: quick pass after ~10s, then again at ~35s when all connectors finish
          setTimeout(() => refreshEvents(), 10_000);
          setTimeout(() => refreshEvents(), 35_000);
        }}
      />
    </div>
  );
}
