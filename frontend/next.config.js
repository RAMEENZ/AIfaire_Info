/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Sortie "standalone" : image Docker minimale (~150 Mo au lieu de ~1 Go).
  // Next ne package que les dépendances réellement tracées + un server.js.
  output: "standalone",
  webpack: (config) => {
    config.resolve.fallback = { fs: false };
    return config;
  },
};

module.exports = nextConfig;
