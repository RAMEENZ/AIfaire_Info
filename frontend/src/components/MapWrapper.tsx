"use client";

import { Event } from "@/lib/types";
import FranceMap from "./FranceMap";

interface MapWrapperProps {
  events: Event[];
  selectedEvent?: Event | null;
  onSelectEvent?: (event: Event) => void;
  onSelectDept?: (deptCode: string) => void;
}

export default function MapWrapper({ events, selectedEvent, onSelectEvent, onSelectDept }: MapWrapperProps) {
  return (
    <div className="w-full h-full">
      <FranceMap events={events} selectedEvent={selectedEvent} onSelectEvent={onSelectEvent} onSelectDept={onSelectDept} />
    </div>
  );
}
