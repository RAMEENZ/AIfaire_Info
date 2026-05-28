"use client";

import { Event } from "@/lib/types";
import FranceMap from "./FranceMap";

interface MapWrapperProps {
  events: Event[];
  selectedEvent?: Event | null;
  onSelectEvent?: (event: Event) => void;
}

export default function MapWrapper({ events, selectedEvent, onSelectEvent }: MapWrapperProps) {
  return (
    <div className="w-full h-full">
      <FranceMap events={events} selectedEvent={selectedEvent} onSelectEvent={onSelectEvent} />
    </div>
  );
}
