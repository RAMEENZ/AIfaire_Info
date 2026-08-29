import type { Metadata, Viewport } from "next";
import "./globals.css";
import { API_BASE_URL } from "@/lib/constants";

// Racine des URL absolues des métadonnées (og:image notamment). Sans elle,
// Next retombe sur http://localhost:3000 : les robots d'aperçu de WhatsApp,
// Slack ou Mastodon iraient alors chercher l'image sur LEUR propre machine,
// et la carte de partage resterait vide — le défaut qu'on corrige ici.
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: "(ai)Faire Info — Agrégateur d'information géolocalisé",
  description:
    "Visualisez en temps réel les événements météo, crues, séismes, transports et actualités en France.",
  icons: {
    icon: "/icon.svg",
    shortcut: "/icon.svg",
    apple: "/icon.svg",
  },
  manifest: "/manifest.json",
  // Autodécouverte du flux : sans ce <link>, le flux Atom existait mais aucun
  // lecteur ne pouvait le trouver depuis l'adresse du site. L'URL est dérivée
  // d'API_BASE_URL (« /api » derrière nginx en production, hôte:port en dev)
  // plutôt que codée en dur, sinon le lien serait faux dans l'un des deux cas.
  alternates: {
    types: {
      "application/atom+xml": [
        { url: `${API_BASE_URL}/feed.rss`, title: "(ai)Faire Info — Actualités" },
      ],
    },
  },
  openGraph: {
    title: "(ai)Faire Info",
    description: "Actualités et alertes géolocalisées en France en temps réel",
    type: "website",
    locale: "fr_FR",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Pas de maximumScale : bloquer le pinch-zoom pénalise l'accessibilité
  // (et Lighthouse le signale). Le zoom utilisateur doit rester possible.
  // viewport-fit=cover : la page s'étend sous l'encoche/la barre home des
  // iPhone — les safe-areas sont gérées via env(safe-area-inset-*).
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#1d4ed8" },
    { media: "(prefers-color-scheme: dark)", color: "#1f2937" },
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fr" suppressHydrationWarning>
      <head>
        {/* Anti-FOUC: set dark class before first paint */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem('theme');if(t==='dark'||(!t&&window.matchMedia('(prefers-color-scheme:dark)').matches)){document.documentElement.classList.add('dark')}}catch(e){}`,
          }}
        />
      </head>
      <body className="bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 antialiased">
        {children}
      </body>
    </html>
  );
}
