"use client";

import { useEffect, useRef } from "react";
import { Marker, Popup } from "react-leaflet";
import { format, parseISO } from "date-fns";
import { fr } from "date-fns/locale";
import type { DivIcon } from "leaflet";

import { CATEGORY_CONFIG, GRAVITE_CONFIG, SOURCE_LABELS } from "@/lib/constants";
import { Event } from "@/lib/types";

const GRAVITE_COLORS: Record<number, string> = {
  0: "#6B7280",
  1: "#F59E0B",
  2: "#F97316",
  3: "#EF4444",
};

function graviteColor(gravite: number): string {
  return GRAVITE_COLORS[gravite] ?? "#6B7280";
}

function createMarkerIcon(event: Event): DivIcon | null {
  if (typeof window === "undefined") return null;
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const L = require("leaflet") as typeof import("leaflet");

  const color = graviteColor(event.gravite);
  const letter = CATEGORY_CONFIG[event.categorie]?.letter ?? event.categorie[0].toUpperCase();
  const size = event.gravite >= 2 ? 28 : 22;

  return L.divIcon({
    className: "",
    html: `<div class="faire-marker" style="width:${size}px;height:${size}px;background:${color};font-size:${size <= 22 ? 9 : 11}px;">${letter}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    popupAnchor: [0, -(size / 2 + 4)],
  });
}

function formatDate(iso: string): string {
  try {
    return format(parseISO(iso), "d MMM yyyy 'à' HH:mm", { locale: fr });
  } catch {
    return iso;
  }
}

interface EventMarkerProps {
  event: Event;
}

export default function EventMarker({ event }: EventMarkerProps) {
  const iconRef = useRef<DivIcon | null>(null);

  if (!iconRef.current) {
    iconRef.current = createMarkerIcon(event);
  }

  useEffect(() => {
    iconRef.current = createMarkerIcon(event);
  }, [event.gravite, event.categorie]);

  if (event.lieu_lat === null || event.lieu_lon === null) return null;
  if (!iconRef.current) return null;

  const catConfig = CATEGORY_CONFIG[event.categorie];
  const graviteConfig = GRAVITE_CONFIG[event.gravite] ?? GRAVITE_CONFIG[0];
  const sourceLabel = SOURCE_LABELS[event.source] ?? event.source;

  return (
    <Marker
      position={[event.lieu_lat, event.lieu_lon]}
      icon={iconRef.current}
    >
      <Popup minWidth={280} maxWidth={300}>
        <div className="text-sm font-sans">
          {/* Header */}
          <div className="px-3 pt-3 pb-2">
            <a
              href={event.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-semibold text-gray-900 hover:text-blue-700 leading-snug block"
            >
              {event.titre}
            </a>
          </div>

          {/* Badges */}
          <div className="px-3 pb-2 flex flex-wrap gap-1">
            <span
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-white text-xs font-medium"
              style={{ backgroundColor: catConfig?.color ?? "#6B7280" }}
            >
              {catConfig?.icon} {catConfig?.label ?? event.categorie}
            </span>
            <span
              className="inline-flex items-center px-2 py-0.5 rounded-full text-white text-xs font-medium"
              style={{ backgroundColor: graviteConfig.color }}
            >
              {graviteConfig.label}
            </span>
            {event.lieu_nom && (
              <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-gray-100 text-gray-700 text-xs">
                {event.lieu_nom}
              </span>
            )}
          </div>

          {/* Résumé IA */}
          {event.resume_ia && (
            <div className="px-3 pb-2">
              <p className="text-gray-700 leading-snug">{event.resume_ia}</p>
              <span className="text-xs text-gray-400 italic mt-0.5 block">résumé automatique</span>
            </div>
          )}

          {/* Footer */}
          <div className="px-3 pb-3 border-t border-gray-100 pt-2 flex justify-between text-xs text-gray-500">
            <span>{sourceLabel}</span>
            <span>{formatDate(event.date_publication)}</span>
          </div>
        </div>
      </Popup>
    </Marker>
  );
}
