"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { MapContainer, TileLayer, GeoJSON, useMap, useMapEvents } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import type { Map as LeafletMap, Layer } from "leaflet";
import type { GeoJsonObject, Feature, Geometry } from "geojson";

import EventMarker from "./EventMarker";
import { CATEGORY_CONFIG, GRAVITE_CONFIG, FRANCE_CENTER, FRANCE_DEFAULT_ZOOM } from "@/lib/constants";
import { Event } from "@/lib/types";

interface FranceMapProps {
  events: Event[];
  selectedEvent?: Event | null;
  onSelectEvent?: (event: Event) => void;
  onSelectDept?: (deptCode: string) => void;
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

const DEPT_GEOJSON_URL =
  "https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/departements-version-simplifiee.geojson";

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

function deptCodeFromInsee(inseeCode: string): string {
  if (inseeCode.startsWith("97") || inseeCode.startsWith("98")) {
    return inseeCode.slice(0, 3);
  }
  return inseeCode.slice(0, 2);
}

function graviteColor(gravite: number): { color: string; opacity: number } | null {
  if (gravite >= 3) return { color: "#EF4444", opacity: 0.4 };
  if (gravite >= 2) return { color: "#F97316", opacity: 0.3 };
  if (gravite >= 1) return { color: "#F59E0B", opacity: 0.2 };
  return null;
}

function distanceKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
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

// ── Feature 2: Heatmap layer ────────────────────────────────────────────────

function HeatmapLayer({ events, active }: { events: Event[]; active: boolean }) {
  const map = useMap();

  useEffect(() => {
    if (typeof window === "undefined") return;

    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const L = require("leaflet") as typeof import("leaflet");

    // Load leaflet.heat from CDN if not available
    const loadHeat = (): Promise<void> => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      if ((L as any).heatLayer) return Promise.resolve();
      return new Promise((resolve, reject) => {
        const existing = document.querySelector(
          'script[src*="leaflet-heat"]'
        );
        if (existing) {
          existing.addEventListener("load", () => resolve());
          return;
        }
        const script = document.createElement("script");
        script.src = "https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js";
        script.onload = () => resolve();
        script.onerror = reject;
        document.head.appendChild(script);
      });
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let heatLayer: any = null;

    if (active) {
      loadHeat()
        .then(() => {
          const points = events
            .filter((e) => e.lieu_lat != null && e.lieu_lon != null)
            .map((e) => [e.lieu_lat!, e.lieu_lon!, Math.min(1, (e.gravite + 1) / 4)]);

          if (points.length === 0) return;
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          heatLayer = (L as any).heatLayer(points, {
            radius: 25,
            blur: 20,
            maxZoom: 10,
            gradient: { 0.4: "#3B82F6", 0.65: "#F59E0B", 1: "#EF4444" },
          }).addTo(map);
        })
        .catch(console.error);
    }

    return () => {
      if (heatLayer) map.removeLayer(heatLayer);
    };
  }, [active, events, map]);

  return null;
}

// ── Feature 4: Watch zone helpers ───────────────────────────────────────────

function MapClickHandler({ onMapClick }: { onMapClick: (lat: number, lon: number) => void }) {
  useMapEvents({
    click(e) {
      onMapClick(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}

interface WatchZone {
  lat: number;
  lon: number;
  radius: number; // km
}

function WatchCircle({ zone }: { zone: WatchZone }) {
  const map = useMap();

  useEffect(() => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const L = require("leaflet") as typeof import("leaflet");
    const circle = L.circle([zone.lat, zone.lon], {
      radius: zone.radius * 1000, // m
      color: "#6366F1",
      weight: 2,
      fillColor: "#6366F1",
      fillOpacity: 0.08,
      dashArray: "6 4",
    }).addTo(map);

    return () => {
      map.removeLayer(circle);
    };
  }, [map, zone.lat, zone.lon, zone.radius]);

  return null;
}

// ── Géorecherche (Nominatim) ────────────────────────────────────────────────

function GeoSearch() {
  const map = useMap();
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [notFound, setNotFound] = useState(false);

  const handleSearch = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    setLoading(true);
    setNotFound(false);
    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(q)}&countrycodes=fr&limit=1`,
        { headers: { "Accept-Language": "fr" } }
      );
      const data = await res.json();
      if (data[0]) {
        map.flyTo([parseFloat(data[0].lat), parseFloat(data[0].lon)], 12, { duration: 1 });
        setQuery("");
      } else {
        setNotFound(true);
        setTimeout(() => setNotFound(false), 2000);
      }
    } catch {
      // ignore network errors
    } finally {
      setLoading(false);
    }
  }, [map, query]);

  return (
    <form onSubmit={handleSearch} className="absolute top-2 left-2 z-[1000] flex gap-1">
      <input
        type="text"
        value={query}
        onChange={(e) => { setQuery(e.target.value); setNotFound(false); }}
        placeholder="Rechercher une ville…"
        className={`px-2 py-1 text-xs rounded border shadow-md bg-white w-36 focus:outline-none transition-colors ${
          notFound ? "border-red-400 placeholder-red-400" : "border-gray-200 focus:border-blue-400"
        }`}
      />
      <button
        type="submit"
        disabled={loading || !query.trim()}
        className="px-2 py-1 text-xs rounded border border-gray-200 shadow-md bg-white text-gray-600 hover:bg-blue-50 hover:text-blue-700 disabled:opacity-40 transition-colors"
        title="Rechercher"
      >
        {loading ? "…" : "🔍"}
      </button>
    </form>
  );
}

export default function FranceMap({ events, selectedEvent, onSelectEvent, onSelectDept }: FranceMapProps) {
  const mapRef = useRef<LeafletMap | null>(null);
  const [deptGeoJSON, setDeptGeoJSON] = useState<GeoJsonObject | null>(null);
  const [showRiskLayer, setShowRiskLayer] = useState(false);

  // Feature 2: heatmap toggle
  const [showHeatmap, setShowHeatmap] = useState(false);

  // Feature 4: watch zone
  const [watchMode, setWatchMode] = useState(false);
  const [watchZone, setWatchZone] = useState<WatchZone | null>(null);

  const deptMaxGravite = new Map<string, number>();
  for (const event of events) {
    if (!event.lieu_code_insee) continue;
    const code = deptCodeFromInsee(event.lieu_code_insee);
    const current = deptMaxGravite.get(code) ?? 0;
    if (event.gravite > current) deptMaxGravite.set(code, event.gravite);
  }

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
    fetch(DEPT_GEOJSON_URL)
      .then((r) => r.json())
      .then((data: GeoJsonObject) => setDeptGeoJSON(data))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (selectedEvent?.lieu_lat != null && selectedEvent?.lieu_lon != null) {
      const container = mapRef.current?.getContainer();
      if (!container || container.offsetWidth === 0 || container.offsetHeight === 0) return;
      const targetZoom =
        selectedEvent.lieu_niveau === "commune" ? 13
        : selectedEvent.lieu_niveau === "departement" ? 10
        : selectedEvent.lieu_niveau === "region" ? 8
        : 7;
      const currentZoom = mapRef.current?.getZoom() ?? 0;
      mapRef.current?.flyTo(
        [selectedEvent.lieu_lat, selectedEvent.lieu_lon],
        Math.max(currentZoom, targetZoom),
        { duration: 0.8 }
      );
    }
  }, [selectedEvent]);

  const flyTo = (center: [number, number], zoom: number) => {
    mapRef.current?.flyTo(center, zoom, { duration: 1.2 });
  };

  const styleFeature = (feature?: Feature<Geometry, { code: string }>) => {
    if (!feature) return {};
    const code = feature.properties?.code ?? "";
    const gravite = deptMaxGravite.get(code) ?? 0;
    const fill = showRiskLayer ? graviteColor(gravite) : null;
    if (!fill) {
      return {
        fillColor: "transparent",
        fillOpacity: 0,
        color: "#94A3B8",
        weight: 0.5,
        opacity: 0.3,
      };
    }
    return {
      fillColor: fill.color,
      fillOpacity: fill.opacity,
      color: fill.color,
      weight: 1,
      opacity: 0.5,
    };
  };

  const onEachDept = useCallback((feature: Feature<Geometry, { code: string; nom: string }>, layer: Layer) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (layer as any).on({
      click: () => {
        if (onSelectDept) onSelectDept(feature.properties?.code ?? "");
      },
      mouseover: (e: { target: { setStyle: (s: object) => void } }) => {
        e.target.setStyle({ weight: 2, color: "#3B82F6", opacity: 0.7 });
      },
      mouseout: (e: { target: { setStyle: (s: object) => void } }) => {
        e.target.setStyle(styleFeature(feature));
      },
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onSelectDept, deptMaxGravite, showRiskLayer]);

  const handleMapClick = (lat: number, lon: number) => {
    if (!watchMode) return;
    setWatchZone((prev) => ({ lat, lon, radius: prev?.radius ?? 50 }));
  };

  // Feature 4: filter visible markers when watch zone is active
  const visibleEvents = watchZone
    ? events.filter(
        (e) =>
          e.lieu_lat != null &&
          e.lieu_lon != null &&
          distanceKm(watchZone.lat, watchZone.lon, e.lieu_lat!, e.lieu_lon!) <= watchZone.radius
      )
    : events;

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <MapContainer
        center={FRANCE_CENTER}
        zoom={FRANCE_DEFAULT_ZOOM}
        minZoom={3}
        maxZoom={18}
        style={{ width: "100%", height: "100%", cursor: watchMode ? "crosshair" : undefined }}
        ref={mapRef}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {deptGeoJSON && (
          <GeoJSON
            key={JSON.stringify([Array.from(deptMaxGravite.entries()), showRiskLayer])}
            data={deptGeoJSON}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            style={(feature) => styleFeature(feature as Feature<Geometry, { code: string }>)}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            onEachFeature={onEachDept as any}
            pane="tilePane"
          />
        )}
        <MarkerClusterGroup
          showCoverageOnHover={false}
          iconCreateFunction={createClusterCustomIcon}
          maxClusterRadius={50}
          disableClusteringAtZoom={12}
        >
          {visibleEvents.map((event) => (
            <EventMarker
              key={event.id}
              event={event}
              isSelected={selectedEvent?.id === event.id}
              onSelect={onSelectEvent}
            />
          ))}
        </MarkerClusterGroup>

        {/* Géorecherche */}
        <GeoSearch />

        {/* Feature 2: Heatmap layer */}
        <HeatmapLayer events={events} active={showHeatmap} />

        {/* Feature 4: Map click handler for watch zone */}
        <MapClickHandler onMapClick={handleMapClick} />

        {/* Feature 4: Watch zone circle */}
        {watchZone && <WatchCircle zone={watchZone} />}
      </MapContainer>

      {/* Bouton toggle couche risque départements */}
      <div className="absolute top-2 right-2 z-[1000]">
        <button
          onClick={() => setShowRiskLayer((v) => !v)}
          className={`px-2.5 py-1 text-[11px] font-medium rounded border shadow-md transition-colors ${
            showRiskLayer
              ? "bg-red-600 text-white border-red-700 hover:bg-red-700"
              : "bg-white text-gray-600 border-gray-200 hover:bg-gray-50 hover:text-blue-700"
          }`}
          title="Afficher/masquer la couche de risque par département"
        >
          Risque depts
        </button>
      </div>

      {/* Feature 2: Heatmap toggle button */}
      <div className="absolute bottom-16 right-2 z-[1000]">
        <button
          onClick={() => setShowHeatmap((v) => !v)}
          className={`px-2 py-1 rounded text-xs font-medium border shadow-md transition-colors ${
            showHeatmap
              ? "bg-orange-500 text-white border-orange-600"
              : "bg-white text-gray-600 border-gray-200 hover:text-orange-500"
          }`}
          title="Basculer la heatmap"
        >
          🔥 Heatmap
        </button>
      </div>

      {/* Feature 4: Zone watch toggle + controls */}
      <div className="absolute bottom-24 right-2 z-[1000] flex flex-col items-end gap-1">
        <button
          onClick={() => {
            setWatchMode((v) => {
              if (v) {
                // deactivating watch mode clears zone too
                setWatchZone(null);
              }
              return !v;
            });
          }}
          className={`px-2 py-1 rounded text-xs font-medium border shadow-md transition-colors ${
            watchMode
              ? "bg-indigo-600 text-white border-indigo-700"
              : "bg-white text-gray-600 border-gray-200 hover:text-indigo-600"
          }`}
          title="Activer la zone de surveillance (cliquez sur la carte pour définir le centre)"
        >
          📍 Zone
        </button>
        {watchZone && (
          <div className="bg-white border border-indigo-200 rounded shadow-md px-2 py-1.5 flex flex-col gap-1 text-[10px] text-gray-700 w-36">
            <div className="flex justify-between items-center">
              <span className="font-medium text-indigo-700">Rayon : {watchZone.radius} km</span>
              <button
                onClick={() => { setWatchZone(null); setWatchMode(false); }}
                className="text-gray-400 hover:text-red-500 transition-colors"
                title="Effacer la zone"
              >
                ✕
              </button>
            </div>
            <input
              type="range"
              min={10}
              max={500}
              step={10}
              value={watchZone.radius}
              onChange={(e) =>
                setWatchZone((prev) => prev ? { ...prev, radius: Number(e.target.value) } : prev)
              }
              className="w-full accent-indigo-600"
            />
            <p className="text-[9px] text-gray-400">
              {visibleEvents.length} événement{visibleEvents.length !== 1 ? "s" : ""} dans la zone
            </p>
          </div>
        )}
        {watchMode && !watchZone && (
          <p className="bg-white/90 border border-indigo-200 rounded shadow-md px-2 py-1 text-[10px] text-indigo-700 w-36 text-center">
            Cliquez sur la carte pour définir le centre
          </p>
        )}
      </div>

      {/* Panneau de navigation DOM-TOM */}
      <div className="absolute bottom-7 left-2 z-[1000]">
        <div className="bg-white/90 backdrop-blur-sm border border-gray-200 rounded-lg shadow-md px-2 py-1.5">
          <p className="text-[9px] font-semibold text-gray-400 uppercase tracking-wide mb-1">DOM-TOM</p>
          <div className="flex flex-wrap gap-1 max-w-[200px]">
            {DOM_TOM.map((t) => {
              const territoryEvents = events.filter((e) => e.lieu_code_insee?.startsWith(t.code) ?? false);
              const maxG = territoryEvents.reduce((m, e) => Math.max(m, e.gravite), 0);
              const alertColor = maxG >= 3 ? "#EF4444" : maxG >= 2 ? "#F97316" : maxG >= 1 ? "#F59E0B" : null;
              return (
                <button
                  key={t.code}
                  onClick={() => flyTo(t.center, t.zoom)}
                  className="relative px-1.5 py-0.5 text-[10px] font-medium bg-gray-50 hover:bg-blue-50 border border-gray-200 rounded text-gray-600 hover:text-blue-700 transition-colors"
                  title={alertColor ? `${t.name} — ${territoryEvents.length} alerte(s)` : `Aller sur ${t.name}`}
                >
                  {t.name}
                  {alertColor && (
                    <span
                      className="absolute -top-1 -right-1 w-2 h-2 rounded-full border border-white"
                      style={{ backgroundColor: alertColor }}
                    />
                  )}
                </button>
              );
            })}
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

      {/* Feature 4: zone active but all events filtered out note */}
      {watchZone && visibleEvents.length === 0 && events.length > 0 && (
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-10 pointer-events-none">
          <div className="bg-white/90 backdrop-blur-sm rounded-xl px-5 py-4 text-center shadow-md max-w-xs">
            <p className="text-sm font-semibold text-gray-700 mb-1">Aucun événement dans la zone</p>
            <p className="text-xs text-gray-500">
              Augmentez le rayon ou déplacez le centre
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
