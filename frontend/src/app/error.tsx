"use client";

import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("FAIRE Info runtime error:", error);
  }, [error]);

  return (
    <div className="flex flex-col items-center justify-center h-screen gap-4 px-6 text-center bg-gray-50 dark:bg-gray-900/40">
      <svg className="w-12 h-12 text-red-400" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
      </svg>
      <h1 className="text-xl font-semibold text-gray-800 dark:text-gray-100">Une erreur s&apos;est produite</h1>
      <p className="text-sm text-gray-500 dark:text-gray-400 max-w-xs leading-relaxed">
        {error.message || "Une erreur inattendue s'est produite dans l'application."}
      </p>
      <button
        onClick={reset}
        className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-md transition-colors"
      >
        Réessayer
      </button>
    </div>
  );
}
