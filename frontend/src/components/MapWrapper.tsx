"use client";

import { Event } from "@/lib/types";
import FranceMap from "./FranceMap";

interface MapWrapperProps {
  events: Event[];
  onBboxChange: (bbox: string) => void;
}

export default function MapWrapper({ events, onBboxChange }: MapWrapperProps) {
  return (
    <div className="w-full h-full">
      <FranceMap events={events} onBboxChange={onBboxChange} />
    </div>
  );
}
