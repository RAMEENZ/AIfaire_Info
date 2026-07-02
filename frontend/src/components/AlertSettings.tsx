"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { ALL_CATEGORIES, CATEGORY_CONFIG } from "@/lib/constants";
import { DEPT_LIST } from "@/lib/departments";
import {
  AlertSettings as Settings,
  loadAlertSettings,
  saveAlertSettings,
  notificationsSupported,
  notificationPermission,
  requestNotificationPermission,
} from "@/lib/notifications";
import { Categorie } from "@/lib/types";

interface AlertSettingsProps {
  onChange?: (settings: Settings) => void;
}

export default function AlertSettings({ onChange }: AlertSettingsProps) {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [permission, setPermission] = useState<NotificationPermission>("default");
  const [deptSearch, setDeptSearch] = useState("");
  const panelRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  // Chargement initial depuis localStorage (client uniquement)
  useEffect(() => {
    setSettings(loadAlertSettings());
    setPermission(notificationPermission());
  }, []);

  // Fermeture au clic extérieur
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        panelRef.current &&
        !panelRef.current.contains(e.target as Node) &&
        btnRef.current &&
        !btnRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const update = (patch: Partial<Settings>) => {
    setSettings((prev) => {
      if (!prev) return prev;
      const next = { ...prev, ...patch };
      saveAlertSettings(next);
      onChange?.(next);
      return next;
    });
  };

  const handleToggleEnabled = async () => {
    if (!settings) return;
    if (!settings.enabled) {
      const perm = await requestNotificationPermission();
      setPermission(perm);
      if (perm !== "granted") {
        update({ enabled: false });
        return;
      }
    }
    update({ enabled: !settings.enabled });
  };

  const toggleDept = (code: string) => {
    if (!settings) return;
    const has = settings.departments.includes(code);
    update({
      departments: has
        ? settings.departments.filter((c) => c !== code)
        : [...settings.departments, code],
    });
  };

  const toggleCategory = (cat: Categorie) => {
    if (!settings) return;
    const has = settings.categories.includes(cat);
    update({
      categories: has
        ? settings.categories.filter((c) => c !== cat)
        : [...settings.categories, cat],
    });
  };

  const filteredDepts = useMemo(() => {
    const q = deptSearch.trim().toLowerCase();
    if (!q) return DEPT_LIST;
    return DEPT_LIST.filter(
      (d) => d.name.toLowerCase().includes(q) || d.code.toLowerCase().includes(q)
    );
  }, [deptSearch]);

  const active = settings?.enabled ?? false;
  const deptCount = settings?.departments.length ?? 0;

  return (
    <div className="relative">
      <button
        ref={btnRef}
        onClick={() => setOpen((v) => !v)}
        className={`flex items-center gap-1 text-xs px-2 py-1 rounded border transition-colors ${
          active
            ? "border-blue-300 dark:border-blue-700 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
            : "border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700/50"
        }`}
        title="Alertes navigateur"
      >
        <svg className="w-3.5 h-3.5" fill={active ? "currentColor" : "none"} stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
        </svg>
        <span className="hidden lg:inline">Alertes</span>
      </button>

      {open && settings && (
        <div
          ref={panelRef}
          className="absolute right-0 top-9 z-[2000] w-72 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-xl p-3 text-xs"
        >
          {!notificationsSupported() ? (
            <p className="text-gray-500 dark:text-gray-400">
              Votre navigateur ne supporte pas les notifications.
            </p>
          ) : (
            <>
              {/* Activation */}
              <label className="flex items-center justify-between cursor-pointer mb-3">
                <span className="font-semibold text-gray-700 dark:text-gray-200">Alertes navigateur</span>
                <button
                  type="button"
                  onClick={handleToggleEnabled}
                  className={`relative w-9 h-5 rounded-full transition-colors ${
                    active ? "bg-blue-600" : "bg-gray-300"
                  }`}
                  role="switch"
                  aria-checked={active}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white dark:bg-gray-800 rounded-full transition-transform ${
                      active ? "translate-x-4" : ""
                    }`}
                  />
                </button>
              </label>

              {permission === "denied" && (
                <p className="text-amber-600 dark:text-amber-400 mb-3">
                  Notifications bloquées dans le navigateur. Autorisez-les dans les
                  réglages du site pour recevoir des alertes.
                </p>
              )}

              {/* Seuil de gravité */}
              <p className="font-semibold text-gray-600 dark:text-gray-300 mb-1.5">Me prévenir pour</p>
              <div className="flex gap-1 mb-3">
                <button
                  onClick={() => update({ minGravite: 2 })}
                  className={`flex-1 py-1 rounded border transition-colors ${
                    settings.minGravite === 2
                      ? "border-orange-400 bg-orange-50 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300 font-medium"
                      : "border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                  }`}
                >
                  🟠 Alerte & +
                </button>
                <button
                  onClick={() => update({ minGravite: 3 })}
                  className={`flex-1 py-1 rounded border transition-colors ${
                    settings.minGravite === 3
                      ? "border-red-400 bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-300 font-medium"
                      : "border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                  }`}
                >
                  🔴 Urgence
                </button>
              </div>

              {/* Catégories (optionnel) */}
              <p className="font-semibold text-gray-600 dark:text-gray-300 mb-1.5">
                Catégories {settings.categories.length === 0 && <span className="font-normal text-gray-400 dark:text-gray-500">(toutes)</span>}
              </p>
              <div className="flex flex-wrap gap-1 mb-3">
                {ALL_CATEGORIES.map((cat) => {
                  const on = settings.categories.includes(cat);
                  return (
                    <button
                      key={cat}
                      onClick={() => toggleCategory(cat)}
                      className={`px-1.5 py-0.5 rounded border transition-colors ${
                        on
                          ? "border-blue-300 dark:border-blue-700 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                          : "border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                      }`}
                    >
                      {CATEGORY_CONFIG[cat]?.icon} {CATEGORY_CONFIG[cat]?.label}
                    </button>
                  );
                })}
              </div>

              {/* Départements */}
              <p className="font-semibold text-gray-600 dark:text-gray-300 mb-1.5">
                Départements{" "}
                {deptCount === 0 ? (
                  <span className="font-normal text-gray-400 dark:text-gray-500">(toute la France)</span>
                ) : (
                  <span className="font-normal text-blue-600 dark:text-blue-400">({deptCount} sélectionné{deptCount > 1 ? "s" : ""})</span>
                )}
              </p>
              <input
                type="search"
                value={deptSearch}
                onChange={(e) => setDeptSearch(e.target.value)}
                placeholder="Filtrer (nom ou code)…"
                className="w-full px-2 py-1 mb-1.5 rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/40 focus:outline-none focus:border-blue-400 focus:bg-white dark:focus:bg-gray-800"
              />
              {deptCount > 0 && (
                <button
                  onClick={() => update({ departments: [] })}
                  className="text-blue-600 dark:text-blue-400 hover:underline mb-1.5"
                >
                  Tout désélectionner
                </button>
              )}
              <div className="max-h-40 overflow-y-auto border border-gray-100 dark:border-gray-700 rounded divide-y divide-gray-50">
                {filteredDepts.map((d) => {
                  const on = settings.departments.includes(d.code);
                  return (
                    <label
                      key={d.code}
                      className="flex items-center gap-2 px-2 py-1 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50"
                    >
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={() => toggleDept(d.code)}
                        className="accent-blue-600"
                      />
                      <span className="text-gray-400 dark:text-gray-500 w-7">{d.code}</span>
                      <span className="text-gray-700 dark:text-gray-200 truncate">{d.name}</span>
                    </label>
                  );
                })}
                {filteredDepts.length === 0 && (
                  <p className="px-2 py-2 text-gray-400 dark:text-gray-500">Aucun département</p>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
