"use client";

import { useEffect, useState } from "react";
import { API_BASE_URL } from "@/lib/constants";
import { DEPT_CODE_TO_NAME } from "@/lib/departments";
import { toast } from "@/lib/toast";

/**
 * Activation des notifications Web Push.
 *
 * Discret par construction : le bouton n'apparaît que si le serveur a des clés
 * VAPID configurées ET si le navigateur sait faire. Aucune demande de
 * permission n'est déclenchée au chargement — uniquement sur action explicite,
 * une sollicitation non sollicitée étant la meilleure façon de se faire
 * bloquer définitivement par le navigateur.
 */

/** Convertit la clé publique base64url en buffer attendu par l'API Push.
 * Le type de retour est `ArrayBuffer` : `applicationServerKey` n'accepte pas
 * un `Uint8Array` adossé à un `SharedArrayBuffer` selon la définition DOM. */
function urlBase64ToBuffer(base64: string): ArrayBuffer {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const normalized = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(normalized);
  const buffer = new ArrayBuffer(raw.length);
  const view = new Uint8Array(buffer);
  for (let i = 0; i < raw.length; i++) view[i] = raw.charCodeAt(i);
  return buffer;
}

export default function PushSettings({ pinnedDept }: { pinnedDept?: string | null }) {
  const [available, setAvailable] = useState(false);
  const [publicKey, setPublicKey] = useState<string | null>(null);
  const [subscribed, setSubscribed] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const supported =
      typeof window !== "undefined" &&
      "serviceWorker" in navigator &&
      "PushManager" in window &&
      "Notification" in window;
    if (!supported) return;

    fetch(`${API_BASE_URL}/push/public-key`)
      .then((r) => r.json())
      .then((d: { enabled: boolean; public_key: string | null }) => {
        if (d.enabled && d.public_key) {
          setAvailable(true);
          setPublicKey(d.public_key);
        }
      })
      .catch(() => {});

    navigator.serviceWorker.ready
      .then((reg) => reg.pushManager.getSubscription())
      .then((sub) => setSubscribed(!!sub))
      .catch(() => {});
  }, []);

  async function enable() {
    if (!publicKey) return;
    setBusy(true);
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        toast("Notifications refusées — réactivables dans les réglages du navigateur", "error");
        return;
      }
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToBuffer(publicKey),
      });
      const json = sub.toJSON() as { endpoint?: string; keys?: { p256dh: string; auth: string } };
      const res = await fetch(`${API_BASE_URL}/push/subscribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          endpoint: json.endpoint,
          keys: json.keys,
          departement: pinnedDept ?? "",
          gravite_min: 3,
        }),
      });
      if (!res.ok) throw new Error(String(res.status));
      setSubscribed(true);
      toast(
        pinnedDept
          ? `Alertes activées pour ${DEPT_CODE_TO_NAME[pinnedDept] ?? pinnedDept}`
          : "Alertes activées pour toute la France",
        "success"
      );
    } catch {
      toast("Activation impossible", "error");
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    setBusy(true);
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await fetch(`${API_BASE_URL}/push/unsubscribe`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ endpoint: sub.endpoint }),
        }).catch(() => {});
        await sub.unsubscribe();
      }
      setSubscribed(false);
      toast("Alertes désactivées", "success");
    } catch {
      toast("Désactivation impossible", "error");
    } finally {
      setBusy(false);
    }
  }

  if (!available) return null;

  return (
    <button
      onClick={subscribed ? disable : enable}
      disabled={busy}
      aria-pressed={subscribed}
      title={
        subscribed
          ? "Désactiver les alertes push"
          : pinnedDept
          ? `Recevoir les alertes graves de ${DEPT_CODE_TO_NAME[pinnedDept] ?? pinnedDept}`
          : "Recevoir les alertes graves (épinglez un département pour cibler)"
      }
      className={`flex items-center gap-1 text-xs px-2 py-1 rounded border transition-colors disabled:opacity-50 ${
        subscribed
          ? "border-blue-300 dark:border-blue-700 text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-900/30"
          : "border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50"
      }`}
    >
      <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
        />
      </svg>
      <span className="hidden lg:inline">{subscribed ? "Alertes activées" : "Alertes push"}</span>
    </button>
  );
}
