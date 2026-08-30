# Analyse complète du code et des branches — (ai)Faire Info

*Revue conduite le 29 août 2026 sur `main` @ `2a379e0` et sur les 7 branches distantes.*

Cette analyse a été **exécutée**, pas seulement lue : les suites de tests backend,
frontend et de bout en bout ont été installées et lancées dans un conteneur neuf,
les branches ont été comparées à `main`, et les journaux CI des six pull requests
ouvertes ont été dépouillés. Les constats de la partie 8 sont tous reproduits ou
tirés d'un journal d'exécution, jamais déduits.

---

## 1. Ce qu'est le projet

Une application web qui agrège l'actualité publique française en quasi temps réel,
la catégorise et la géolocalise par IA, puis l'affiche sur une carte de France
doublée d'un fil et d'un brief rédigé trois fois par jour.

- **Backend** : Python / FastAPI, 14 connecteurs, ordonnanceur APScheduler, PostgreSQL + PostGIS.
- **Frontend** : Next.js 15 (App Router), React 19, Leaflet, Tailwind, PWA avec service worker.
- **IA** : Mistral (extraction lieu/catégorie/résumé/tags + briefs), repli Ollama, puis repli par règles.
- **Exploitation** : Docker Compose (7 services), nginx interne, tunnel Cloudflare comme unique porte d'entrée.

## 2. Chiffres

| Mesure | Valeur |
|---|---|
| Code applicatif (hors `node_modules`) | ~25 100 lignes |
| Backend `app/` | 11 091 lignes, 90 fichiers Python |
| Tests backend | 4 678 lignes — **541 tests, 18 ignorés** |
| Frontend `src/` + `e2e/` | 7 870 lignes (39 `.ts`, 23 `.tsx`) |
| Tests frontend | **70 unitaires (Vitest) + 56 de bout en bout (Playwright)** |
| Flux RSS | **848** entrées dans `presse_rss.py` (conforme au README) |
| Connecteurs | 14 |
| Historique git | 50 commits, tous entre le 02 et le 22/08/2026 |

Le rapport de test / code est de ~1 pour 2,4 côté backend. C'est élevé, et la
couverture ne se contente pas des fonctions pures : `test_integration_api.py`
vérifie le SQL réellement émis sur une vraie base PostGIS, et les tests E2E
rejouent l'interface à onze largeurs d'écran.

## 3. Architecture

### Topologie de déploiement

```
Internet → Cloudflare (TLS, WAF) → cloudflared (tunnel sortant)
                                        ↓ réseau Docker interne
                                      nginx ──/api/──→ backend:8000
                                            └──/─────→ frontend:3000
                                                        db (PostGIS) · redis
                                                        autoheal (watchdog)
```

Tous les ports publiés le sont sur `127.0.0.1` : aucun service n'est joignable
en direct depuis Internet. `autoheal` redémarre le backend dès que son
healthcheck passe `unhealthy` — Docker seul ne le fait jamais.

### Le pipeline

```
Sources → Connecteurs (parallèle, timeout 120 s/connecteur)
        → Filtre marchand → Dédup par titre → Plafond round-robin par flux
        → Extraction (Mistral → Ollama → règles)
        → Géocodage (table locale 35 000 communes → BAN en repli)
        → Upsert PostgreSQL par lots de 10 → Cache Redis invalidé → Push
```

Rythme : ingestion complète à 7h/12h/19h, passage horaire des seules sources
d'alerte à :30 (météo, crues, séismes — sans coût LLM), agrégats à :50, contrôle
de fraîcheur à :45, purge à 3h, briefs à 9h/14h/21h.

## 4. Backend — lecture module par module

### Ce qui structure le code

- **`config.py`** — 40 réglages typés (pydantic-settings), chacun documenté par la
  panne qu'il évite. Deux garde-fous *fail-closed* en production : refus de démarrer
  avec un mot de passe de base faible, neutralisation du CORS `*`.
