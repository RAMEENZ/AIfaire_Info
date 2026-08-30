"use client";
import { useState } from "react";
import useSWR from "swr";
import { API_BASE_URL, GRAVITE_CONFIG } from "@/lib/constants";
import { DEPT_CODE_TO_NAME } from "@/lib/departments";

interface BriefData {
  date: string;
  content: string;
  event_count: number;
  generated_at: string;
  brief?: null;
  message?: string;
}

const fetcher = (url: string) => fetch(url).then(r => r.json());

const SECTION_TITLES = ["Alertes & vigilances", "Actualité générale", "En régions"];

function BriefContent({ content }: { content: string }) {
  const lines = content.split("\n");
  const elements: React.ReactNode[] = [];
  let key = 0;

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      elements.push(<div key={key++} className="h-2" />);
      continue;
    }
    if (SECTION_TITLES.includes(trimmed)) {
      elements.push(
        <p key={key++} className="font-semibold text-blue-800 dark:text-blue-200 mt-3 mb-1 first:mt-0">
          {trimmed}
        </p>
      );
    } else {
      elements.push(
        <p key={key++} className="text-gray-700 dark:text-gray-200 leading-relaxed">
          {trimmed}
        </p>
      );
    }
  }

  return <div className="space-y-0.5">{elements}</div>;
}

function BriefArchive({ latestGeneratedAt }: { latestGeneratedAt: string }) {
  const [showArchive, setShowArchive] = useState(false);
  // Chargement paresseux : l'archive n'est demandée qu'à l'ouverture.
  const { data, isLoading } = useSWR<{ briefs: BriefData[] }>(
    showArchive ? `${API_BASE_URL}/brief/history?limit=14` : null,
    fetcher,
    { revalidateOnFocus: false }
  );

  // Le brief courant est déjà affiché au-dessus : on ne liste que les autres.
  const past = (data?.briefs ?? []).filter((b) => b.generated_at !== latestGeneratedAt);

  return (
    <div className="mt-2">
      <button
        onClick={() => setShowArchive((v) => !v)}
        className="text-[10px] font-medium text-blue-600 dark:text-blue-300 hover:underline"
        aria-expanded={showArchive}
      >
        {showArchive ? "▲ Masquer les briefs précédents" : "▼ Briefs précédents"}
      </button>
      {showArchive && (
        <div className="mt-1.5 space-y-1">
          {isLoading && <p className="text-[10px] text-gray-500 dark:text-gray-400">Chargement…</p>}
          {!isLoading && past.length === 0 && (
            <p className="text-[10px] text-gray-500 dark:text-gray-400">Aucun brief antérieur.</p>
          )}
          {past.map((b) => (
            <details key={b.generated_at} className="group">
              <summary className="cursor-pointer text-[11px] text-gray-600 dark:text-gray-300 hover:text-blue-700 dark:hover:text-blue-300">
                {new Date(b.generated_at).toLocaleDateString("fr-FR", {
                  weekday: "long", day: "numeric", month: "long",
                })}{" "}
                ·{" "}
                {new Date(b.generated_at).toLocaleTimeString("fr-FR", {
                  hour: "2-digit", minute: "2-digit",
                })}
              </summary>
              <div className="mt-1 pl-2 border-l-2 border-blue-200 dark:border-blue-800">
                <BriefContent content={b.content} />
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}

interface LocalBrief {
  dept: string;
  total: number;
  par_categorie: Record<string, number>;
  faits: {
    id: string;
    titre: string;
    categorie: string;
    gravite: number;
    lieu_nom: string | null;
    source_url: string;
  }[];
}

/** Volet « près de chez vous », affiché quand un département est épinglé. */
function LocalBriefPanel({ dept }: { dept: string }) {
  const { data } = useSWR<LocalBrief>(`${API_BASE_URL}/brief/local?dept=${dept}`, fetcher, {
    refreshInterval: 3600_000,
    revalidateOnFocus: false,
  });

  if (!data || data.total === 0) return null;

  return (
    <div className="mt-3 pt-2 border-t border-blue-200 dark:border-blue-800">
      <p className="font-semibold text-blue-800 dark:text-blue-200 mb-1">
        Dans le {DEPT_CODE_TO_NAME[dept] ?? dept} — {data.total} événement
        {data.total > 1 ? "s" : ""} sur 24 h
      </p>
      <ul className="space-y-0.5">
        {data.faits.map((f) => (
          <li key={f.id} className="flex items-start gap-1.5">
            <span
              className="w-1.5 h-1.5 rounded-full shrink-0 mt-1.5"
              style={{ backgroundColor: GRAVITE_CONFIG[f.gravite]?.color ?? "#6B7280" }}
            />
            <a
              href={f.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-gray-700 dark:text-gray-200 hover:text-blue-700 dark:hover:text-blue-300 hover:underline leading-snug"
            >
              {f.titre}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function DailyBrief({ pinnedDept }: { pinnedDept?: string | null }) {
  const [open, setOpen] = useState(false);
  const { data, isLoading } = useSWR<BriefData>(`${API_BASE_URL}/brief`, fetcher, {
    refreshInterval: 3600_000,
    revalidateOnFocus: true,
  });

  const hasBrief = data && !data.message && data.content;

  return (
    <div className="border-b border-gray-100 dark:border-gray-700">
      <button
        onClick={() => setOpen(v => !v)}
        className={`w-full flex items-center gap-2 px-3 py-2 text-left text-xs font-medium hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors ${hasBrief ? "text-blue-700 dark:text-blue-300" : "text-gray-500 dark:text-gray-400"}`}
        disabled={!hasBrief && !isLoading}
      >
        <span className="text-base">📰</span>
        <span className="flex-1">
          {isLoading
            ? "Chargement du brief..."
            : hasBrief
            ? `Brief du ${new Date(data.date).toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}`
            : "Aucun brief disponible"}
        </span>
        {hasBrief && <span className="text-gray-500 dark:text-gray-400">{open ? "▲" : "▼"}</span>}
      </button>
      {open && hasBrief && (
        // max-h + overflow-y : la colonne parente est en overflow-hidden — sans
        // défilement propre, un brief long (a fortiori avec les archives
        // dépliées) déborde et devient illisible, surtout sur mobile.
        // overscroll-contain : arrivé en butée, le geste ne scrolle pas la page.
        <div className="px-3 pb-3 text-xs bg-blue-50 dark:bg-blue-900/30 border-t border-blue-100 dark:border-blue-800 max-h-[45vh] overflow-y-auto overscroll-contain">
          <div className="mt-2">
            <BriefContent content={data.content} />
          </div>
          <p className="mt-3 text-[10px] text-gray-500 dark:text-gray-400">
            Généré à {new Date(data.generated_at).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })} · {data.event_count} événements analysés
          </p>
          {pinnedDept && <LocalBriefPanel dept={pinnedDept} />}
          <BriefArchive latestGeneratedAt={data.generated_at} />
        </div>
      )}
    </div>
  );
}
