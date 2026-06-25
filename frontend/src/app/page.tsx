"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import dynamic from "next/dynamic";

import TimelineBar from "@/components/TimelineBar";
import DailyBrief from "@/components/DailyBrief";
import EventFeed from "@/components/EventFeed";
import FilterBar from "@/components/FilterBar";
import StatusBar from "@/components/StatusBar";
import StatsBar from "@/components/StatsBar";
import AlertSettings from "@/components/AlertSettings";
import { fetchEvents, fetchHealth, triggerIngest } from "@/lib/api";
import { API_BASE_URL, ALL_CATEGORIES, GRAVITE_CONFIG, REFRESH_INTERVAL } from "@/lib/constants";
import {
  AlertSettings as AlertSettingsType,
  loadAlertSettings,
  shouldAlert,
  sendEventNotification,
} from "@/lib/notifications";
import { Categorie, Event, EventFilters } from "@/lib/types";

function useEventStream(categories: Categorie[], graviteMin: number) {
  const [liveEvents, setLiveEvents] = useState<Event[]>([]);
  const [isLive, setIsLive] = useState(false);
  const seenRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const params = new URLSearchParams();
    categories.forEach((c) => params.append("categories", c));
    if (graviteMin > 0) params.set("gravite_min", String(graviteMin));

    const es = new EventSource(`${API_BASE_URL}/events/stream?${params}`);

    es.addEventListener("connected", () => setIsLive(true));

    es.addEventListener("events", (e: MessageEvent) => {
      try {
        const incoming: Event[] = JSON.parse(e.data);
        const fresh = incoming.filter((ev) => !seenRef.current.has(ev.id));
        if (fresh.length > 0) {
          fresh.forEach((ev) => seenRef.current.add(ev.id));
          setLiveEvents((prev) => [...fresh, ...prev].slice(0, 200));
        }
      } catch {
        // ignore parse errors
      }
    });

    es.onerror = () => setIsLive(false);

    return () => {
      es.close();
      setIsLive(false);
    };
  // Reconnect only when filters change
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [categories.join(","), graviteMin]);

  return { liveEvents, isLive };
}

