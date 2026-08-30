/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Sortie "standalone" : image Docker minimale (~150 Mo au lieu de ~1 Go).
  // Next ne package que les dépendances réellement tracées + un server.js.
  output: "standalone",
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
