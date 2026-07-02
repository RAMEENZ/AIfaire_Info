"use client";

import { useEffect, useRef, useState } from "react";
import { format, formatDistanceToNow, parseISO } from "date-fns";
import { fr } from "date-fns/locale";

import { ALL_CATEGORIES, CATEGORY_CONFIG, GRAVITE_CONFIG, SOURCE_LABELS } from "@/lib/constants";
import { SORT_OPTIONS, SortMode, sortComparator } from "@/lib/sortEvents";
import { Categorie, Event } from "@/lib/types";

type Tab = "all" | "local" | "national";

const PAGE_SIZE = 50;

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
  liveEventIds?: Set<string>;
}

function formatRelative(iso: string): string {
  try {
    return formatDistanceToNow(parseISO(iso), { locale: fr, addSuffix: true });
  } catch {
    return iso;
  }
}

function sourceLabelOf(event: Event): string {
  return event.source === "presse_rss" && event.auteur
    ? event.auteur
    : SOURCE_LABELS[event.source] ?? event.source;
}

interface CollapsedEvent {
  event: Event;
  duplicates: Event[];
}

function collapseByCluster(events: Event[]): CollapsedEvent[] {
  const result: CollapsedEvent[] = [];
  const representativeIndex = new Map<string, number>();

  for (const event of events) {
    if (event.cluster_id === null) {
      result.push({ event, duplicates: [] });
      continue;
    }
    const existing = representativeIndex.get(event.cluster_id);
    if (existing === undefined) {
      representativeIndex.set(event.cluster_id, result.length);
      result.push({ event, duplicates: [] });
    } else {
      const rep = result[existing];
      const alreadyListed =
        rep.event.source_url === event.source_url ||
        rep.duplicates.some((d) => d.source_url === event.source_url);
      if (!alreadyListed) {
        rep.duplicates.push(event);
      }
    }
  }

  return result;
}

function ShareButton({ eventId }: { eventId: string }) {
  const [copied, setCopied] = useState(false);
  const handleShare = (e: React.MouseEvent) => {
    e.stopPropagation();
    const url = `${window.location.origin}${window.location.pathname}?event=${eventId}`;
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  };
  return (
    <button
      onClick={handleShare}
      title="Copier le lien vers cet événement"
      className="text-gray-300 hover:text-blue-500 transition-colors flex-shrink-0"
    >
      {copied ? (
        <span className="text-green-500 text-[10px] font-semibold">✓</span>
      ) : (
        <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
        </svg>
      )}
    </button>
  );
}

