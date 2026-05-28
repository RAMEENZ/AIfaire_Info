"use client";

import { useEffect, useRef, useState } from "react";
import { MapContainer, TileLayer } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import type { Map as LeafletMap } from "leaflet";

import EventMarker from "./EventMarker";
import { CATEGORY_CONFIG, GRAVITE_CONFIG, FRANCE_CENTER, FRANCE_DEFAULT_ZOOM } from "@/lib/constants";
import { Event } from "@/lib/types";

interface FranceMapProps {
  events: Event[];
  selectedEvent?: Event | null;
  onSelectEvent?: (event: Event) => void;
}

const DOM_TOM = [
  { code: "971", name: "Guadeloupe",   center: [ 16.25, -61.55] as [number, number], zoom: 10 },
  { code: "972", name: "Martinique",   center: [ 14.65, -61.00] as [number, number], zoom: 10 },
  { code: "973", name: "Guyane",       center: [  4.00, -53.00] as [number, number], zoom:  7 },
  { code: "974", name: "Réunion",      center: [-21.10,  55.50] as [number, number], zoom: 10 },
  { code: "976", name: "Mayotte",      center: [-12.80,  45.15] as [number, number], zoom: 11 },
  { code: "975", name: "St-Pierre",    center: [ 46.90, -56.30] as [number, number], zoom: 11 },
  { code: "977", name: "St-Barth",     center: [ 17.90, -62.85] as [number, number], zoom: 13 },
  { code: "978", name: "St-Martin",    center: [ 18.07, -63.05] as [number, number], zoom: 12 },
  { code: "986", name: "Wallis-Futuna",center: [-13.30,-176.20] as [number, number], zoom: 11 },
  { code: "987", name: "Polynésie",    center: [-17.60,-149.40] as [number, number], zoom:  8 },
  { code: "988", name: "N-Calédonie",  center: [-20.90, 165.60] as [number, number], zoom:  8 },
];

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function createClusterCustomIcon(cluster: any) {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const L = require("leaflet") as typeof import("leaflet");
  const count: number = cluster.getChildCount();
  const size = count >= 50 ? 42 : count >= 20 ? 36 : count >= 10 ? 30 : 24;
  const fontSize = size <= 24 ? 10 : size <= 30 ? 11 : 13;
  return L.divIcon({
    className: "",
    html: `<div style="width:${size}px;height:${size}px;background:#1d4ed8;color:white;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:${fontSize}px;font-weight:700;border:2px solid white;box-shadow:0 1px 5px rgba(0,0,0,0.35)">${count}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function MapLegend() {
  const [open, setOpen] = useState(false);
  return (
    <div className="absolute bottom-7 right-2 z-[1000]">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-7 h-7 rounded-full bg-white border border-gray-200 shadow-md text-gray-600 hover:text-blue-700 text-xs font-bold flex items-center justify-center"
        title="Légende"
      >
        ?
      </button>
      {open && (
        <div className="absolute bottom-9 right-0 bg-white/95 backdrop-blur-sm border border-gray-200 rounded-lg shadow-lg p-3 w-52 text-xs">
          <p className="font-semibold text-gray-600 mb-2 uppercase tracking-wide text-[10px]">Catégories</p>
          <div className="grid grid-cols-2 gap-x-2 gap-y-1 mb-3">
            {(Object.entries(CATEGORY_CONFIG) as [string, typeof CATEGORY_CONFIG[keyof typeof CATEGORY_CONFIG]][]).map(([key, cfg]) => (
              <div key={key} className="flex items-center gap-1.5">
                <span
                  className="w-5 h-5 rounded-full flex items-center justify-center text-white font-bold flex-shrink-0"
                  style={{ backgroundColor: cfg.color, fontSize: 8 }}
                >
                  {cfg.letter}
                </span>
                <span className="text-gray-600 truncate">{cfg.label}</span>
              </div>
            ))}
          </div>
          <p className="font-semibold text-gray-600 mb-2 uppercase tracking-wide text-[10px]">Gravité</p>
          <div className="space-y-1">
            {([0, 1, 2, 3] as const).map((g) => (
              <div key={g} className="flex items-center gap-1.5">
                <span
                  className="w-3 h-3 rounded-full flex-shrink-0"
                  style={{ backgroundColor: GRAVITE_CONFIG[g].color }}
                />
                <span className="text-gray-600">{GRAVITE_CONFIG[g].label}</span>
              </div>
            ))}
          </div>
          <p className="mt-2 text-gray-400 text-[10px]">
            Cercle bleu = cluster (cliquez pour dézoomer)
          </p>
        </div>
      )}
    </div>
  );
}

export default function FranceMap({ events, selectedEvent, onSelectEvent }: FranceMapProps) {
  const mapRef = useRef<LeafletMap | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    import("leaflet").then((L) => {
      delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
        iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
        shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
      });
    });
  }, []);

  useEffect(() => {
    if (selectedEvent?.lieu_lat != null && selectedEvent?.lieu_lon != null) {
      const zoom =
        selectedEvent.lieu_niveau === "commune" ? 13
        : selectedEvent.lieu_niveau === "departement" ? 10
        : selectedEvent.lieu_niveau === "region" ? 8
        : 7;
      mapRef.current?.flyTo([selectedEvent.lieu_lat, selectedEvent.lieu_lon], zoom, { duration: 1.0 });
    }
  }, [selectedEvent]);

  const flyTo = (center: [number, number], zoom: number) => {
    mapRef.current?.flyTo(center, zoom, { duration: 1.2 });
  };

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <MapContainer
        center={FRANCE_CENTER}
        zoom={FRANCE_DEFAULT_ZOOM}
        minZoom={3}
        maxZoom={18}
        style={{ width: "100%", height: "100%" }}
        ref={mapRef}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MarkerClusterGroup
          chunkedLoading
          showCoverageOnHover={false}
          iconCreateFunction={createClusterCustomIcon}
          maxClusterRadius={50}
        >
          {events.map((event) => (
            <EventMarker
              key={event.id}
              event={event}
              isSelected={selectedEvent?.id === event.id}
              onSelect={onSelectEvent}
            />
          ))}
        </MarkerClusterGroup>
      </MapContainer>

      {/* Panneau de navigation DOM-TOM */}
      <div className="absolute bottom-7 left-2 z-[1000]">
        <div className="bg-white/90 backdrop-blur-sm border border-gray-200 rounded-lg shadow-md px-2 py-1.5">
          <p className="text-[9px] font-semibold text-gray-400 uppercase tracking-wide mb-1">DOM-TOM</p>
          <div className="flex flex-wrap gap-1 max-w-[200px]">
            {DOM_TOM.map((t) => (
              <button
                key={t.code}
                onClick={() => flyTo(t.center, t.zoom)}
                className="px-1.5 py-0.5 text-[10px] font-medium bg-gray-50 hover:bg-blue-50 border border-gray-200 rounded text-gray-600 hover:text-blue-700 transition-colors"
                title={`Aller sur ${t.name}`}
              >
                {t.name}
              </button>
            ))}
            <button
              onClick={() => flyTo(FRANCE_CENTER, FRANCE_DEFAULT_ZOOM)}
              className="px-1.5 py-0.5 text-[10px] font-medium bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors"
              title="Retour France métropolitaine"
            >
              ← Métropole
            </button>
          </div>
        </div>
      </div>

      <MapLegend />

      {events.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
          <div className="bg-white/80 backdrop-blur-sm rounded-xl px-6 py-5 text-center shadow-md max-w-xs">
            <div className="text-3xl mb-2">📍</div>
            <p className="text-sm font-semibold text-gray-700 mb-1">
              Aucun événement localisé
            </p>
            <p className="text-xs text-gray-500 leading-snug">
              Les actualités nationales sont affichées dans le feed →
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
