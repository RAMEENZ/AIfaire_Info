"use client";

import { useEffect, useRef } from "react";
import { MapContainer, TileLayer, useMapEvents } from "react-leaflet";
import type { Map as LeafletMap } from "leaflet";

import EventMarker from "./EventMarker";
import { FRANCE_BOUNDS, FRANCE_CENTER, FRANCE_DEFAULT_ZOOM } from "@/lib/constants";
import { Event } from "@/lib/types";

interface FranceMapProps {
  events: Event[];
  onBboxChange: (bbox: string) => void;
}

function BboxTracker({ onBboxChange }: { onBboxChange: (bbox: string) => void }) {
  const map = useMapEvents({
    moveend() {
      const b = map.getBounds();
      const bbox = [
        b.getWest().toFixed(6),
        b.getSouth().toFixed(6),
        b.getEast().toFixed(6),
        b.getNorth().toFixed(6),
      ].join(",");
      onBboxChange(bbox);
    },
  });
  return null;
}

export default function FranceMap({ events, onBboxChange }: FranceMapProps) {
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
      <BboxTracker onBboxChange={onBboxChange} />
      {events.map((event) => (
        <EventMarker key={event.id} event={event} />
      ))}
    </MapContainer>
  );
}
