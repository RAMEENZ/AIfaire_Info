import type { MetadataRoute } from "next";

/**
 * Plan du site.
 *
 * Seules les pages STABLES y figurent. Les pages événement (`/event/[id]`)
 * en sont volontairement absentes : les événements sont purgés au bout de
 * 36 h à 30 jours selon la source, et les lister produirait un plan
 * majoritairement composé de 404 — ce qui dégrade la confiance qu'un moteur
 * accorde au site, alors que le but recherché est l'inverse.
 */
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export default function sitemap(): MetadataRoute.Sitemap {
  const maintenant = new Date();
  return [
    { url: SITE_URL, lastModified: maintenant, changeFrequency: "hourly", priority: 1 },
    { url: `${SITE_URL}/stats`, lastModified: maintenant, changeFrequency: "daily", priority: 0.6 },
    {
      url: `${SITE_URL}/tendances`,
      lastModified: maintenant,
      changeFrequency: "daily",
      priority: 0.6,
    },
  ];
}
