"use client";

import { useEffect, useRef } from "react";
import { MapContainer, TileLayer } from "react-leaflet";
import type { Map as LeafletMap } from "leaflet";

import EventMarker from "./EventMarker";
import { FRANCE_BOUNDS, FRANCE_CENTER, FRANCE_DEFAULT_ZOOM } from "@/lib/constants";
import { Event } from "@/lib/types";

interface FranceMapProps {
  events: Event[];
}

export default function FranceMap({ events }: FranceMapProps) {
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

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <MapContainer
        center={FRANCE_CENTER}
        zoom={FRANCE_DEFAULT_ZOOM}
        minZoom={5}
        maxZoom={18}
        maxBounds={FRANCE_BOUNDS}
        maxBoundsViscosity={0.6}
        style={{ width: "100%", height: "100%" }}
        ref={mapRef}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {events.map((event) => (
          <EventMarker key={event.id} event={event} />
        ))}
      </MapContainer>

      {events.length === 0 && (
        <div
          className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none"
          style={{ top: 0, left: 0, right: 0, bottom: 0 }}
        >
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