- **`pipeline/ingestor.py`** — verrou global d'ingestion, sauvegarde par lots (les
  événements apparaissent au fil de l'eau et survivent à un redémarrage),
  remplacement atomique en une transaction pour les sources temps réel, statut de
  connecteur avec compteur d'échecs consécutifs et webhook de panne *et* de
  rétablissement.
- **`pipeline/extractor.py`** — le cœur du produit et le fichier le plus subtil.
  Prompt long pour Mistral, prompt court pour les petits modèles locaux, plafond de
  gravité déterministe qui borne les hallucinations du modèle, cascade de replis
  pour le lieu (code INSEE de l'URL > commune du titre > toponyme), et surtout un
  refus systématique de placer un marqueur douteux : un événement « national »
  reste hors carte, un faux marqueur trompe.
- **`pipeline/robots.py`** — réimplémentation de l'analyse `robots.txt` selon la
  RFC 9309, parce que `RobotFileParser` de la bibliothèque standard applique encore
  la convention de 1996 et faisait disparaître les interdictions des éditeurs les
  plus stricts. Le refus de n'importe quel agent d'IA courant vaut refus.
- **`pipeline/fetcher.py`** — anti-SSRF sérieux : résolution DNS et vérification de
  **toutes** les adresses retournées, gestion des IPv6 mappées IPv4, revalidation à
  chaque redirection, corps borné à 5 Mio.
- **`pipeline/mistral_client.py`** — client partagé, cadence minimale à la source
  (le vrai garde-fou contre les 429), reprise avec respect de `Retry-After` et bruit
  aléatoire.
- **`api/routes/health.py`** — `/healthz` teste la santé réelle (ordonnanceur vivant
  *et* données fraîches), pas « l'API répond ». La logique de décision est une
  fonction pure, donc testable hors ligne.

### Surface d'API

`/events` (paginé, filtré, trié, résumés tronqués), `/events/map` (charge utile
allégée), `/events/{id}`, `/events/stream` (SSE plafonné), `/events/timeline`,
`/stats`, `/stats/geo`, `/stats/history`, `/trends`, `/brief`, `/brief/local`,
`/brief/history`, `/feed.rss` (Atom), `/health`, `/health/feeds`, `/metrics`,
`/healthz`, `/push/*`, et deux déclencheurs protégés par clé (`/ingest/run`,
`/brief/run`).

Les entrées sont validées sans exception : `dept` par expression régulière avant
tout `LIKE` de préfixe, `bbox` bornée en latitude/longitude, `q` échappé pour
`ILIKE`, catégories confrontées à la liste canonique. Le total de `/events` est
obtenu par fonction fenêtre `count() OVER()`, ce qui évite de réévaluer le filtre
spatial une seconde fois.

## 5. Frontend

Une seule page dense (`page.tsx`, 875 lignes) qui orchestre carte, fil, brief,
filtres, timeline et statut, plus trois pages secondaires. Points remarquables :

- **État partageable** : filtres, département et recherche sont sérialisés dans
  l'URL (`replaceState`, pas `pushState` — sinon chaque frappe empilerait une
  entrée d'historique).
- **Carte et fil découplés** : la carte a sa propre source (`/events/map`) pour
  rester complète quand le fil n'affiche que sa première page ; la fiche complète
  d'un marqueur n'est chargée qu'à l'ouverture de sa bulle, avec cache borné à 200
  entrées.
- **Durcissement des réponses** : une réponse 200 au corps inattendu est rejetée au
  point d'entrée plutôt que de casser plus loin.
- **Hors ligne** : service worker à priorité réseau, caches versionnés et purgés à
  l'activation, HTML jamais servi depuis le cache tant que le réseau répond.
- **Accessibilité** : couleur de texte calculée sur la luminance du fond, audit
  axe-core automatisé dans la CI, pinch-zoom laissé actif.

## 6. Ce que j'ai exécuté

| Vérification | Résultat |
|---|---|
| `pytest` (backend, hors ligne) | **541 passés, 18 ignorés** en 4 s |
| `ruff check .` | **1 erreur** — voir constat A |
| `npx tsc --noEmit` | **passe** |
| `npm test` (Vitest) | **70 passés**, 10 fichiers |
| `npm run build` + `npm run test:e2e` | **56 passés** en 29 s |
| `Settings()` depuis `backend/.env.example` | **échec** — voir constat B |

Autrement dit : le code de `main` est sain, seul l'outillage autour ne l'est pas.

## 7. Branches et pull requests

Huit branches distantes, dont six portent une PR Dependabot ouverte.

| Branche | PR | CI | Cause exacte de l'échec |
|---|---|---|---|
| `main` | — | 🔴 | `ruff` (constat A) — l'étape `pytest` est **sautée** |
| `claude/gracious-shannon-qoc6tn` | — | — | Identique à `main` (0 commit d'écart), branche morte |
| `.../types/node-26.2.0` | [#63](https://github.com/RAMEENZ/AIfaire_Info/pull/63) | 🟢 | **Seule PR mergeable en l'état** |
| `.../python-minor-patch` | [#60](https://github.com/RAMEENZ/AIfaire_Info/pull/60) | 🔴 | Uniquement `ruff`, hérité de `main` — verte avant rebase |
| `.../npm-minor-patch` | [#64](https://github.com/RAMEENZ/AIfaire_Info/pull/64) | 🔴 | Uniquement `ruff`, hérité de `main` ; ses 4 autres jobs passent |
| `.../tailwindcss-4.3.3` | [#59](https://github.com/RAMEENZ/AIfaire_Info/pull/59) | 🔴 | Vraie rupture : le build webpack échoue sur `globals.css` |
| `.../next-16.3.1` | [#61](https://github.com/RAMEENZ/AIfaire_Info/pull/61) | 🔴 | Vraie rupture : Turbopack refuse une config `webpack` sans config `turbopack` |
| `.../jsdom-30.0.1` | [#62](https://github.com/RAMEENZ/AIfaire_Info/pull/62) | 🔴 | Vraie rupture : `webidl.util.markAsUncloneable is not a function` — Node 20 trop ancien |

Trois enseignements :

1. **Deux PR sur six ne sont rouges que par contagion.** Corriger le lint de `main`
   les repasse au vert sans y toucher.
2. **Les trois majors demandent chacune une migration précise**, pas un simple bump :
   - Tailwind 4 : `postcss.config.js` charge `tailwindcss` comme greffon PostCSS alors
     que la v4 exige `@tailwindcss/postcss`, et `globals.css` utilise encore
     `@tailwind base/components/utilities` là où la v4 attend `@import "tailwindcss"`.
   - Next 16 : Turbopack devient le moteur par défaut et refuse le
     `webpack: (config) => …` de `next.config.js`. Le correctif est court — ajouter
     `turbopack: {}`, ou forcer `--webpack` — d'autant que le `fs: false` qu'il pose
     n'est probablement plus nécessaire.
   - jsdom 30 : il embarque un `undici` qui exige un Node plus récent que celui de la
     CI. Ce n'est pas un problème de jsdom, c'est **Node 20 qui est en fin de vie** —
     les journaux GitHub Actions le signalent déjà à chaque run.
3. **La branche `claude/gracious-shannon-qoc6tn` est un doublon exact de `main`** :
   rien à y merger, elle peut être supprimée.

## 8. Constats classés

### A — La CI de `main` est rouge depuis le 22/08, et les tests backend ne tournent plus

`backend/tests/test_fetcher_borne.py:13` importe `httpx` sans l'utiliser. `ruff`
le rejette (F401), le job « Backend — tests » échoue **à l'étape lint**, et
l'étape `pytest` qui suit est marquée `skipped`.

Conséquence réelle : depuis une semaine, aucune exécution des 541 tests backend
sur `main` — le filet de sécurité le plus fourni du dépôt est décroché sans que
rien ne le dise, puisque l'échec s'affiche comme un problème de style. Les quatre
autres jobs (Docker, frontend, E2E, intégration PostGIS) passent, ce qui rend la
CI rouge « pour une virgule » et invite à s'y habituer.

Correctif : supprimer la ligne. Une commande, `ruff check --fix`.

### B — `cp .env.example .env` empêche le backend de démarrer en local

`backend/.env.example` (lignes 20-23) déclare encore
`SCHEDULER_HOUR_MORNING/MIDDAY/EVENING/NIGHT`, quatre réglages disparus lors du
passage à `INGEST_HOURS` / `BRIEF_HOURS`. `Settings` est en `extra='forbid'` :
au chargement du fichier, pydantic lève quatre `extra_forbidden` et le processus
ne démarre pas.

Reproduit tel quel avec la procédure du README (« ### Backend › `cp .env.example .env` »).
Portée limitée au **développement local** : sous Docker, `env_file` passe les
clés comme variables d'environnement, que pydantic ignore silencieusement — j'ai
vérifié les deux chemins. La production n'est donc pas menacée, mais tout nouveau
contributeur bute sur un mur au troisième pas du README.

Le fichier omet par ailleurs les réglages devenus configurables le 22/08
(`INGEST_HOURS`, `BRIEF_HOURS`, `RESPECT_ROBOTS_TXT`, `MISTRAL_*`,
`FEED_HOST_MIN_INTERVAL_SECONDS`, `FILTER_COMMERCIAL_CONTENT`…).

### C — Le cache Redis de `/events` ne sert pratiquement jamais

`_events_cache_key` (`backend/app/api/routes/events.py:67`) fabrique la clé à
partir de tous les paramètres, `depuis` compris. Or le frontend envoie
`new Date(Date.now() - heures * 3600000).toISOString()`, recalculé à chaque
requête (`frontend/src/app/page.tsx:180` pour le fil, `:261` pour la carte) :
une horodate à la milliseconde, donc **une clé différente à chaque appel**.

Deux visiteurs qui arrivent à la même seconde produisent deux clés distinctes et
deux requêtes PostGIS. Le cache ne mutualise rien ; il accumule des entrées à
usage unique pendant 120 s, et l'invalidation en fin d'ingestion les balaie une à
une. Le travail que le cache était censé économiser — celui du filtre spatial et
du tri — est intégralement payé à chaque visite.

Correctif peu coûteux et sans effet visible : arrondir `depuis` à la minute dans
la clé de cache uniquement (la requête, elle, garde la valeur exacte).

### D — Les contours départementaux viennent d'un dépôt GitHub tiers, à l'exécution

`frontend/src/components/FranceMap.tsx:34` charge le GeoJSON des départements
depuis `raw.githubusercontent.com/gregoiredavid/france-geojson/master/…`, chez
chaque visiteur, sur une branche `master` non épinglée.

C'est exactement la dépendance que le projet a supprimée en août pour
`leaflet.heat` (« du code exécutable servi par un tiers sans contrôle
d'intégrité »). Le risque est ici moindre — de la donnée, pas du code — mais les
trois autres coûts demeurent : le calque disparaît si le fichier est déplacé ou
renommé en amont, il ne fonctionne pas en mode hors ligne alors que c'est une
promesse affichée de l'application, et il impose de garder
`connect-src https://raw.githubusercontent.com` dans la CSP.

Le fichier simplifié pèse quelques centaines de kilo-octets : le poser dans
`public/` clôt le sujet, comme cela a été fait pour les icônes Leaflet.

### E — Dérive documentaire sur les heures de brief

`README.md:42` annonce 9h/14h/21h (conforme à `BRIEF_HOURS = "9,14,21"` et à la
table des variables, ligne 348). `README.md:122` et
`backend/app/api/routes/events.py:444` annoncent encore 9h/13h/20h. Deux des
trois mentions sont fausses.

### F — Le README fait exécuter une migration inutile

`README.md:89` demande `alembic upgrade head` pour créer `push_subscriptions`.
Or `init_db()` importe `app.models` en entier : `PushSubscription` et `DailyStat`
sont enregistrées dans `Base.metadata` et `create_all` les crée déjà au
démarrage. L'instruction est sans danger mais entretient la confusion sur le
mécanisme réellement en vigueur.

### G — Trois mécanismes de schéma coexistent *(déjà documenté)*

`create_all` au démarrage, du DDL manuel idempotent dans `migrate_db()`, et
quatre révisions Alembic que rien n'exécute jamais. Le README l'appelle lui-même
« le point le plus fragile du dépôt » et explique pourquoi il n'a pas été traité.
Je confirme le diagnostic et l'arbitrage : unifier suppose de toucher au schéma
d'une base en production, ce n'est pas un correctif de passage. À traiter comme
un chantier daté, pas comme une dette qu'on redécouvre chaque trimestre.

### H — Dette d'accessibilité plafonnée *(déjà documenté)*

Quatre violations de contraste (3,3:1 à 4,2:1 pour 4,5:1 requis) sont tolérées par
une constante dans `e2e/a11y.spec.ts`, avec la justification qu'en sortir demande
d'assombrir la charte graphique. Le plafond est bien conçu — toute nouvelle
occurrence fait échouer la suite — mais il attend un arbitrage qui n'est
planifié nulle part.

### I — Observations mineures

- `ALERT_CONNECTOR_NAMES` ne compte que 3 des 6 connecteurs `replace_on_ingest` :
  SNCF, Bison Futé, incendies et OpenSky ne sont rafraîchis que 3 fois par jour,
  soit jusqu'à 12 h de retard sur des données qui se veulent temps réel. C'est
  peut-être délibéré (ces sources n'ont pas la criticité des vigilances), mais
  rien ne le dit.
- `_replace_source_events` insère avec `on_conflict_do_nothing` sur `source_url` :
  un article présent sous une autre source est silencieusement perdu du lot.
  Situation improbable, trace absente.
- `docs/RAPPORT.md` date du 3 août et annonce « ~868 flux » là où le code en
  compte 848 ; il décrit aussi Next.js 14 alors que le projet est en 15.
- La version Python diverge : `Dockerfile` et CI en 3.13, mais rien n'empêche un
  contributeur de développer en 3.11 — la suite y passe intégralement (vérifié).

## 9. Ce qui distingue ce dépôt

Il faut le dire clairement, parce que c'est rare : **la qualité d'ingénierie est
au-dessus de ce qu'on observe habituellement sur un projet de cette taille.**

- **Chaque garde-fou porte la trace de l'incident qui l'a motivé**, daté et chiffré.
  Le commentaire de `MISTRAL_MIN_INTERVAL_SECONDS` ne dit pas « limite le débit », il
  dit « 5 articles sur 15 ont épuisé leurs quatre tentatives en 429, et ce sont
  exactement les 5 ressortis sans tags ». C'est de la documentation qui survit à
  ses auteurs.
- **Les compromis sont explicités et chiffrés**, pas subis : le coût du respect de
  `robots.txt` est mesuré (−7,6 % de longueur de résumé), et la première alarme
  (−25 %) est corrigée comme un effet d'échantillon plutôt que propagée.
- **Les tests visent les régressions réelles** : onze largeurs d'écran parce que le
  défaut d'août vivait entre le mobile et le bureau ; une API simulée qui reproduit
  fidèlement les *omissions* du vrai backend, parce qu'une simulation trop généreuse
  avait laissé passer la régression des bulles de carte.
- **Le principe directeur du produit est tenu partout** : un faux marqueur trompe
  plus qu'un marqueur absent. Ce raisonnement se retrouve dans `commune_from_text`,
  `est_lieu_connu`, le seuil de confiance géographique, le plafond de gravité et
  jusque dans le prompt d'extraction.
- **La sécurité est traitée sérieusement** : anti-SSRF avec résolution DNS complète,
  CSP sans `unsafe-eval` vérifiée par un test E2E, `hmac.compare_digest` sur la clé
  d'ingestion, échappement `ILIKE`, `fail-closed` en production, ports sur loopback.

## 10. Recommandations, par ordre de rendement

| # | Action | Effort | Effet |
|---|---|---|---|
| 1 | Supprimer l'import mort (constat A) | 1 ligne | Rend le vert à `main` **et** aux PR #60 et #64 ; remet 541 tests en service |
| 2 | Corriger `.env.example` (constat B) | 10 min | Débloque l'installation locale documentée |
| 3 | Fusionner #63 (`@types/node`), puis #60 et #64 une fois (1) fait | 5 min | Trois PR soldées |
| 4 | Passer la CI et le `Dockerfile` frontend à **Node 22** | 30 min | Débloque #62, sort d'une version que GitHub Actions déprécie déjà |
| 5 | Arrondir `depuis` dans la clé de cache (constat C) | 30 min | Rend au cache Redis la fonction pour laquelle il a été écrit |
| 6 | Vendoriser le GeoJSON départemental (constat D) | 1 h | Une dépendance tierce de moins à l'exécution, carte complète hors ligne |
| 7 | Harmoniser les heures de brief et l'instruction Alembic (E, F) | 15 min | Documentation qui cesse de se contredire |
| 8 | Traiter #61 (Next 16) et #59 (Tailwind 4) comme deux migrations datées | ~½ j chacune | Sortir de deux majors qui vont continuer à s'accumuler |
| 9 | Planifier l'unification du schéma (constat G) | ~1 j | Éteindre le risque que le dépôt désigne lui-même comme le sien |

Les points 1 à 4 tiennent en une heure et referment la moitié du tableau de bord.

---

## 11. Suites données (même branche)

Les recommandations 1 à 5, 7 et 8 ont été appliquées et fusionnées. Les constats
A, B, C, E et F sont clos, et tout ce qui précède se lit comme l'état **avant**
correction. Restent ouvertes : la recommandation 6 (vendoriser le GeoJSON) et la
9 (unification du schéma), cette dernière délibérément.

| Recommandation | État | Vérification |
|---|---|---|
| 1 — supprimer l'import mort | ✅ appliquée | `ruff check .` passe, `pytest` : 541 passés |
| 2 — corriger `.env.example` | ✅ appliquée | `Settings(_env_file=…)` charge ; deux tests de non-régression ajoutés |
| 3 — fusionner #63, #60, #64 | ✅ fusionnées | #60 et #64 sont passées au vert **sans un seul changement**, une fois (1) sur `main` |
| 4 — passer à Node 22 | ✅ appliquée | jsdom 30 + Node 22 : **70 tests passent** (mesuré) ; #62 fusionnée ensuite |
| 5 — clé de cache Redis | ✅ appliquée | **Vérifiée en production** : `+1 hit` sur le cas qui échouait (#70) |
| 6 — vendoriser le GeoJSON | ⏸ non traitée | Reste une dépendance tierce à l'exécution |
| 7 — heures de brief, instruction Alembic | ✅ appliquée | Incluse dans #65 puis #70 |
| 8 — migrations Next 16 et Tailwind 4 | ✅ appliquées | #67 et #68 ; #59 et #61 fermées comme obsolètes |
| 9 — unifier le schéma | ⏸ non traitée | Chantier à dater : touche au schéma d'une base en production |
| — healthcheck du frontend | ✅ ajouté | Hors recommandations : révélé par le déploiement du 30/08 (#70) |

Détails :

- **Correctif 2** ne se limite pas à retirer les quatre clés mortes. Le fichier
  d'exemple omettait aussi les **19 réglages** que `config.py` expose réellement
  — dont `INGEST_HOURS`, `BRIEF_HOURS` et `RESPECT_ROBOTS_TXT`, devenus
  configurables le 22/08 mais jamais documentés à cet endroit. Ils y figurent
  désormais avec leur valeur par défaut. Un en-tête explique la règle qui rendait
  le piège possible : ce fichier étant lu *comme un fichier .env*, toute clé qui
  n'est pas un réglage du backend doit y rester commentée — ce qui vaut aussi
  pour `POSTGRES_PASSWORD` et `CLOUDFLARE_TUNNEL_TOKEN`, qui relèvent du `.env`
  de la racine.

- **Deux tests verrouillent le correctif 2** (`tests/test_config.py`) : l'un
  vérifie que chaque clé active de `.env.example` correspond à un champ de
  `Settings`, l'autre charge réellement le fichier. J'ai confirmé qu'ils
  échouent bien en réintroduisant `SCHEDULER_HOUR_MORNING`, puis restauré le
  fichier.

- **Correctif 4** repose sur une mesure et non sur une hypothèse : jsdom 30.0.1
  installé sous Node 22.22.2 fait passer les 70 tests, là où la CI en Node 20
  échouait sur `webidl.util.markAsUncloneable is not a function`. La PR #62 est
  donc débloquée par ce seul changement de version.
  Une réserve était posée ici : faute de démon Docker dans l'environnement de
  vérification, l'image `node:22-alpine` n'avait pas pu être construite
  localement. **Elle est levée** — le job « Images Docker » de la CI l'a
  construite sans erreur sur #65, puis sur #67 et #68.

### Les deux migrations majeures

Traitées après coup, chacune dans sa propre PR, et chacune avec une surprise que
le simple bump n'aurait pas révélée.

**Tailwind 4** (#67) — le risque connu de la v4 est la couleur de bordure par
défaut, qui passe de `gray-200` à `currentColor`. Sur les 84 classes `border*`
du dépôt, **aucune** n'était dépourvue de couleur explicite : c'est ce qui
rendait la migration abordable, et cela se vérifiait avant de commencer. Le
codemod officiel a traité les renommages (26 `flex-shrink-0`, 6 `outline-none`,
l'échelle `shadow`/`rounded`) et surtout `darkMode: "class"`, sans quoi les 456
usages de `dark:` auraient cessé de suivre le bouton de thème.

Ce que le codemod ne pouvait pas voir : la Preflight de la v4 écrit
`font-family: var(--default-font-family, -apple-system, …)`, variable définie
nulle part ici. Toute l'interface basculait sur cette pile de repli. Mesuré sur
l'application montée — mêmes tailles, mêmes espacements, même largeur de carte,
mais un bouton de filtre passant de **78,2 px à 73,4 px**. La police rendue
n'était plus la même, partout, et aucun test ne l'aurait signalé : la
typographie ne casse rien, elle décale. `--font-sans` est désormais déclarée
explicitement.

**Next 16** (#68) — Turbopack, moteur par défaut, refuse de démarrer si une
configuration `webpack` traîne sans configuration `turbopack` en regard. Next
propose de « faire taire l'erreur » avec un `turbopack: {}` vide ; le bloc
incriminé ne posant qu'un `resolve.fallback = { fs: false }` inutile ici, il a
été retiré plutôt que neutralisé. Le build signalait par ailleurs
« `z-index` is currently not supported » à chaque passage : Satori empile dans
l'ordre du document, l'image de partage a été rendue et regardée avant de
retirer la propriété inopérante.

Captures avant/après en 1366 px et 390 px, thèmes clair et sombre : celles de
Next 16 sont **identiques à l'octet** à celles prises après Tailwind 4, qui sont
elles-mêmes indiscernables de la référence v3.

### Le constat C, de bout en bout

C'est le seul constat de ce rapport dont la boucle a été fermée jusqu'à la
mesure en production. Elle mérite d'être écrite, parce que chaque maillon
disait quelque chose que le précédent ne pouvait pas dire.

| Étape | Ce qu'on a appris |
|---|---|
| **Lecture** | `_events_cache_key` reprend `depuis` tel quel ; le front l'envoie à la milliseconde, recalculé à chaque requête |
| **Mesure (30/08)** | `keyspace_hits:0` · `keyspace_misses:104` — pas un taux faible : aucune réutilisation, jamais |
| **Correctif (#70)** | `depuis` et `avant` arrondis à la minute dans la clé seulement ; six tests de non-régression |
| **Vérification (30/08)** | Deux requêtes ne différant que par les microsecondes : `+1 miss`, puis **`+1 hit`** |

Une nuance que la mesure a apportée et que la lecture seule ne donnait pas :
avec ~106 requêtes sur toute la vie du conteneur Redis, deux visiteurs tombent
rarement dans la même fenêtre de 120 s. Le correctif lève une impossibilité
**structurelle** — aucune clé ne pouvait être relue — mais le gain restera
latent tant que le trafic n'est pas concurrent. Le cache est désormais capable
de servir ; il ne deviendra utile qu'avec de l'affluence.
