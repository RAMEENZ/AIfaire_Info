import type { MetadataRoute } from "next";

/**
 * robots.txt du site.
 *
 * Le projet consulte scrupuleusement le robots.txt des éditeurs qu'il lit
 * (backend/app/pipeline/robots.py) mais n'en publiait aucun — asymétrie
 * gênante pour un agrégateur.
 *
 * Les pages sont ouvertes : c'est de l'information publique, et l'indexation
 * est souhaitable. `/api/` est écarté du parcours des robots : ce sont des
 * réponses JSON sans valeur en résultat de recherche, et les explorer
 * consommerait la limite de débit pour rien. Le flux Atom reste joignable
 * pour qui le demande — il est déclaré dans l'en-tête des pages, pas
 * découvert en rampant.
 */
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: "/api/" }],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