function exportToCSV(events: Event[]) {
  const headers = ["id", "titre", "source", "auteur", "categorie", "gravite", "lieu_nom", "lieu_niveau", "lieu_lat", "lieu_lon", "date_publication", "source_url", "resume_ia"];
  const esc = (v: string | null | undefined) => `"${(v ?? "").replace(/"/g, '""')}"`;
  const rows = events.map((e) => [
    e.id, esc(e.titre), esc(e.source), esc(e.auteur), esc(e.categorie),
    e.gravite, esc(e.lieu_nom), esc(e.lieu_niveau),
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
  const [darkMode, setDarkMode] = useState(false);
  const [selectedDept, setSelectedDept] = useState<string | null>(null);
  const [historyDate, setHistoryDate] = useState<Date | null>(null);

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
  const swrKey = ["events", filters.categories, filters.gravite_min, filters.depuis_heures, historyDate?.toISOString() ?? null];

  const {
    data: eventsData,
    isLoading: eventsLoading,
    error: eventsError,
    mutate: refreshEvents,
  } = useSWR(
    swrKey,
    () => {
      if (historyDate) {
        const depuis = new Date(historyDate);
        const avant = new Date(historyDate);
        avant.setDate(avant.getDate() + 2);
        return fetchEvents({
          categories: filters.categories,
          gravite_min: filters.gravite_min > 0 ? filters.gravite_min : undefined,
          depuis: depuis.toISOString(),
          avant: avant.toISOString(),
        });
      }
      return fetchEvents({
        categories: filters.categories,
        gravite_min: filters.gravite_min > 0 ? filters.gravite_min : undefined,
        depuis: new Date(Date.now() - filters.depuis_heures * 3600 * 1000).toISOString(),
      });
    },
    {
      refreshInterval: historyDate ? 0 : REFRESH_INTERVAL,
      revalidateOnFocus: false,
    }
  );

  const { data: healthData } = useSWR("health", fetchHealth, {
    refreshInterval: REFRESH_INTERVAL,
    revalidateOnFocus: false,
  });

  const [selectedEvent, setSelectedEvent] = useState<Event | null>(null);
  const [mobileView, setMobileView] = useState<"map" | "feed">("map");
  const ingestTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  // Dark mode: sync with localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem("theme");
    const isDark =
      stored === "dark" ||
      (!stored && window.matchMedia("(prefers-color-scheme: dark)").matches);
    setDarkMode(isDark);
  }, []);

  const toggleDark = useCallback(() => {
    setDarkMode((prev) => {
      const next = !prev;
      if (next) {
        document.documentElement.classList.add("dark");
        localStorage.setItem("theme", "dark");
      } else {
        document.documentElement.classList.remove("dark");
        localStorage.setItem("theme", "light");
      }
      return next;
    });
  }, []);

  useEffect(() => {
    return () => { ingestTimersRef.current.forEach(clearTimeout); };
  }, []);

  const handleResetFilters = useCallback(() => {
    setFilters({ categories: ALL_CATEGORIES, gravite_min: 0, depuis_heures: 48 });
  }, []);

  const handleSelectEvent = useCallback((e: Event) => {
    setSelectedEvent(e);
    setMobileView("feed");
  }, []);

  const handleTriggerIngest = useCallback(async () => {
    await triggerIngest();
    const t1 = setTimeout(refreshEvents, 10_000);
    const t2 = setTimeout(refreshEvents, 35_000);
    ingestTimersRef.current.push(t1, t2);
  }, [refreshEvents]);

  const { liveEvents, isLive } = useEventStream(filters.categories, filters.gravite_min);

  const allEvents: Event[] = useMemo(() => {
    const base = eventsData?.events ?? [];
    if (liveEvents.length === 0) return base;
    const existingIds = new Set(base.map((e) => e.id));
    const fresh = liveEvents.filter((e) => !existingIds.has(e.id));
    return fresh.length > 0 ? [...fresh, ...base] : base;
  }, [eventsData?.events, liveEvents]);

  // Auto-select event from ?event=<id> URL param on first load
  useEffect(() => {
    if (allEvents.length === 0) return;
    const p = new URLSearchParams(window.location.search);
    const eventId = p.get("event");
    if (!eventId) return;
    const found = allEvents.find((e) => e.id === eventId);
    if (found) {
      setSelectedEvent(found);
      setMobileView("feed");
    }
  // Run only once when events first arrive
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allEvents.length > 0]);

  const localEvents = useMemo(
    () => allEvents.filter((e) => e.lieu_lat !== null && e.lieu_lon !== null),
    [allEvents]
  );

  const nationalEvents = useMemo(
    () => allEvents.filter((e) => e.lieu_niveau === "national" || (e.lieu_lat === null && e.lieu_lon === null)),
    [allEvents]
  );

  const eventCounts: Partial<Record<Categorie, number>> = useMemo(() => {
    const counts: Partial<Record<Categorie, number>> = {};
    for (const e of allEvents) {
      counts[e.categorie] = (counts[e.categorie] ?? 0) + 1;
    }
    return counts;
  }, [allEvents]);

  const maxGravite = useMemo(() => allEvents.reduce((max, e) => Math.max(max, e.gravite), -1), [allEvents]);

  const urgentCount = useMemo(() => allEvents.filter((e) => e.gravite >= 3).length, [allEvents]);

  // Most recent event publication time — used as freshness indicator in StatsBar
  const newestEventDate = useMemo(() => {
    if (allEvents.length === 0) return null;
    return allEvents.reduce(
      (latest, e) => (e.date_publication > latest ? e.date_publication : latest),
      allEvents[0].date_publication
    );
  }, [allEvents]);
  useEffect(() => {
    const base = "FAIRE Info";
    if (urgentCount > 0) {
      document.title = `🔴 ${urgentCount} urgence${urgentCount > 1 ? "s" : ""} — ${base}`;
    } else {
      document.title = base;
    }
  }, [urgentCount]);

  // ── Alertes navigateur ───────────────────────────────────────────────────
  const [alertSettings, setAlertSettings] = useState<AlertSettingsType | null>(null);
  const seenEventIdsRef = useRef<Set<string> | null>(null);

  useEffect(() => {
    setAlertSettings(loadAlertSettings());
  }, []);

  useEffect(() => {
    if (!alertSettings) return;
    // Premier passage : on mémorise les IDs déjà présents sans notifier
    // (sinon tout le feed initial déclencherait une avalanche d'alertes).
    if (seenEventIdsRef.current === null) {
      seenEventIdsRef.current = new Set(allEvents.map((e) => e.id));
      return;
    }
    const seen = seenEventIdsRef.current;
    const fresh = allEvents.filter((e) => !seen.has(e.id));
    for (const e of fresh) {
      seen.add(e.id);
      if (shouldAlert(e, alertSettings)) sendEventNotification(e);
    }
  }, [allEvents, alertSettings]);

  const handleCategoriesChange = useCallback((categories: Categorie[]) => {
    setFilters((prev) => ({ ...prev, categories }));
  }, []);

  const handleGraviteChange = useCallback((gravite_min: number) => {
    setFilters((prev) => ({ ...prev, gravite_min }));
  }, []);

  const handleDepuisHeuresChange = useCallback((depuis_heures: number) => {
    setFilters((prev) => ({ ...prev, depuis_heures }));
  }, []);

  const activeCategoryFilter: Categorie | null =
    filters.categories.length === 1 ? filters.categories[0] : null;

  const handleStatsBarCategorySelect = useCallback((cat: Categorie) => {
    setFilters((prev) => {
      const active = prev.categories.length === 1 ? prev.categories[0] : null;
      return { ...prev, categories: active === cat ? ALL_CATEGORIES : [cat] };
    });
  }, []);

  const handleSelectDept = useCallback((deptCode: string) => {
    setSelectedDept((prev) => (prev === deptCode ? null : deptCode));
    setMobileView("feed");
  }, []);

  // Events filtered by selected dept (for the sidebar banner)
  const deptEvents = useMemo(() => {
    if (!selectedDept) return [];
    return allEvents.filter((e) => e.lieu_code_insee?.startsWith(selectedDept) ?? false);
  }, [allEvents, selectedDept]);

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <header className="flex flex-wrap items-center gap-2 px-3 py-2 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 shadow-sm z-10 flex-shrink-0">
        <div className="flex items-center gap-2 mr-4">
          <span className="text-blue-700 font-black text-xl tracking-tight">FAIRE</span>
          <span className="text-gray-500 dark:text-gray-400 text-sm font-medium hidden sm:inline">Info</span>
        </div>
        <FilterBar
          filters={filters}
          onCategoriesChange={handleCategoriesChange}
          onGraviteChange={handleGraviteChange}
          onDepuisHeuresChange={handleDepuisHeuresChange}
          onRefresh={refreshEvents}
          onResetFilters={handleResetFilters}
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
        <AlertSettings onChange={setAlertSettings} />
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
            className="hidden lg:flex items-center gap-1 text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            title={`Télécharger ${allEvents.length} événements en CSV`}
          >
            <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            CSV
          </button>
        )}
        <a
          href={`${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api"}/feed.rss${filters.categories.length < 12 ? "?categories=" + filters.categories.join(",") : ""}`}
          target="_blank"
          rel="noopener noreferrer"
          className="hidden md:flex items-center gap-1 text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          title="Flux RSS Atom (filtre catégories actuel)"
        >
          <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
            <path d="M5 3a1 1 0 000 2c5.523 0 10 4.477 10 10a1 1 0 102 0C17 8.373 11.627 3 5 3z" />
            <path d="M4 9a1 1 0 000 2 7 7 0 017 7 1 1 0 102 0A9 9 0 004 9z" />
            <path d="M3 15a2 2 0 114 0 2 2 0 01-4 0z" />
          </svg>
          <span className="hidden lg:inline">RSS</span>
        </a>
        <a
          href="/stats"
          className="hidden md:flex items-center gap-1 text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          title="Statistiques"
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
          <span className="hidden lg:inline">Stats</span>
        </a>
        <button
          onClick={toggleDark}
          className="flex items-center justify-center w-7 h-7 rounded border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          title={darkMode ? "Passer en mode clair" : "Passer en mode sombre"}
        >
          {darkMode ? (
            <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" clipRule="evenodd" />
            </svg>
          ) : (
            <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
              <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
            </svg>
          )}
        </button>
        <div className="ml-auto flex items-center gap-2 hidden md:flex">
          {isLive && (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-green-100 text-green-700 text-[10px] font-semibold uppercase tracking-wide">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
              En direct
            </span>
          )}
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
          <MapWrapper events={localEvents} selectedEvent={selectedEvent} onSelectEvent={handleSelectEvent} onSelectDept={handleSelectDept} />
        </div>

        {/* Sidebar — full width on mobile (toggleable), 30% on desktop */}
        <aside className={`${mobileView === "feed" ? "flex" : "hidden"} md:flex flex-col flex-1 md:flex-none md:w-[30%] md:min-w-[260px] md:max-w-sm border-t md:border-t-0 md:border-l border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 overflow-hidden`}>
          {/* Dept banner */}
          {historyDate && (
            <div className="flex items-center justify-between px-3 py-1.5 bg-amber-50 dark:bg-amber-900/30 border-b border-amber-200 dark:border-amber-800 flex-shrink-0">
              <span className="text-xs text-amber-700 dark:text-amber-300 font-medium">
                ⏪ {historyDate.toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" })} — {new Date(historyDate.getTime() + 2 * 86400000).toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}
              </span>
              <button
                onClick={() => setHistoryDate(null)}
                className="text-amber-400 hover:text-amber-600 dark:hover:text-amber-200 transition-colors"
                title="Retour au live"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          )}
          {selectedDept && (
            <div className="flex items-center justify-between px-3 py-1.5 bg-blue-50 dark:bg-blue-900/30 border-b border-blue-200 dark:border-blue-800 flex-shrink-0">
              <span className="text-xs text-blue-700 dark:text-blue-300 font-medium">
                Dép. {selectedDept} — {deptEvents.length} événement{deptEvents.length !== 1 ? "s" : ""}
              </span>
              <button
                onClick={() => setSelectedDept(null)}
                className="text-blue-400 hover:text-blue-600 dark:hover:text-blue-200 transition-colors"
                title="Effacer le filtre département"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          )}
          <TimelineBar
            categories={filters.categories}
            graviteMin={filters.gravite_min}
            historyDate={historyDate}
            onHistoryDateChange={setHistoryDate}
          />
          <StatsBar
            localCount={localEvents.length}
            nationalCount={nationalEvents.length}
            newestEventDate={newestEventDate}
            events={allEvents}
            activeCategoryFilter={activeCategoryFilter}
            onCategorySelect={handleStatsBarCategorySelect}
          />
          <DailyBrief />
          <EventFeed
            events={allEvents}
            isLoading={eventsLoading}
            error={eventsError}
            selectedEventId={selectedEvent?.id ?? null}
            onSelectEvent={setSelectedEvent}
            onRetry={refreshEvents}
            liveEventIds={new Set(liveEvents.map((e) => e.id))}
          />
        </aside>
      </main>

      {/* Status bar */}
      <StatusBar
        connectors={healthData?.connectors ?? []}
        nextIngestAt={healthData?.next_ingest_at ?? null}
        onTriggerIngest={handleTriggerIngest}
      />
    </div>
  );
}
