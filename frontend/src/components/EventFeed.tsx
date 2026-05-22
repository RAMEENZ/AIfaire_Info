"use client";

import { formatDistanceToNow, parseISO } from "date-fns";
import { fr } from "date-fns/locale";

import { CATEGORY_CONFIG, SOURCE_LABELS } from "@/lib/constants";
import { Event } from "@/lib/types";

interface EventFeedProps {
  events: Event[];
  isLoading: boolean;
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
  const sourceLabel = SOURCE_LABELS[event.source] ?? event.source;

  return (
    <article className="px-4 py-3 border-b border-gray-100 hover:bg-gray-50 transition-colors">
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

export default function EventFeed({ events, isLoading }: EventFeedProps) {
  const sorted = [...events].sort(
    (a, b) =>
      new Date(b.date_publication).getTime() -
      new Date(a.date_publication).getTime()
  );

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="px-4 py-2.5 border-b border-gray-200 flex items-center justify-between flex-shrink-0">
        <h2 className="text-sm font-semibold text-gray-700">
          Actualité nationale
        </h2>
        {sorted.length > 0 && (
          <span className="text-xs text-gray-400">{sorted.length}</span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
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
            Aucun événement national
          </div>
        )}

        {sorted.map((event) => (
          <EventCard key={event.id} event={event} />
        ))}
      </div>
    </div>
  );
}
