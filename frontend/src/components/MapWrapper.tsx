"use client";

import { Event } from "@/lib/types";
import FranceMap from "./FranceMap";

interface MapWrapperProps {
  events: Event[];
}

export default function MapWrapper({ events }: MapWrapperProps) {
  return (
    <div className="w-full h-full">
      <FranceMap events={events} />
    </div>
  );
}
