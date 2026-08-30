"use client";

import { useEffect, useState } from "react";

/**
 * Enregistre le service worker et signale la perte de connexion.
 *
 * L'enregistrement se fait ici (et non dans le layout) pour rester côté
 * client, après l'hydratation : le worker n'est qu'un filet hors ligne, il
 * ne doit jamais retarder le premier rendu.
 */
export default function OfflineIndicator() {
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    setOffline(!navigator.onLine);
    const goOffline = () => setOffline(true);
    const goOnline = () => setOffline(false);
    window.addEventListener("offline", goOffline);
    window.addEventListener("online", goOnline);

    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
      // `catch` silencieux : un échec d'enregistrement (navigation privée,
      // navigateur ancien) ne doit rien casser — l'app fonctionne sans.
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }

    return () => {
      window.removeEventListener("offline", goOffline);
      window.removeEventListener("online", goOnline);
    };
  }, []);

  if (!offline) return null;

  return (
    <div
      role="status"
      className="flex items-center justify-center gap-1.5 px-3 py-1 bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-200 text-[11px] font-medium shrink-0"
    >
      <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M18.364 5.636a9 9 0 010 12.728m-12.728 0a9 9 0 010-12.728m9.9 9.9a5 5 0 010-7.072m-7.072 0a5 5 0 010 7.072M13 12a1 1 0 11-2 0 1 1 0 012 0z" />
      </svg>
      Hors ligne — dernières données connues
    </div>
  );
}
