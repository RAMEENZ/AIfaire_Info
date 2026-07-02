"use client";

// Page événement dédiée : permalien partageable, lisible sans le contexte de
// la carte. Chargée côté client depuis GET /api/events/{id}.
import useSWR from "swr";
import { format, parseISO } from "date-fns";
import { fr } from "date-fns/locale";

import { API_BASE_URL, CATEGORY_CONFIG, GRAVITE_CONFIG } from "@/lib/constants";
import { Event } from "@/lib/types";

const fetcher = async (url: string): Promise<Event> => {
  const r = await fetch(url);
  if (r.status === 404) throw new Error("introuvable");
  if (!r.ok) throw new Error(`Erreur API : ${r.status}`);
  return r.json();
};

function fmtDate(iso: string): string {
  try {
    return format(parseISO(iso), "d MMMM yyyy 'à' HH:mm", { locale: fr });
  } catch {
    return iso;
  }
}

export default function EventPage({ params }: { params: { id: string } }) {
  const { data: event, error, isLoading } = useSWR<Event>(
    `${API_BASE_URL}/events/${params.id}`,
    fetcher,
    { revalidateOnFocus: false }
  );

  const catConfig = event ? CATEGORY_CONFIG[event.categorie] : null;

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <header className="flex items-center gap-4 px-4 py-3 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 shadow-sm">
        <a
          href={event ? `/?event=${event.id}` : "/"}
          className="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400 hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          Voir sur la carte
        </a>
        <span className="text-blue-700 dark:text-blue-400 font-black text-lg tracking-tight">FAIRE</span>
        <span className="text-gray-500 dark:text-gray-400 text-sm font-medium">Info</span>
      </header>

      <main className="max-w-2xl mx-auto px-4 py-8">
        {isLoading && (
          <div className="text-center py-16 text-gray-400 dark:text-gray-500">Chargement…</div>
        )}

        {error && (
          <div className="text-center py-16">
            <p className="font-medium text-gray-700 dark:text-gray-200 mb-1">
              {String(error.message) === "introuvable"
                ? "Événement introuvable"
                : "Erreur de chargement"}
            </p>
            <p className="text-sm text-gray-400 dark:text-gray-500 mb-4">
              Il a peut-être été purgé (les événements ne sont conservés que
              quelques jours).
            </p>
            <a href="/" className="text-sm text-blue-600 dark:text-blue-400 hover:underline">
              Retour à l'accueil
            </a>
          </div>
        )}

        {event && (
          <article className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm p-6">
            <div className="flex flex-wrap items-center gap-1.5 mb-3">
              <span
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-white text-xs font-medium"
                style={{ backgroundColor: catConfig?.color ?? "#6B7280" }}
              >
                {catConfig?.icon} {catConfig?.label ?? event.categorie}
              </span>
              {event.gravite >= 1 && (
                <span
                  className="inline-flex items-center px-2 py-0.5 rounded text-white text-xs font-medium"
                  style={{ backgroundColor: GRAVITE_CONFIG[event.gravite]?.color ?? "#6B7280" }}
                >
                  {GRAVITE_CONFIG[event.gravite]?.label}
                </span>
              )}
              {event.lieu_nom && event.lieu_nom !== "national" && (
                <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 text-xs">
                  <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z" clipRule="evenodd" />
                  </svg>
                  {event.lieu_nom}
                </span>
              )}
            </div>

            <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100 leading-snug mb-3">
              {event.titre}
            </h1>

            {event.resume_ia && (
              <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed mb-1">
                {event.resume_ia}
              </p>
            )}
            {event.resume_ia && (
              <p className="text-[10px] text-gray-400 dark:text-gray-500 italic mb-4">
                résumé automatique
              </p>
            )}

            {event.tags && event.tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mb-4">
                {event.tags.map((tag) => (
                  <span
                    key={tag}
                    className="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 text-xs"
                  >
                    #{tag}
                  </span>
                ))}
              </div>
            )}

            <div className="border-t border-gray-100 dark:border-gray-700 pt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-gray-500 dark:text-gray-400">
              <div className="space-y-0.5">
                <p>
                  {event.auteur ? `${event.auteur} · ` : ""}
                  publié le {fmtDate(event.date_publication)}
                </p>
                {event.lieu_niveau && event.lieu_niveau !== "national" && (
                  <p>
                    Localisation : {event.lieu_niveau}
                    {event.lieu_confiance_geo > 0 &&
                      ` (confiance ${Math.round(event.lieu_confiance_geo * 100)} %)`}
                  </p>
                )}
              </div>
              <a
                href={event.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-700 text-white font-medium transition-colors"
              >
                Lire l'article original
                <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
              </a>
            </div>
          </article>
        )}
      </main>
    </div>
  );
}
