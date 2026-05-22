import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FAIRE Info — Agrégateur d'information géolocalisé",
  description:
    "Visualisez en temps réel les événements météo, crues, séismes, transports et actualités en France.",
  icons: {
    icon: "/favicon.ico",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fr">
      <body className="bg-gray-50 text-gray-900 antialiased">{children}</body>
    </html>
  );
}
