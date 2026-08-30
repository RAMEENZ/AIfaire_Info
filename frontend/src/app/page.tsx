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
import ShortcutsHelp from "@/components/ShortcutsHelp";
import Toaster from "@/components/Toaster";
import OfflineIndicator from "@/components/OfflineIndicator";
import PushSettings from "@/components/PushSettings";
import Wordmark from "@/components/Wordmark";
import { fetchEvents, fetchHealth, fetchMapEvents, triggerIngest } from "@/lib/api";
import { lireDept, lireFiltres, lireRecherche, serialiserEtat } from "@/lib/urlEtat";
import { lireStockage, ecrireStockage, effacerStockage } from "@/lib/stockage";
import { toast } from "@/lib/toast";
import { API_BASE_URL, ALL_CATEGORIES, EVENTS_PAGE_SIZE, GRAVITE_CONFIG, REFRESH_INTERVAL, csvSafe, readableTextColor } from "@/lib/constants";
import {
  AlertSettings as AlertSettingsType,
  loadAlertSettings,
  evenementsAAlerter,
  sendEventNotification,
} from "@/lib/notifications";
import { Categorie, Event, EventFilters } from "@/lib/types";
import { DEPT_CODE_TO_NAME } from "@/lib/departments";

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
  const esc = (v: string | null | undefined) => `"${csvSafe(v ?? "").replace(/"/g, '""')}"`;
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

// Le déclencheur d'ingestion manuelle (POST /api/ingest/run) est protégé côté
// backend : en production il exige INGEST_API_KEY (401) ou est verrouillé sans
// clé (503). Le front public ne peut pas transmettre cette clé, donc le bouton
// n'a de sens qu'en dev/local. Masqué par défaut ; activer explicitement via
// NEXT_PUBLIC_ENABLE_INGEST_BUTTON=true (cf. .env.local.example).
const INGEST_BUTTON_ENABLED = process.env.NEXT_PUBLIC_ENABLE_INGEST_BUTTON === "true";

const MapWrapper = dynamic(() => import("@/components/MapWrapper"), {
  ssr: false,
  loading: () => (
    <div className="flex-1 flex items-center justify-center bg-gray-100 dark:bg-gray-700">
      <span className="text-gray-500 dark:text-gray-400 text-sm">Chargement de la carte…</span>
    </div>
  ),
});

// Au premier rendu serveur, `window` n'existe pas : on repart des valeurs par
// défaut, l'état réel étant relu côté client.
const rechercheCourante = () => (typeof window === "undefined" ? "" : window.location.search);

const readFiltersFromURL = (): EventFilters => lireFiltres(rechercheCourante());
const readDeptFromURL = (): string | null => lireDept(rechercheCourante());
const readQueryFromURL = (): string => lireRecherche(rechercheCourante());