function EventCard({
  event,
  isLive,
  selected,
  onSelect,
  activeTag,
  onTagClick,
  duplicates = [],
}: {
  event: Event;
  isLive?: boolean;
  selected?: boolean;
  onSelect?: (event: Event) => void;
  activeTag?: string | null;
  onTagClick?: (tag: string) => void;
  duplicates?: Event[];
}) {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const catConfig = CATEGORY_CONFIG[event.categorie];
  const sourceLabel = sourceLabelOf(event);
  const duplicateCount = duplicates.length;
  const isLocalized = event.lieu_lat !== null && event.lieu_lon !== null;
  const borderColor = GRAVITE_BORDER[event.gravite] ?? "transparent";

  const toggleSources = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    setSourcesOpen((open) => !open);
  };

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
        {isLive && (
          <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-green-100 text-green-700 uppercase tracking-wide">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
            Nouveau
          </span>
        )}
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

        {event.tags && event.tags.length > 0 && (
          <div className="w-full flex flex-wrap gap-1 mt-1">
            {event.tags.slice(0, 4).map((tag) => (
              <button
                key={tag}
                onClick={(ev) => { ev.stopPropagation(); onTagClick?.(tag); }}
                className={`px-1 py-0.5 rounded text-xs leading-none transition-colors ${
                  activeTag === tag
                    ? "bg-blue-100 text-blue-700 font-medium"
                    : "bg-gray-100 text-gray-500 hover:bg-gray-200"
                }`}
              >
                #{tag}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="mt-1.5 flex items-center justify-between gap-2 text-xs text-gray-400">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="inline-block px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 font-medium shrink-0 truncate max-w-[120px]">
            {sourceLabel}
          </span>
          {duplicateCount > 0 && (
            <button
              onClick={toggleSources}
              aria-expanded={sourcesOpen}
              title={sourcesOpen ? "Masquer les autres sources" : "Afficher les autres sources"}
              className="inline-block px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 hover:bg-gray-200 transition-colors shrink-0"
            >
              +{duplicateCount} {duplicateCount > 1 ? "autres sources" : "autre source"}
            </button>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <time
            dateTime={event.date_publication}
            className="text-right"
            title={(() => {
              try { return format(parseISO(event.date_publication), "d MMM yyyy HH:mm", { locale: fr }); }
              catch { return event.date_publication; }
            })()}
          >
            {formatRelative(event.date_publication)}
          </time>
          <ShareButton eventId={event.id} />
        </div>
      </div>

      {duplicateCount > 0 && sourcesOpen && (
        <ul className="mt-1.5 space-y-1 border-t border-gray-100 pt-1.5">
          {duplicates.map((dup) => (
            <li key={dup.id} className="flex items-center gap-1.5 text-xs text-gray-500">
              <span className="truncate">{sourceLabelOf(dup)}</span>
              <a
                href={dup.source_url}
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
      )}
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

function CategoryFilterBar({
  activeCategories,
  onToggle,
  onClear,
  eventCounts,
}: {
  activeCategories: Set<Categorie>;
  onToggle: (cat: Categorie) => void;
  onClear: () => void;
  eventCounts: Partial<Record<Categorie, number>>;
}) {
  return (
    <div className="px-2 py-1.5 border-b border-gray-100 bg-gray-50">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-gray-400 font-medium uppercase tracking-wide">Catégories</span>
        {activeCategories.size > 0 && (
          <button onClick={onClear} className="text-[10px] text-blue-500 hover:underline">
            Effacer
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-1">
        {ALL_CATEGORIES.map((cat) => {
          const cfg = CATEGORY_CONFIG[cat];
          const active = activeCategories.has(cat);
          const count = eventCounts[cat] ?? 0;
          if (count === 0 && !active) return null;
          return (
            <button
              key={cat}
              onClick={() => onToggle(cat)}
              title={cfg.label}
              className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium transition-colors ${
                active
                  ? "text-white"
                  : "bg-white text-gray-500 border border-gray-200 hover:border-gray-300"
              }`}
              style={active ? { backgroundColor: cfg.color } : undefined}
            >
              <span>{cfg.icon}</span>
              <span className="hidden sm:inline">{cfg.label}</span>
              {count > 0 && <span className={active ? "opacity-80" : "opacity-60"}>{count}</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function EventFeed({ events, isLoading, error, selectedEventId, onSelectEvent, onRetry, liveEventIds }: EventFeedProps) {
  const [tab, setTab] = useState<Tab>("all");
  const [sortMode, setSortMode] = useState<SortMode>("gravite");
  const [search, setSearch] = useState("");
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [activeCategories, setActiveCategories] = useState<Set<Categorie>>(new Set());
  const [showFilters, setShowFilters] = useState(false);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (activeTag && !events.some((e) => e.tags?.includes(activeTag))) {
      setActiveTag(null);
    }
  }, [events, activeTag]);

  // Réinitialise la pagination quand les filtres ou le tri changent.
  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [tab, search, activeTag, activeCategories, sortMode]);

  useEffect(() => {
    if (selectedEventId == null) return;
    const el = document.getElementById(`event-card-${selectedEventId}`);
    el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [selectedEventId]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const inInput = document.activeElement?.tagName === "INPUT";
      if (e.key === "/" && !inInput) {
        e.preventDefault();
        searchInputRef.current?.focus();
      } else if (e.key === "Escape" && document.activeElement === searchInputRef.current) {
        setSearch("");
        searchInputRef.current?.blur();
      } else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !inInput && onSelectEvent) {
        e.preventDefault();
        const cards = Array.from(document.querySelectorAll<HTMLElement>("[id^='event-card-']"));
        if (cards.length === 0) return;
        const sortedIds = cards.map((el) => el.id.replace("event-card-", ""));
        const currentIdx = selectedEventId ? sortedIds.indexOf(selectedEventId) : -1;
        const nextIdx =
          e.key === "ArrowDown"
            ? Math.min(currentIdx + 1, sortedIds.length - 1)
            : Math.max(currentIdx - 1, 0);
        if (nextIdx !== currentIdx && nextIdx >= 0) {
          cards[nextIdx].click();
        }
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedEventId]);

  const searchLower = search.trim().toLowerCase();

  const matchesSearch = (e: Event) => {
    if (!searchLower) return true;
    return (
      e.titre.toLowerCase().includes(searchLower) ||
      (e.lieu_nom?.toLowerCase().includes(searchLower) ?? false) ||
      (e.resume_ia?.toLowerCase().includes(searchLower) ?? false) ||
      (e.auteur?.toLowerCase().includes(searchLower) ?? false) ||
      (e.tags?.some((t) => t.toLowerCase().includes(searchLower)) ?? false)
    );
  };

  const searchFiltered = events
    .filter(matchesSearch)
    .filter((e) => !activeTag || (e.tags?.includes(activeTag) ?? false))
    .filter((e) => activeCategories.size === 0 || activeCategories.has(e.categorie));

  const localCount = searchFiltered.filter((e) => e.lieu_lat !== null && e.lieu_lon !== null).length;
  const nationalCount = searchFiltered.length - localCount;

  const filtered = searchFiltered.filter((e) => {
    if (tab === "local") return e.lieu_lat !== null && e.lieu_lon !== null;
    if (tab === "national") return e.lieu_lat === null || e.lieu_lon === null;
    return true;
  });

  const sorted = [...filtered].sort(sortComparator(sortMode));

  const collapsed = collapseByCluster(sorted);
  const visible = collapsed.slice(0, visibleCount);
  const hasMore = visibleCount < collapsed.length;

  // Comptage par catégorie (avant filtre catégorie, après autres filtres).
  const preCatFiltered = events
    .filter(matchesSearch)
    .filter((e) => !activeTag || (e.tags?.includes(activeTag) ?? false))
    .filter((e) => {
      if (tab === "local") return e.lieu_lat !== null && e.lieu_lon !== null;
      if (tab === "national") return e.lieu_lat === null || e.lieu_lon === null;
      return true;
    });
  const eventCounts: Partial<Record<Categorie, number>> = {};
  for (const e of preCatFiltered) {
    eventCounts[e.categorie] = (eventCounts[e.categorie] ?? 0) + 1;
  }

  const toggleCategory = (cat: Categorie) => {
    setActiveCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  const tabClass = (t: Tab) =>
    `px-2 py-0.5 text-xs rounded transition-colors ${
      tab === t
        ? "bg-blue-100 text-blue-700 font-medium"
        : "text-gray-500 hover:bg-gray-100"
    }`;

  const hasActiveFilters = activeCategories.size > 0 || !!activeTag;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Alert banner */}
      <AlertBanner events={events} onSelect={onSelectEvent} />

      {/* Header + tabs */}
      <div className="px-4 pt-2.5 pb-2 border-b border-gray-200 flex-shrink-0">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-gray-700">Actualités</h2>
          <div className="flex items-center gap-1.5">
            {activeTag && (
              <button
                onClick={() => setActiveTag(null)}
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 text-xs font-medium hover:bg-blue-200 transition-colors"
              >
                #{activeTag}
                <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
            {collapsed.length > 0 && (
              <span className="text-xs text-gray-400">{collapsed.length}</span>
            )}
            <select
              value={sortMode}
              onChange={(e) => setSortMode(e.target.value as SortMode)}
              className="text-[10px] px-1 py-0.5 rounded border border-gray-200 bg-gray-50 text-gray-600 focus:outline-none focus:border-blue-400 cursor-pointer"
              title="Ordre de tri du fil"
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
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
        <div className="flex gap-1 items-center">
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
          <button
            onClick={() => setShowFilters((v) => !v)}
            className={`ml-auto px-2 py-0.5 text-xs rounded transition-colors flex items-center gap-1 ${
              showFilters || hasActiveFilters
                ? "bg-blue-100 text-blue-700 font-medium"
                : "text-gray-500 hover:bg-gray-100"
            }`}
            title="Filtrer par catégorie"
          >
            <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2a1 1 0 01-.293.707L13 13.414V19a1 1 0 01-.553.894l-4 2A1 1 0 017 21v-7.586L3.293 6.707A1 1 0 013 6V4z" />
            </svg>
            {hasActiveFilters ? `Filtres (${activeCategories.size + (activeTag ? 1 : 0)})` : "Filtrer"}
          </button>
        </div>
      </div>

      {/* Category filter bar (collapsible) */}
      {showFilters && (
        <CategoryFilterBar
          activeCategories={activeCategories}
          onToggle={toggleCategory}
          onClear={() => setActiveCategories(new Set())}
          eventCounts={eventCounts}
        />
      )}

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
            {searchLower || hasActiveFilters ? (
              <>
                <span>Aucun résultat pour ces filtres</span>
                <button
                  onClick={() => { setSearch(""); setActiveCategories(new Set()); setActiveTag(null); }}
                  className="text-xs text-blue-500 hover:underline"
                >
                  Effacer les filtres
                </button>
              </>
            ) : (
              <span>Aucun événement</span>
            )}
          </div>
        )}

        {visible.map(({ event, duplicates }) => (
          <EventCard
            key={event.id}
            event={event}
            isLive={liveEventIds?.has(event.id) ?? false}
            selected={event.id === selectedEventId}
            onSelect={onSelectEvent}
            activeTag={activeTag}
            onTagClick={(tag) => setActiveTag(activeTag === tag ? null : tag)}
            duplicates={duplicates}
          />
        ))}

        {/* Charger plus */}
        {hasMore && (
          <div className="px-4 py-3 border-t border-gray-100 text-center">
            <button
              onClick={() => setVisibleCount((v) => v + PAGE_SIZE)}
              className="text-xs text-blue-600 hover:text-blue-800 hover:underline"
            >
              Charger {Math.min(PAGE_SIZE, collapsed.length - visibleCount)} de plus
              <span className="text-gray-400 ml-1">({visibleCount} / {collapsed.length})</span>
            </button>
          </div>
        )}

        {collapsed.length > 8 && !hasMore && (
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
