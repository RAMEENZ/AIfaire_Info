"use client";

import { parseISO, format } from "date-fns";

interface StatsBarProps {
  localCount: number;
  nationalCount: number;
  generatedAt: string | null;
}

function formatGeneratedAt(iso: string | null): string {
  if (!iso) return "";
  try {
    return format(parseISO(iso), "HH:mm");
  } catch {
    return "";
  }
}

export default function StatsBar({ localCount, nationalCount, generatedAt }: StatsBarProps) {
  const time = formatGeneratedAt(generatedAt);

  return (
    <div className="flex items-center gap-3 px-4 py-1.5 bg-gray-50 border-b border-gray-200 text-xs flex-shrink-0">
      <button
        className="font-medium text-blue-600 hover:text-blue-800 transition-colors"
        onClick={() => {
          // Scroll map viewport to localised events — best-effort via window message
          window.dispatchEvent(new CustomEvent("faire:focus-local-events"));
        }}
      >
        {localCount} localisé{localCount !== 1 ? "s" : ""}
      </button>
      <span className="text-gray-300">|</span>
      <span className="text-gray-500">
        {nationalCount} national{nationalCount !== 1 ? "aux" : ""}
      </span>
      {time && (
        <>
          <span className="text-gray-300">|</span>
          <span className="text-gray-400">Màj {time}</span>
        </>
      )}
    </div>
  );
}