export default function HomePage() {
  const [filters, setFilters] = useState<EventFilters>(readFiltersFromURL);
  const [darkMode, setDarkMode] = useState(false);
  const [selectedDept, setSelectedDept] = useState<string | null>(readDeptFromURL);
  // Département épinglé : persiste entre les sessions (localStorage) et
  // ré-applique le filtre départemental au chargement.
  const [pinnedDept, setPinnedDept] = useState<string | null>(null);
  const [historyDate, setHistoryDate] = useState<Date | null>(null);

  useEffect(() => {
    const stored = lireStockage("pinnedDept");
    if (stored && DEPT_CODE_TO_NAME[stored]) {
      setPinnedDept(stored);
      // Un département dans l'URL l'emporte sur le département épinglé :
      // recevoir « la carte du Finistère » et voir s'afficher son propre
      // département épinglé rendrait tout lien partagé inutilisable.
      if (!readDeptFromURL()) setSelectedDept(stored);
    }
  }, []);

  // Recherche côté serveur : porte sur toute la base et non sur les seuls
  // événements déjà chargés (auparavant « incendie Gard » ne trouvait rien si
  // l'événement n'était pas dans la page courante). Valeur déjà anti-rebondie
  // par EventFeed, et relue depuis l'URL pour qu'une recherche se partage.
  const [serverQuery, setServerQuery] = useState<string>(readQueryFromURL);

  // Une recherche mérite une fenêtre temporelle large : chercher dans les
  // 48 dernières heures seulement raterait l'essentiel de ce que l'utilisateur
  // a en tête.
  const SEARCH_WINDOW_HOURS = 720;
  const effectiveSinceHours = serverQuery ? Math.max(filters.depuis_heures, SEARCH_WINDOW_HOURS) : filters.depuis_heures;

  // L'URL reflète ce qui est affiché, pour qu'une vue se partage telle quelle.
  // Le département et la recherche en étaient absents : « la carte du Finistère
  // filtrée sur les crues » n'était pas un lien qu'on pouvait envoyer.
  useEffect(() => {
    const qs = serialiserEtat({ filters, dept: selectedDept, q: serverQuery });
    const newUrl = qs ? `?${qs}` : window.location.pathname;
    // replaceState et non pushState : chaque frappe dans la recherche
    // empilerait sinon une entrée d'historique, et le bouton « retour »
    // deviendrait inutilisable.
    window.history.replaceState(null, "", newUrl);
  }, [filters, selectedDept, serverQuery]);

  // SWR key uses stable primitive values (no datetime string that changes every render)
  const swrKey = ["events", filters.categories, filters.gravite_min, effectiveSinceHours, serverQuery, historyDate?.toISOString() ?? null];

  const buildParams = useCallback(
    (offset: number) => {
      const base = {
        categories: filters.categories,
        gravite_min: filters.gravite_min > 0 ? filters.gravite_min : undefined,
        limit: EVENTS_PAGE_SIZE,
        offset,
        q: serverQuery || undefined,
      };
      if (historyDate) {
        const depuis = new Date(historyDate);
        const avant = new Date(historyDate);
        avant.setDate(avant.getDate() + 2);
        return { ...base, depuis: depuis.toISOString(), avant: avant.toISOString() };
      }
      return { ...base, depuis: new Date(Date.now() - effectiveSinceHours * 3600 * 1000).toISOString() };
    },
    [filters.categories, filters.gravite_min, effectiveSinceHours, serverQuery, historyDate]
  );

  const {
    data: eventsData,
    isLoading: eventsLoading,
    error: eventsError,
    mutate: mutateEvents,
  } = useSWR(swrKey, () => fetchEvents(buildParams(0)), {
    refreshInterval: historyDate ? 0 : REFRESH_INTERVAL,
    revalidateOnFocus: false,
    keepPreviousData: true,
  });

  /**
   * Rafraîchissement sans argument.
   *
   * `mutate` de SWR prend en premier paramètre les DONNÉES à substituer. Passé
   * tel quel à `onClick`, React lui transmet l'événement de clic : SWR range
   * alors un objet MouseEvent à la place de la réponse de l'API, et le premier
   * accès à `.events` casse le rendu (« can't access property "length",
   * P.events is undefined »).
   *
   * TypeScript ne peut pas l'attraper : une fonction déclarée `() => void`
   * reste assignable à un gestionnaire d'événement. On neutralise donc le
   * problème ici, à la source, plutôt que dans chaque composant qui reçoit ce
   * rappel — sans quoi il faudrait y penser à chaque nouveau bouton.
   */
  const refreshEvents = useCallback(() => {
    void mutateEvents();
  }, [mutateEvents]);

  // Pages suivantes chargées à la demande, empilées sous la première.
  const [extraEvents, setExtraEvents] = useState<Event[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState(false);

  // Tout changement de filtre/recherche repart de la première page.
  const swrKeyStr = JSON.stringify(swrKey);
  useEffect(() => {
    setExtraEvents([]);
    setMoreError(false);
  }, [swrKeyStr]);

  // `?.` jusqu'au bout : une réponse dépourvue de `events` ne doit pas casser
  // le rendu, même si `fetchEvents` la rejette désormais en amont.
  const loadedCount = (eventsData?.events?.length ?? 0) + extraEvents.length;
  const hasMore = Boolean(eventsData) && loadedCount < (eventsData?.total ?? 0);

  const handleLoadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    setMoreError(false);
    try {
      const next = await fetchEvents(buildParams(loadedCount));
      setExtraEvents((prev) => {
        // Filet anti-doublon : une ingestion entre deux pages peut décaler la
        // fenêtre et renvoyer un événement déjà présent.
        const seen = new Set([...(eventsData?.events ?? []), ...prev].map((e) => e.id));
        return [...prev, ...next.events.filter((e) => !seen.has(e.id))];
      });
    } catch {
      setMoreError(true);
    } finally {
      setLoadingMore(false);
    }
  }, [loadingMore, hasMore, buildParams, loadedCount, eventsData]);

  // Marqueurs de la carte : source dédiée et complète, indépendante de la
  // pagination du fil (sinon il faudrait « charger plus » pour voir ses
  // points). Charge utile réduite — pas de résumé IA.
  const { data: mapData } = useSWR(
    ["map", filters.categories, filters.gravite_min, filters.depuis_heures, historyDate?.toISOString() ?? null],
    () =>
      fetchMapEvents({
        categories: filters.categories,
        gravite_min: filters.gravite_min > 0 ? filters.gravite_min : undefined,
        depuis: historyDate
          ? new Date(historyDate).toISOString()
          : new Date(Date.now() - filters.depuis_heures * 3600 * 1000).toISOString(),
      }),
    { refreshInterval: historyDate ? 0 : REFRESH_INTERVAL, revalidateOnFocus: false, keepPreviousData: true }
  );

  const { data: healthData } = useSWR("health", fetchHealth, {
    refreshInterval: REFRESH_INTERVAL,
    revalidateOnFocus: false,
  });

  const [selectedEvent, setSelectedEvent] = useState<Event | null>(null);
  const [mobileView, setMobileView] = useState<"map" | "feed">("map");
  // Menu « ⋯ » mobile : Stats, Tendances, RSS, Partager et CSV sont des liens
  // desktop-only (hidden md:flex) — sans ce menu, ils sont inaccessibles au
  // téléphone.
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const ingestTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  // Dark mode: sync with localStorage on mount
  useEffect(() => {
    const stored = lireStockage("theme");
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
        ecrireStockage("theme", "dark");
      } else {
        document.documentElement.classList.remove("dark");
        ecrireStockage("theme", "light");
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
    const base = [...(eventsData?.events ?? []), ...extraEvents];
    if (liveEvents.length === 0) return base;
    const existingIds = new Set(base.map((e) => e.id));
    const fresh = liveEvents.filter((e) => !existingIds.has(e.id));
    return fresh.length > 0 ? [...fresh, ...base] : base;
  }, [eventsData?.events, extraEvents, liveEvents]);

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

  // La carte s'appuie sur sa source dédiée ; les événements arrivés en direct
  // (SSE) y sont ajoutés immédiatement sans attendre le prochain cycle.
  const localEvents = useMemo(() => {
    const base = mapData ?? allEvents.filter((e) => e.lieu_lat !== null && e.lieu_lon !== null);
    const known = new Set(base.map((e) => e.id));
    const liveLocated = liveEvents.filter(
      (e) => !known.has(e.id) && e.lieu_lat !== null && e.lieu_lon !== null
    );
    return liveLocated.length > 0 ? [...liveLocated, ...base] : base;
  }, [mapData, allEvents, liveEvents]);

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
    const base = "(ai)Faire Info";
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
    // L'amorçage de la mémoire et le tri vivent dans evenementsAAlerter, où ils
    // sont couverts par des tests : la subtilité — n'amorcer que sur un lot non
    // vide — n'était pas vérifiable tant qu'elle restait dans cet effet.
    const { memoire, aAlerter } = evenementsAAlerter(
      seenEventIdsRef.current, allEvents, alertSettings,
    );
    seenEventIdsRef.current = memoire;
    aAlerter.forEach(sendEventNotification);
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

  const togglePinDept = useCallback(() => {
    if (!selectedDept) return;
    setPinnedDept((prev) => {
      if (prev === selectedDept) {
        effacerStockage("pinnedDept");
        return null;
      }
      ecrireStockage("pinnedDept", selectedDept);
      return selectedDept;
    });
  }, [selectedDept]);

  const clearDept = useCallback(() => {
    setSelectedDept(null);
    setPinnedDept((prev) => {
      if (prev) effacerStockage("pinnedDept");
      return null;
    });
  }, []);

  // Fil filtré quand un département est sélectionné : ses événements + les
  // nationaux (qui concernent tout le monde). La carte, elle, garde tout.
  const feedEvents = useMemo(() => {
    if (!selectedDept) return allEvents;
    return allEvents.filter(
      (e) =>
        (e.lieu_code_insee?.startsWith(selectedDept) ?? false) ||
        e.lieu_niveau === "national"
    );
  }, [allEvents, selectedDept]);

  return (
    <div className="flex flex-col h-app overflow-hidden bg-gray-50 dark:bg-gray-900">
      {/*
        En-tête en DEUX BANDES distinctes, et non une seule ligne où tout se
        dispute la place :
          1. identité + outils + état — des éléments courts, qui tiennent
             ensemble et se replient naturellement ;
          2. les filtres — seize pastilles, deux groupes de boutons : un bloc
             qui a besoin de toute la largeur pour se déployer.

        Les mêler faisait des filtres le seul élément compressible : ils
        absorbaient tout le manque de place et s'écrasaient en une colonne
        d'une pastille par ligne. À 1100 px, l'en-tête atteignait 799 px de
        haut sur une fenêtre de 900 (mesuré le 03/08/2026).

        Deux bandes séparées rendent cela structurellement impossible : chaque
        bande dispose de la largeur entière et se replie pour son propre
        compte. Aucun seuil de largeur, aucun `order` ni `contents` — la
        disposition découle de ce que les éléments SONT, pas d'une correction
        appliquée à partir d'une certaine taille d'écran.
      */}
      <header className="flex flex-col gap-1.5 px-3 py-2 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 shadow-xs z-10 shrink-0">
        {/* Bande 1 — identité, outils, état */}
        <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center mr-4">
          <Wordmark taille="md" infoResponsive />
        </div>
        {maxGravite >= 2 && (
          <span
            className="hidden sm:inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-semibold motion-safe:animate-pulse"
            style={{
              backgroundColor: GRAVITE_CONFIG[maxGravite]?.color,
              color: readableTextColor(GRAVITE_CONFIG[maxGravite]?.color ?? "#6B7280"),
            }}
            title={GRAVITE_CONFIG[maxGravite]?.label}
          >
            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
            {GRAVITE_CONFIG[maxGravite]?.label}
          </span>
        )}
        <AlertSettings onChange={setAlertSettings} />
        <PushSettings pinnedDept={pinnedDept} />
        <button
          onClick={() => {
            navigator.clipboard
              .writeText(window.location.href)
              .then(() => toast("Lien copié dans le presse-papiers ✓", "success"))
              .catch(() => toast("Impossible de copier le lien", "error"));
          }}
          aria-label="Copier le lien avec les filtres actuels"
          className="hidden md:flex items-center gap-1 text-xs px-2 py-1 rounded-sm border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
          title="Copier le lien avec les filtres actuels"
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
          </svg>
          <span className="hidden lg:inline">Partager</span>
        </button>
        {allEvents.length > 0 && (
          <button
            onClick={() => {
              exportToCSV(allEvents);
              toast(`${allEvents.length} événement${allEvents.length > 1 ? "s" : ""} exporté${allEvents.length > 1 ? "s" : ""} en CSV`, "success");
            }}
            aria-label={`Télécharger ${allEvents.length} événements en CSV`}
            className="hidden lg:flex items-center gap-1 text-xs px-2 py-1 rounded-sm border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            title={`Télécharger ${allEvents.length} événements en CSV`}
          >
            <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            CSV
          </button>
        )}
        {/* FastAPI attend des paramètres répétés (?categories=a&categories=b),
            pas une liste jointe par virgules (sinon 422). Filtre inclus
            uniquement quand une sélection partielle est active. */}
        <a
          href={`${API_BASE_URL}/feed.rss${
            filters.categories.length !== ALL_CATEGORIES.length
              ? "?" + filters.categories.map((c) => `categories=${c}`).join("&")
              : ""
          }`}
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Flux RSS Atom (filtre catégories actuel)"
          className="hidden md:flex items-center gap-1 text-xs px-2 py-1 rounded-sm border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
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
          className="hidden md:flex items-center gap-1 text-xs px-2 py-1 rounded-sm border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          title="Statistiques"
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
          <span className="hidden lg:inline">Stats</span>
        </a>
        <a
          href="/tendances"
          className="hidden md:flex items-center gap-1 text-xs px-2 py-1 rounded-sm border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          title="Tendances (historique quotidien)"
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
          </svg>
          <span className="hidden lg:inline">Tendances</span>
        </a>
        {/* Menu mobile ⋯ : donne accès aux liens masqués sur petit écran */}
        <div className="relative md:hidden ml-auto">
          <button
            onClick={() => setMobileMenuOpen((v) => !v)}
            aria-label="Plus d'options"
            aria-expanded={mobileMenuOpen}
            className="flex items-center justify-center w-8 h-8 rounded-sm border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
          >
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
              <path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
            </svg>
          </button>
          {mobileMenuOpen && (
            <>
              {/* Voile : ferme le menu au tap en dehors */}
              <div className="fixed inset-0 z-40" onClick={() => setMobileMenuOpen(false)} aria-hidden="true" />
              <div className="absolute right-0 top-9 z-50 w-48 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg py-1">
                <a
                  href="/stats"
                  className="block px-3 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                >
                  📊 Statistiques
                </a>
                <a
                  href="/tendances"
                  className="block px-3 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                >
                  📈 Tendances
                </a>
                <a
                  href={`${API_BASE_URL}/feed.rss${
                    filters.categories.length !== ALL_CATEGORIES.length
                      ? "?" + filters.categories.map((c) => `categories=${c}`).join("&")
                      : ""
                  }`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block px-3 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                >
                  📡 Flux RSS
                </a>
                <button
                  onClick={() => {
                    setMobileMenuOpen(false);
                    navigator.clipboard
                      .writeText(window.location.href)
                      .then(() => toast("Lien copié dans le presse-papiers ✓", "success"))
                      .catch(() => toast("Impossible de copier le lien", "error"));
                  }}
                  className="block w-full text-left px-3 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                >
                  🔗 Partager le lien
                </button>
                {allEvents.length > 0 && (
                  <button
                    onClick={() => {
                      setMobileMenuOpen(false);
                      exportToCSV(allEvents);
                      toast(`${allEvents.length} événement${allEvents.length > 1 ? "s" : ""} exporté${allEvents.length > 1 ? "s" : ""} en CSV`, "success");
                    }}
                    className="block w-full text-left px-3 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                  >
                    ⬇️ Export CSV
                  </button>
                )}
              </div>
            </>
          )}
        </div>
        <ShortcutsHelp />
        <button
          onClick={toggleDark}
          aria-label={darkMode ? "Passer en mode clair" : "Passer en mode sombre"}
          className="flex items-center justify-center w-7 h-7 rounded-sm border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
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
            <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300 text-[10px] font-semibold uppercase tracking-wide">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
              En direct
            </span>
          )}
          {eventsError && allEvents.length > 0 && (
            <span className="text-xs text-amber-600 dark:text-amber-400 flex items-center gap-1" title="Données potentiellement périmées — la dernière mise à jour a échoué">
              <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
              </svg>
              Données possiblement périmées
            </span>
          )}
          <span className="text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap">
            {eventsData
              ? localEvents.length > 0
                ? `${eventsData.total} événement${eventsData.total > 1 ? "s" : ""} (${localEvents.length} localisé${localEvents.length > 1 ? "s" : ""} · ${nationalEvents.length} national${nationalEvents.length > 1 ? "aux" : ""})`
                : `${eventsData.total} événement${eventsData.total > 1 ? "s" : ""} · tout national`
              : eventsLoading
              ? "Chargement…"
              : ""}
          </span>
        </div>
        </div>

        {/* Bande 2 — les filtres, sur toute la largeur. Une seule instance du
            composant : sur mobile il n'affiche que son bouton « Filtres », qui
            déplie le reste sur place. */}
        <div className="flex">
          <FilterBar
            filters={filters}
            onCategoriesChange={handleCategoriesChange}
            onGraviteChange={handleGraviteChange}
            onDepuisHeuresChange={handleDepuisHeuresChange}
            onRefresh={refreshEvents}
            onResetFilters={handleResetFilters}
            isLoading={eventsLoading}
            eventCounts={eventCounts}
            selectedDept={selectedDept}
          />
        </div>
      </header>

      <OfflineIndicator />

      {/* Mobile toggle bar */}
      <div className="flex md:hidden border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shrink-0">
        <button
          onClick={() => setMobileView("map")}
          className={`flex-1 py-2.5 text-xs font-medium flex items-center justify-center gap-1.5 transition-colors ${
            mobileView === "map" ? "text-blue-700 dark:text-blue-300 border-b-2 border-blue-700 bg-blue-50 dark:bg-blue-900/30" : "text-gray-500 dark:text-gray-400"
          }`}
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
          </svg>
          Carte ({localEvents.length})
        </button>
        <button
          onClick={() => setMobileView("feed")}
          className={`flex-1 py-2.5 text-xs font-medium flex items-center justify-center gap-1.5 transition-colors ${
            mobileView === "feed" ? "text-blue-700 dark:text-blue-300 border-b-2 border-blue-700 bg-blue-50 dark:bg-blue-900/30" : "text-gray-500 dark:text-gray-400"
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
            <div className="flex items-center justify-between px-3 py-1.5 bg-amber-50 dark:bg-amber-900/30 border-b border-amber-200 dark:border-amber-800 shrink-0">
              <span className="text-xs text-amber-700 dark:text-amber-300 font-medium">
                ⏪ {historyDate.toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" })} — {new Date(historyDate.getTime() + 2 * 86400000).toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}
              </span>
              <button
                onClick={() => setHistoryDate(null)}
                className="text-amber-400 dark:text-amber-500 hover:text-amber-600 dark:hover:text-amber-200 transition-colors"
                title="Retour au live"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          )}
          {selectedDept && (
            <div className="flex items-center justify-between gap-2 px-3 py-1.5 bg-blue-50 dark:bg-blue-900/30 border-b border-blue-200 dark:border-blue-800 shrink-0">
              <span className="text-xs text-blue-700 dark:text-blue-300 font-medium truncate">
                {DEPT_CODE_TO_NAME[selectedDept] ?? `Dép. ${selectedDept}`} ({selectedDept}) —{" "}
                {deptEvents.length} événement{deptEvents.length !== 1 ? "s" : ""}
              </span>
              <div className="flex items-center gap-1.5 shrink-0">
                <button
                  onClick={togglePinDept}
                  className={`text-xs transition-colors ${
                    pinnedDept === selectedDept
                      ? "text-blue-700 dark:text-blue-200"
                      : "text-blue-300 dark:text-blue-500 hover:text-blue-600 dark:hover:text-blue-300"
                  }`}
                  title={
                    pinnedDept === selectedDept
                      ? "Département épinglé — cliquer pour désépingler"
                      : "Épingler ce département (retrouvé à chaque visite)"
                  }
                  aria-pressed={pinnedDept === selectedDept}
                >
                  📌
                </button>
                <button
                  onClick={clearDept}
                  className="text-blue-400 hover:text-blue-600 dark:hover:text-blue-200 transition-colors"
                  title="Effacer le filtre département"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>
          )}
          {/* Timeline et stats : desktop uniquement. Sur mobile ces deux
              barres mangeaient 154 px des ~550 px de la colonne, ne laissant
              que ~130 px au fil (une carte visible). Leurs compteurs sont
              déjà repris par la barre d'onglets mobile et par les onglets du
              fil (« Tous / Carte / National »). */}
          <div className="hidden md:block shrink-0">
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
          </div>
          <DailyBrief pinnedDept={pinnedDept} />
          <EventFeed
            events={feedEvents}
            isLoading={eventsLoading}
            error={eventsError}
            selectedEventId={selectedEvent?.id ?? null}
            onSelectEvent={setSelectedEvent}
            onRetry={refreshEvents}
            serverQuery={serverQuery}
            liveEventIds={new Set(liveEvents.map((e) => e.id))}
            onSearchChange={setServerQuery}
            totalAvailable={eventsData?.total ?? 0}
            hasMore={hasMore}
            loadingMore={loadingMore}
            moreError={moreError}
            onLoadMore={handleLoadMore}
            onRefresh={refreshEvents}
          />
        </aside>
      </main>

      {/* Status bar */}
      <StatusBar
        connectors={healthData?.connectors ?? []}
        nextIngestAt={healthData?.next_ingest_at ?? null}
        ingestHours={healthData?.ingest_hours}
        ingestTimezone={healthData?.ingest_timezone}
        hourlyAlerts={healthData?.hourly_alerts}
        onTriggerIngest={INGEST_BUTTON_ENABLED ? handleTriggerIngest : undefined}
      />

      <Toaster />

      {/* Annonce l'arrivée d'événements temps réel aux lecteurs d'écran */}
      <div aria-live="polite" className="sr-only">
        {liveEvents.length > 0 &&
          `${liveEvents.length} nouveau${liveEvents.length > 1 ? "x" : ""} événement${liveEvents.length > 1 ? "s" : ""} reçu${liveEvents.length > 1 ? "s" : ""}`}
      </div>
    </div>
  );
}
