"use client";

import { useState } from "react";
import { format, formatDistanceToNow, parseISO } from "date-fns";
import { fr } from "date-fns/locale";

import { SOURCE_LABELS } from "@/lib/constants";
import { ConnectorStatus } from "@/lib/types";

interface StatusBarProps {
  connectors: ConnectorStatus[];
  nextIngestAt?: string | null;
  onTriggerIngest?: () => Promise<void>;
}

const STATUS_COLOR: Record<ConnectorStatus["status"], string> = {
  ok: "#10B981",
  warning: "#F59E0B",
  error: "#EF4444",
};

const STATUS_LABEL: Record<ConnectorStatus["status"], string> = {
  ok: "Opérationnel",
  warning: "Dégradé",
  error: "Erreur",
};

function formatLastRun(iso: string | null): string {
  if (!iso) return "jamais";
  try {
    return format(parseISO(iso), "d MMM HH:mm", { locale: fr });
  } catch {
    return iso;
  }
}

function ConnectorDot({ connector }: { connector: ConnectorStatus }) {
  const [tooltipVisible, setTooltipVisible] = useState(false);
  const label = SOURCE_LABELS[connector.name] ?? connector.name;
  const color = STATUS_COLOR[connector.status];

  return (
    // Bouton (et non div) : la fiche détaillée s'ouvre aussi au focus clavier
    // et au tap mobile, pas seulement au survol souris.
    <button
      type="button"
      className="relative flex items-center gap-1.5 cursor-default"
      onMouseEnter={() => setTooltipVisible(true)}
      onMouseLeave={() => setTooltipVisible(false)}
      onFocus={() => setTooltipVisible(true)}
      onBlur={() => setTooltipVisible(false)}
      onClick={() => setTooltipVisible((v) => !v)}
      aria-label={`${label} : ${STATUS_LABEL[connector.status]}`}
      aria-expanded={tooltipVisible}
    >
      <span
        className="block w-2 h-2 rounded-full flex-shrink-0"
        style={{ backgroundColor: color }}
        aria-hidden="true"
      />
      <span className="text-xs text-gray-600 dark:text-gray-300 hidden sm:inline">{label}</span>

      {tooltipVisible && (
        // Uniquement des <span> (contenu « phrasé ») : un <button> ne peut pas
        // contenir de <div>/<p> en HTML valide. Rendu identique (block + reset
        // des marges par le preflight Tailwind).
        <span className="absolute bottom-full left-0 mb-2 z-50 w-52 rounded-md bg-gray-900 text-white text-xs p-2.5 shadow-lg pointer-events-none block text-left">
          <span className="block font-semibold mb-1">{label}</span>
          <span className="block text-gray-300">
            Statut :{" "}
            <span
              style={{ color }}
              className="font-medium"
            >
              {STATUS_LABEL[connector.status]}
            </span>
          </span>
          <span className="block text-gray-300">
            Dernière exécution : {formatLastRun(connector.last_run)}
          </span>
          {connector.last_count !== null && connector.last_count !== undefined && (
            <span className="block text-gray-300">
              Dernière collecte : {connector.last_count} article{connector.last_count !== 1 ? "s" : ""}
            </span>
          )}
          <span className="block text-gray-300">
            Dernier succès : {formatLastRun(connector.last_success)}
          </span>
          {connector.consecutive_failures > 0 && (
            <span className="block text-gray-300">
              Échecs consécutifs : {connector.consecutive_failures}
            </span>
          )}
          {connector.last_error && (
            <span className="block mt-1 text-red-300 break-words">
              {connector.last_error}
            </span>
          )}
          <span
            className="absolute left-2 bottom-[-4px] w-2 h-2 bg-gray-900 rotate-45"
            aria-hidden="true"
          />
        </span>
      )}
    </button>
  );
}

function formatNextIngest(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return formatDistanceToNow(parseISO(iso), { locale: fr, addSuffix: true });
  } catch {
    return "";
  }
}

export default function StatusBar({ connectors, nextIngestAt, onTriggerIngest }: StatusBarProps) {
  const [ingestState, setIngestState] = useState<"idle" | "running" | "done" | "error">("idle");

  const hasError = connectors.some((c) => c.status === "error");
  const hasWarning = connectors.some((c) => c.status === "warning");

  const globalStatus = hasError ? "error" : hasWarning ? "warning" : "ok";
  const globalColor = STATUS_COLOR[globalStatus];

  async function handleTriggerIngest() {
    if (!onTriggerIngest || ingestState === "running") return;
    setIngestState("running");
    try {
      await onTriggerIngest();
      setIngestState("done");
      setTimeout(() => setIngestState("idle"), 3000);
    } catch {
      // Échec visible (401/503/réseau) plutôt qu'un retour silencieux à l'état
      // initial qui laissait croire que rien ne s'était passé.
      setIngestState("error");
      setTimeout(() => setIngestState("idle"), 4000);
    }
  }

  return (
    <footer className="flex items-center gap-4 px-4 py-1.5 bg-gray-50 dark:bg-gray-900/40 border-t border-gray-200 dark:border-gray-700 text-xs text-gray-500 dark:text-gray-400 flex-shrink-0 z-10">
      <span className="font-medium text-gray-600 dark:text-gray-300 hidden sm:block">Connecteurs :</span>

      {connectors.length === 0 ? (
        <span className="text-gray-400 dark:text-gray-500 italic">Aucun connecteur disponible</span>
      ) : (
        <div className="flex items-center gap-4 flex-wrap">
          {connectors.map((connector) => (
            <ConnectorDot key={connector.name} connector={connector} />
          ))}
        </div>
      )}

      <div className="ml-auto flex items-center gap-3">
        {nextIngestAt && ingestState === "idle" && (
          <span className="hidden md:inline text-gray-400 dark:text-gray-500">
            Prochaine MàJ {formatNextIngest(nextIngestAt)}
          </span>
        )}
        {onTriggerIngest && (
          <button
            onClick={handleTriggerIngest}
            disabled={ingestState === "running"}
            className={`hidden md:flex items-center gap-1 text-xs px-2 py-0.5 rounded border transition-colors disabled:opacity-50 ${
              ingestState === "error"
                ? "border-red-300 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30"
                : "border-gray-300 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
            }`}
            title={ingestState === "error" ? "L'ingestion manuelle a échoué (voir la console)" : "Déclencher une ingestion manuelle"}
          >
            <svg
              className={`w-3 h-3 ${ingestState === "running" ? "animate-spin" : ""}`}
              fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            {ingestState === "done"
              ? "Lancée ✓"
              : ingestState === "running"
              ? "En cours…"
              : ingestState === "error"
              ? "Échec"
              : "Ingérer"}
          </button>
        )}
        <div className="flex items-center gap-1.5">
          <span
            className="block w-2 h-2 rounded-full"
            style={{ backgroundColor: globalColor }}
          />
          <span className="hidden sm:inline">{STATUS_LABEL[globalStatus]}</span>
        </div>
      </div>
    </footer>
  );
}
