"use client";

import { parseISO, format, formatDistanceToNow } from "date-fns";
import { fr } from "date-fns/locale";

interface StatsBarProps {
  localCount: number;
  nationalCount: number;
  generatedAt: string | null;
}

function formatGeneratedAt(iso: string | null): string {
  if (!iso) return "";
  try {
    const d = parseISO(iso);
    const now = Date.now();
    const diffMs = now - d.getTime();
    if (diffMs < 60_000) return "à l'instant";
    if (diffMs < 3600_000) return formatDistanceToNow(d, { locale: fr, addSuffix: true });
    return format(d, "HH:mm", { locale: fr });
  } catch {
    return "";
  }
}

export default function StatsBar({ localCount, nationalCount, generatedAt }: StatsBarProps) {
  const time = formatGeneratedAt(generatedAt);
  const total = localCount + nationalCount;

  return (
    <div className="flex items-center gap-2 px-4 py-1.5 bg-gray-50 border-b border-gray-200 text-xs flex-shrink-0">
      <span className="font-semibold text-gray-700">{total}</span>
      <span className="text-gray-400">événements</span>

      <span className="text-gray-200 mx-1">|</span>

      <span className="inline-flex items-center gap-1 text-blue-600 font-medium">
        <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z" clipRule="evenodd" />
        </svg>
        {localCount} localisé{localCount !== 1 ? "s" : ""}
      </span>

      <span className="text-gray-400">
        · {nationalCount} national{nationalCount !== 1 ? "aux" : ""}
      </span>

      {time && (
        <span className="ml-auto text-gray-400">
          Màj {time}
        </span>
      )}
    </div>
  );
}
