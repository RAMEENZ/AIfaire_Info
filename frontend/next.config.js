/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Sortie "standalone" : image Docker minimale (~150 Mo au lieu de ~1 Go).
  // Next ne package que les dépendances réellement tracées + un server.js.
  //
  // `NEXT_OUTPUT=export` bascule sur l'export statique, utilisé par le build
  // APK (Capacitor) : la WebView embarque des fichiers, pas un serveur Node.
  // Toutes les pages du site sont déjà des composants client qui appellent
  // l'API au runtime — l'export ne perd donc aucune donnée, seulement le
  // rendu serveur des métadonnées, sans objet dans une application native.
  output: process.env.NEXT_OUTPUT === "export" ? "export" : "standalone",
  // L'export écrit des fichiers : `/stats` devient `stats/index.html` plutôt
  // que `stats.html`, seule forme qu'un serveur de fichiers (celui de la
  // WebView Capacitor) résout sans règle de réécriture.
  trailingSlash: process.env.NEXT_OUTPUT === "export",
  // Pas de bloc `webpack` ici, et c'est délibéré. Depuis Next 16, Turbopack est
  // le moteur de build par défaut et REFUSE de démarrer s'il trouve une
  // configuration webpack sans configuration Turbopack en regard :
  //   « This build is using Turbopack, with a `webpack` config and no
  //     `turbopack` config. »
  // C'est ce qui faisait échouer la montée de version.
  //
  // Le bloc retiré ne posait qu'un `resolve.fallback = { fs: false }` — un
  // garde-fou contre un module qui importerait `fs` côté navigateur. Le dépôt
  // n'en contient aucun (vérifié), et Turbopack traite les modules Node en
  // contexte client sans qu'on ait à le lui déclarer. Le remplacer par un
  // `turbopack: {}` vide aurait fait taire l'erreur sans rien apporter.
};

module.exports = nextConfig;
