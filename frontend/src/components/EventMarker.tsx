"use client";

import { useCallback, useMemo, useState } from "react";
import { Marker, Popup } from "react-leaflet";
import { format, parseISO } from "date-fns";
import { fr } from "date-fns/locale";
import type { DivIcon } from "leaflet";

import { fetchEventDetail } from "@/lib/api";
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

function createMarkerIcon(event: Event, isSelected?: boolean): DivIcon | null {
  if (typeof window === "undefined") return null;
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const L = require("leaflet") as typeof import("leaflet");

  const color = graviteColor(event.gravite);
  const letter = CATEGORY_CONFIG[event.categorie]?.letter ?? event.categorie[0].toUpperCase();
  const size = event.gravite >= 2 ? 28 : 22;
  const extraClass = isSelected ? " faire-marker--selected" : "";

  return L.divIcon({
    className: "",
    html: `<div class="faire-marker${extraClass}" style="width:${size}px;height:${size}px;background:${color};font-size:${size <= 22 ? 9 : 11}px;--m:${color};">${letter}</div>`,
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
  isSelected?: boolean;
  onSelect?: (event: Event) => void;
}

export default function EventMarker({ event, isSelected, onSelect }: EventMarkerProps) {
  const icon = useMemo(
    () => createMarkerIcon(event, isSelected),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [event.gravite, event.categorie, isSelected]
  );

  // Les marqueurs viennent de /events/map, qui omet le résumé et les tags pour
  // alléger la charge utile. Sans complément, la bulle se réduisait à un titre
  // que l'utilisateur venait déjà de lire sur la carte — le clic ne rapportait
  // rien, sauf pour les vigilances météo dont le titre porte toute l'info.
  const [detail, setDetail] = useState<Event | null>(null);
  const [chargement, setChargement] = useState(false);
  const [echec, setEchec] = useState(false);

  const complet = detail ?? event;
  const detailManquant = event.resume_ia === null && detail === null;

  const chargerDetail = useCallback(() => {
    if (!detailManquant || chargement) return;
    setChargement(true);
    setEchec(false);
    fetchEventDetail(event.id)
      .then(setDetail)
      .catch(() => setEchec(true))
      .finally(() => setChargement(false));
  }, [detailManquant, chargement, event.id]);

  if (event.lieu_lat === null || event.lieu_lon === null) return null;
  if (!icon) return null;

  const catConfig = CATEGORY_CONFIG[complet.categorie];
  const graviteConfig = GRAVITE_CONFIG[complet.gravite] ?? GRAVITE_CONFIG[0];
  const sourceLabel =
    complet.source === "presse_rss" && complet.auteur
      ? complet.auteur
      : SOURCE_LABELS[complet.source] ?? complet.source;

  return (
    <Marker
      position={[event.lieu_lat, event.lieu_lon]}
      icon={icon}
      eventHandlers={{
        click: () => onSelect?.(event),
        // La fiche n'est demandée qu'à l'ouverture de la bulle : charger les
        // résumés des centaines de marqueurs affichés reviendrait à annuler
        // l'allègement de /events/map.
        popupopen: chargerDetail,
      }}
    >
      <Popup minWidth={280} maxWidth={300}>
        <div className="text-sm font-sans">
          {/* Header */}
          <div className="px-3 pt-3 pb-2">
            <a
              href={event.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-semibold text-gray-900 dark:text-gray-100 hover:text-blue-700 leading-snug block"
            >
              {complet.titre}
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
            {complet.lieu_nom && (
              <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 text-xs">
                {complet.lieu_nom}
              </span>
            )}
          </div>

          {/* Résumé IA — complété à l'ouverture pour les marqueurs de la carte */}
          {complet.resume_ia ? (
            <div className="px-3 pb-2">
              <p className="text-gray-700 dark:text-gray-200 leading-snug">{complet.resume_ia}</p>
              <span className="text-xs text-gray-500 dark:text-gray-400 italic mt-0.5 block">résumé automatique</span>
            </div>
          ) : chargement ? (
            <div className="px-3 pb-2" aria-live="polite">
              <div className="h-3 rounded-sm bg-gray-200 dark:bg-gray-700 animate-pulse mb-1.5" />
              <div className="h-3 w-3/4 rounded-sm bg-gray-200 dark:bg-gray-700 animate-pulse" />
              <span className="sr-only">Chargement du résumé…</span>
            </div>
          ) : echec ? (
            <div className="px-3 pb-2">
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Résumé indisponible.{" "}
                <button
                  type="button"
                  onClick={chargerDetail}
                  className="underline hover:text-blue-700 dark:hover:text-blue-300"
                >
                  Réessayer
                </button>
              </p>
            </div>
          ) : null}

          {/* Tags */}
          {complet.tags && complet.tags.length > 0 && (
            <div className="px-3 pb-2 flex flex-wrap gap-1">
              {complet.tags.map((tag) => (
                <span
                  key={tag}
                  className="px-1.5 py-0.5 rounded-sm bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 text-xs"
                >
                  #{tag}
                </span>
              ))}
            </div>
          )}

          {/* Footer */}
          <div className="px-3 pb-3 border-t border-gray-100 dark:border-gray-700 pt-2 flex justify-between text-xs text-gray-500 dark:text-gray-400">
            <span>{sourceLabel}</span>
            <span>{formatDate(complet.date_publication)}</span>
          </div>
        </div>
      </Popup>
    </Marker>
  );
}
