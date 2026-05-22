"use client";

import { useState } from "react";
import { format, parseISO } from "date-fns";
import { fr } from "date-fns/locale";

import { SOURCE_LABELS } from "@/lib/constants";
import { ConnectorStatus } from "@/lib/types";

interface StatusBarProps {
  connectors: ConnectorStatus[];
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
    <div
      className="relative flex items-center gap-1.5 cursor-default"
      onMouseEnter={() => setTooltipVisible(true)}
      onMouseLeave={() => setTooltipVisible(false)}
    >
      <span
        className="block w-2 h-2 rounded-full flex-shrink-0"
        style={{ backgroundColor: color }}
        aria-label={STATUS_LABEL[connector.status]}
      />
      <span className="text-xs text-gray-600 hidden sm:inline">{label}</span>

      {tooltipVisible && (
        <div className="absolute bottom-full left-0 mb-2 z-50 w-52 rounded-md bg-gray-900 text-white text-xs p-2.5 shadow-lg pointer-events-none">
          <p className="font-semibold mb-1">{label}</p>
          <p className="text-gray-300">
            Statut :{" "}
            <span
              style={{ color }}
              className="font-medium"
            >
              {STATUS_LABEL[connector.status]}
            </span>
          </p>
          <p className="text-gray-300">
            Dernière exécution : {formatLastRun(connector.last_run)}
          </p>
          {connector.last_error && (
            <p className="mt-1 text-red-300 break-words">
              {connector.last_error}
            </p>
          )}
          <div
            className="absolute left-2 bottom-[-4px] w-2 h-2 bg-gray-900 rotate-45"
            aria-hidden="true"
          />
        </div>
      )}
    </div>
  );
}

export default function StatusBar({ connectors }: StatusBarProps) {
  const hasError = connectors.some((c) => c.status === "error");
  const hasWarning = connectors.some((c) => c.status === "warning");

  const globalStatus = hasError ? "error" : hasWarning ? "warning" : "ok";
  const globalColor = STATUS_COLOR[globalStatus];

  return (
    <footer className="flex items-center gap-4 px-4 py-1.5 bg-gray-50 border-t border-gray-200 text-xs text-gray-500 flex-shrink-0 z-10">
      <span className="font-medium text-gray-600 hidden sm:block">Connecteurs :</span>

      {connectors.length === 0 ? (
        <span className="text-gray-400 italic">Aucun connecteur disponible</span>
      ) : (
        <div className="flex items-center gap-4 flex-wrap">
          {connectors.map((connector) => (
            <ConnectorDot key={connector.name} connector={connector} />
          ))}
        </div>
      )}

      <div className="ml-auto flex items-center gap-1.5">
        <span
          className="block w-2 h-2 rounded-full"
          style={{ backgroundColor: globalColor }}
        />
        <span className="hidden sm:inline">{STATUS_LABEL[globalStatus]}</span>
      </div>
    </footer>
  );
}
