// Enveloppe serveur de la page événement. Le rendu lui-même est client
// (`EventClient`) : l'événement est chargé depuis l'API au montage.
//
// Cette enveloppe n'existe que pour porter `generateStaticParams`, qu'un
// fichier « use client » ne peut pas exporter.
import EventClient from "./EventClient";

export function generateStaticParams(): { id: string }[] {
  // Build web (standalone) : liste vide, `dynamicParams` valant `true` par
  // défaut, n'importe quel identifiant reste servi à la demande — le
  // comportement d'avant, inchangé.
  //
  // Build APK (`output: export`) : Next refuse une liste vide sur une route
  // dynamique, il faut donc figer au moins un chemin. On en fige un seul, et
  // factice. Les identifiants d'événements naissent à l'exécution et
  // disparaissent à la purge (36 h à 30 j) : aucun n'est connu à l'heure où
  // l'on grave les fichiers de l'application. Rien n'y navigue non plus — le
  // permalien est et reste une adresse web, et le partage depuis
  // l'application pointe vers NEXT_PUBLIC_SITE_URL.
  return process.env.NEXT_OUTPUT === "export" ? [{ id: "_" }] : [];
}

export default function EventPage() {
  return <EventClient />;
}
