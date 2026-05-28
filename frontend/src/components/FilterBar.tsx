"use client";

import { ALL_CATEGORIES, CATEGORY_CONFIG } from "@/lib/constants";
import { Categorie, EventFilters } from "@/lib/types";

const DEFAULT_FILTERS: EventFilters = {
  categories: ALL_CATEGORIES,
  gravite_min: 0,
  depuis_heures: 48,
};

interface FilterBarProps {
  filters: EventFilters;
  onCategoriesChange: (categories: Categorie[]) => void;
  onGraviteChange: (gravite_min: number) => void;
  onDepuisHeuresChange: (heures: number) => void;
  onRefresh: () => void;
  onResetFilters?: () => void;
  isLoading: boolean;
  eventCounts?: Partial<Record<Categorie, number>>;
}

const GRAVITE_OPTIONS: { value: number; label: string }[] = [
  { value: 0, label: "Tous" },
  { value: 1, label: "Vigilance+" },
  { value: 2, label: "Alerte+" },
  { value: 3, label: "Urgence" },
];

const DEPUIS_OPTIONS: { value: number; label: string }[] = [
  { value: 24, label: "24h" },
  { value: 48, label: "48h" },
  { value: 168, label: "7j" },
  { value: 720, label: "30j" },
];

export default function FilterBar({
  filters,
  onCategoriesChange,
  onGraviteChange,
  onDepuisHeuresChange,
  onRefresh,
  onResetFilters,
  isLoading,
  eventCounts,
}: FilterBarProps) {
  function toggleCategory(cat: Categorie) {
    if (filters.categories.includes(cat)) {
      if (filters.categories.length === 1) return;
      onCategoriesChange(filters.categories.filter((c) => c !== cat));
    } else {
      onCategoriesChange([...filters.categories, cat]);
    }
  }

  function selectAllCategories() {
    onCategoriesChange([...ALL_CATEGORIES]);
  }

  const allSelected = filters.categories.length === ALL_CATEGORIES.length;
  const isDefault =
    allSelected &&
    filters.gravite_min === DEFAULT_FILTERS.gravite_min &&
    filters.depuis_heures === DEFAULT_FILTERS.depuis_heures;

  return (
    <div className="flex items-center gap-3 flex-wrap flex-1 min-w-0">
      {/* Categories */}
      <div className="flex items-center gap-1 flex-wrap">
        <button
          onClick={selectAllCategories}
          className={`text-xs px-2 py-1 rounded border transition-colors ${
            allSelected
              ? "bg-gray-700 text-white border-gray-700"
              : "bg-white text-gray-600 border-gray-300 hover:border-gray-500"
          }`}
          title="Toutes les catégories"
        >
          Tout
        </button>

        {ALL_CATEGORIES.map((cat) => {
          const config = CATEGORY_CONFIG[cat];
          const active = filters.categories.includes(cat);
          return (
            <button
              key={cat}
              onClick={() => toggleCategory(cat)}
              title={config.label}
              className={`text-xs px-2 py-1 rounded border transition-colors flex items-center gap-1 ${
                active
                  ? "text-white border-transparent"
                  : "bg-white text-gray-400 border-gray-200 hover:border-gray-400"
              }`}
              style={
                active
                  ? { backgroundColor: config.color, borderColor: config.color }
                  : undefined
              }
            >
              <span>{config.icon}</span>
              <span className="hidden lg:inline">{config.label}</span>
              {eventCounts?.[cat] !== undefined && eventCounts[cat]! > 0 && (
                <span className={`text-[10px] font-semibold ${active ? "opacity-80" : "text-gray-500"}`}>
                  {eventCounts[cat]}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Gravite filter */}
      <div className="flex items-center gap-1">
        <span className="text-xs text-gray-500 hidden sm:inline">Gravité :</span>
        {GRAVITE_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => onGraviteChange(opt.value)}
            className={`text-xs px-2 py-1 rounded border transition-colors ${
              filters.gravite_min === opt.value
                ? "bg-gray-700 text-white border-gray-700"
                : "bg-white text-gray-600 border-gray-300 hover:border-gray-500"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Période */}
      <div className="flex items-center gap-1">
        <span className="text-xs text-gray-500 hidden md:inline">Période :</span>
        {DEPUIS_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => onDepuisHeuresChange(opt.value)}
            className={`text-xs px-2 py-1 rounded border transition-colors ${
              filters.depuis_heures === opt.value
                ? "bg-gray-700 text-white border-gray-700"
                : "bg-white text-gray-600 border-gray-300 hover:border-gray-500"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Reset filters */}
      {!isDefault && onResetFilters && (
        <button
          onClick={onResetFilters}
          className="flex items-center gap-1 text-xs px-2 py-1 rounded border border-gray-300 text-gray-500 hover:bg-gray-100 transition-colors"
          title="Réinitialiser tous les filtres"
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
          <span className="hidden sm:inline">Réinit.</span>
        </button>
      )}

      {/* Refresh */}
      <button
        onClick={onRefresh}
        disabled={isLoading}
        className="flex items-center gap-1 text-xs px-3 py-1 rounded border border-blue-300 text-blue-700 bg-blue-50 hover:bg-blue-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors ml-auto"
        title="Actualiser les données"
      >
        <svg
          className={`w-3 h-3 ${isLoading ? "animate-spin" : ""}`}
          fill="none"
          stroke="currentColor"
          strokeWidth={2.5}
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
          />
        </svg>
        <span className="hidden sm:inline">Actualiser</span>
      </button>
    </div>
  );
}
