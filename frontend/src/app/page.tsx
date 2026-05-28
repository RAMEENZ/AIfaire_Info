"use client";

import { useState } from "react";
import useSWR from "swr";
import dynamic from "next/dynamic";

import EventFeed from "@/components/EventFeed";
import FilterBar from "@/components/FilterBar";
import StatusBar from "@/components/StatusBar";
import StatsBar from "@/components/StatsBar";
import { fetchEvents, fetchHealth } from "@/lib/api";
import { ALL_CATEGORIES, REFRESH_INTERVAL } from "@/lib/constants";
import { Categorie, Event, EventFilters } from "@/lib/types";

const MapWrapper = dynamic(() => import("@/components/MapWrapper"), {
  ssr: false,
  loading: () => (
    <div className="flex-1 flex items-center justify-center bg-gray-100">
      <span className="text-gray-500 text-sm">Chargement de la carte…</span>
    </div>
  ),
});

export default function HomePage() {
  const [filters, setFilters] = useState<EventFilters>({
    categories: ALL_CATEGORIES,
    gravite_min: 0,
  });

  const eventsParams = {
    categories: filters.categories,
    gravite_min: filters.gravite_min > 0 ? filters.gravite_min : undefined,
  };

  const {
    data: eventsData,
    isLoading: eventsLoading,
    mutate: refreshEvents,
  } = useSWR(["events", eventsParams], () => fetchEvents(eventsParams), {
    refreshInterval: REFRESH_INTERVAL,
    revalidateOnFocus: false,
  });

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
          onRefresh={() => refreshEvents()}
          isLoading={eventsLoading}
        />
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
          <MapWrapper
            events={localEvents}
          />
        </div>

        {/* Sidebar — 30% */}
        <aside className="w-[30%] min-w-[260px] max-w-sm border-l border-gray-200 bg-white flex flex-col overflow-hidden">
          <StatsBar
            localCount={localEvents.length}
            nationalCount={nationalEvents.length}
            generatedAt={eventsData?.generated_at ?? null}
          />
          <EventFeed events={allEvents} isLoading={eventsLoading} />
        </aside>
      </main>

      {/* Status bar */}
      <StatusBar connectors={healthData?.connectors ?? []} />
    </div>
  );
}
