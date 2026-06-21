// Alertes navigateur : prévient l'utilisateur quand un événement de gravité
// élevée apparaît dans les départements qu'il surveille. 100 % côté client
// (Notification API + localStorage), aucun changement backend requis.
import { Categorie, Event } from "./types";
import { deptCodeFromInsee } from "./departments";

const STORAGE_KEY = "faire-info-alerts";

export interface AlertSettings {
  enabled: boolean;
  minGravite: number; // 2 = Alerte, 3 = Urgence
  departments: string[]; // codes dépt surveillés ; [] = toute la France
  categories: Categorie[]; // [] = toutes catégories
}

export const DEFAULT_ALERT_SETTINGS: AlertSettings = {
  enabled: false,
  minGravite: 2,
  departments: [],
  categories: [],
};

export function loadAlertSettings(): AlertSettings {
  if (typeof window === "undefined") return DEFAULT_ALERT_SETTINGS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_ALERT_SETTINGS;
    const parsed = JSON.parse(raw) as Partial<AlertSettings>;
    return { ...DEFAULT_ALERT_SETTINGS, ...parsed };
  } catch {
    return DEFAULT_ALERT_SETTINGS;
  }
}

export function saveAlertSettings(settings: AlertSettings): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    /* quota plein / mode privé : on ignore silencieusement */
  }
}

export function notificationsSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

export function notificationPermission(): NotificationPermission {
  if (!notificationsSupported()) return "denied";
  return Notification.permission;
}

export async function requestNotificationPermission(): Promise<NotificationPermission> {
  if (!notificationsSupported()) return "denied";
  if (Notification.permission !== "default") return Notification.permission;
  try {
    return await Notification.requestPermission();
  } catch {
    return "denied";
  }
}

/** Décide si un événement doit déclencher une alerte selon les réglages. */
export function shouldAlert(event: Event, settings: AlertSettings): boolean {
  if (!settings.enabled) return false;
  if (event.gravite < settings.minGravite) return false;
  if (settings.categories.length > 0 && !settings.categories.includes(event.categorie)) {
    return false;
  }
  if (settings.departments.length > 0) {
    const dept = deptCodeFromInsee(event.lieu_code_insee);
    // Événement sans localisation départementale : on n'alerte pas si un
    // filtre géographique précis est actif (évite le bruit national).
    if (!dept || !settings.departments.includes(dept)) return false;
  }
  return true;
}

/** Envoie une notification navigateur pour un événement (si permission accordée). */
export function sendEventNotification(event: Event): void {
  if (!notificationsSupported() || Notification.permission !== "granted") return;
  const lieu = event.lieu_nom && event.lieu_nom !== "national" ? ` · ${event.lieu_nom}` : "";
  const gravite = event.gravite >= 3 ? "🔴 Urgence" : "🟠 Alerte";
  try {
    const notif = new Notification(`${gravite}${lieu}`, {
      body: event.titre,
      tag: event.id, // évite les doublons si la même alerte revient
      icon: "/favicon.ico",
    });
    notif.onclick = () => {
      window.focus();
      if (event.source_url) window.open(event.source_url, "_blank", "noopener");
      notif.close();
    };
  } catch {
    /* certains navigateurs throttlent : on ignore */
  }
}
