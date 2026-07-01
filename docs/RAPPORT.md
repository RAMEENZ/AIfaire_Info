# FAIRE Info — Rapport complet du projet

*Agrégateur d'information géolocalisé pour la France — état au 1er juillet 2026*

---

## 1. Résumé exécutif

**FAIRE Info** est une application web qui **agrège en quasi temps réel l'actualité
publique française** (météo, crues, séismes, énergie, santé, transport, ordre
public, faits divers, sport, économie, politique, culture…) provenant de sources
officielles et de la presse, **la catégorise et la géolocalise automatiquement**,
puis l'affiche sur une **carte interactive de France** doublée d'un fil
d'actualités et d'un **brief quotidien** rédigé par IA.

- **Stack** : Python 3.13 / FastAPI (backend), Next.js 14 / Leaflet (frontend),
  PostgreSQL 16 + PostGIS (base géospatiale), Mistral AI (extraction & briefs),
  le tout orchestré par Docker Compose et exposé via un tunnel Cloudflare.
- **Sources** : 15 connecteurs, dont un agrégateur de **~877 flux RSS** de presse
  nationale et régionale.
- **Principe** : une chaîne de traitement (pipeline) collecte, dédoublonne,
  analyse par IA, géolocalise et stocke les événements ; l'API les sert à un
  frontend cartographique.

---

## 2. Objectif & vision

Donner une **vue cartographique unifiée** de « ce qui se passe » en France :
au lieu de consulter dix sites différents, l'utilisateur voit sur **une seule
carte** les alertes et l'actualité, **là où elles se produisent**, filtrables par
catégorie, gravité et période.

Objectifs de conception :
- **Temps quasi réel** : ingestion plusieurs fois par jour + flux « En direct ».
- **Géolocalisation précise** : placer chaque fait à la bonne commune.
- **Autonomie / robustesse** : fonctionner même quand des sources externes
  tombent (géocodage hors-ligne, isolation des pannes).
- **Souveraineté & sobriété** : sources publiques françaises, hébergement
  auto-géré, pas de dépendance lourde.

---

## 3. Architecture

### 3.1 Composants (Docker Compose)

Six conteneurs, **tous bindés sur `127.0.0.1`** (aucun port web exposé
directement sur Internet) :

| Service | Rôle |
|---|---|
| **db** (PostGIS 16-3.4) | stockage des événements + géométrie `POINT(SRID 4326)` |
| **redis** | cache optionnel des réponses API |
| **backend** (FastAPI) | ingestion, géocodage, API REST + SSE, ordonnanceur |
| **frontend** (Next.js) | carte Leaflet, fil d'actu, brief, statistiques |
| **nginx** | reverse-proxy : `/api/` → backend, tout le reste → frontend |
| **cloudflared** | tunnel Cloudflare — **seul point d'entrée public** |

### 3.2 Flux réseau

```
Internet ──> Cloudflare (TLS, WAF, rate-limit) ──> cloudflared (tunnel)
          └─> nginx ──> /api/  → backend:8000
                     └─> /      → frontend:3000
```

Le frontend appelle l'API en **relatif** (`/api`), donc **same-origin** via nginx :
aucune configuration CORS n'est nécessaire pour l'application elle-même.

---

## 4. Le pipeline de données (de la source à la carte)

C'est le cœur du système. Pour chaque cycle d'ingestion :

```
1. COLLECTE      Les 15 connecteurs interrogent leurs sources EN PARALLÈLE
                 (asyncio.gather), chacun avec un timeout de 120 s. Une source
                 en panne n'affecte pas les autres.

2. SÉLECTION     Presse : chaque flux fournit jusqu'à 25 articles ; on
                 dédoublonne par empreinte de titre, puis on RÉPARTIT le plafond
                 (MAX_PRESSE_ARTICLES) en round-robin ENTRE flux — pour exploiter
                 la diversité des ~877 sources et non laisser un gros publicateur
                 monopoliser.

3. EXTRACTION    Pour chaque article : appel Mistral (repli Ollama local, puis
   IA            règles par mots-clés) → catégorie, gravité (0-3), résumé,
                 lieu_nom, tags. Le texte complet de l'article est récupéré
                 (trafilatura) pour enrichir l'extraction.

4. GÉOCODAGE     lieu_nom → coordonnées, via une cascade HORS-LIGNE d'abord :
                 base locale de ~35 000 communes → départements/régions/DOM-TOM
                 (tables statiques) → repli API BAN externe seulement si besoin.
                 Repli déterministe depuis l'URL (code INSEE / postal /
                 département) quand l'IA renvoie « national ».

5. GARDE-FOUS    Dates futures aberrantes ramenées à maintenant ; fragments
                 génériques (« Seine », « Val »…) rejetés ; vigilances
                 nationales non placées au hasard.

6. STOCKAGE      Upsert PostgreSQL avec clé unique source_url (anti-doublon) +
                 géométrie PostGIS + cluster_id (regroupement des reprises).

7. DIFFUSION     API FastAPI (/api/events, /health, SSE) → Frontend (carte,
                 fil, brief).
```

Un cycle complet prend **~1 à 2 minutes** (ex. 148 événements en ~1 min 40).

---

## 5. Les sources (15 connecteurs)

| Connecteur | Domaine | Accès |
|---|---|---|
| **Météo-France Vigilance** | Météo, canicule, orages… | Open data |
| **Vigicrues** | Crues | API GeoJSON publique |
| **RéNaSS / USGS FDSNWS** | Séismes | API publique |
| **Enedis** | Coupures électriques | Open data |
| **Presse RSS** | Toutes catégories | **~877 flux** (presse nationale + régionale) |
| **SNCF** | Transport ferroviaire | API |
| **Bison Futé** | Trafic routier | RSS |
| **Incendies** | Feux | RSS régionaux |
| **CERT-FR (ANSSI)** | Cybersécurité | RSS |
| **IRSN / ASN** | Nucléaire | RSS |
| **Atmo France (Air Quality)** | Pollution de l'air | API |
| **OpenSky** | Aérien | API |
| **BlueSky** | Réseau social (signaux) | API |
| **Wikinews FR** | Actualité collaborative | API |
| **Santé Publique France** | Santé / alertes sanitaires | RSS |

Le connecteur **Presse RSS** est le plus riche : actu.fr (~114 flux régionaux),
ici.fr, France 3 Régions, Ouest-France, La Dépêche, Sud-Ouest, Le Parisien,
Le Monde, etc. Un outil de diagnostic (`check-feeds`) mesure leur santé
(≈ **95 % vivants**).

---

## 6. Extraction par IA

Chaque article passe par une **extraction en cascade dégradée** (robustesse) :

1. **Mistral AI** (`mistral-small-latest` par défaut) — prioritaire si clé fournie.
2. **Ollama local** (petit modèle) — repli si pas de Mistral.
3. **Règles par mots-clés** — repli ultime, sans IA.

L'IA renvoie 5 champs : **lieu_nom**, **categorie**, **gravité** (0=info,
1=vigilance, 2=alerte, 3=urgence), **résumé** (1-2 phrases), **tags**. La date du
jour (heure de Paris) est fournie au modèle pour situer les faits. Un cache
(SHA-256 du contenu) évite de re-payer l'extraction d'un article déjà vu.

---

## 7. Géolocalisation

Le système de géocodage est le point le plus travaillé — objectif : **placer
chaque événement à la bonne commune, hors-ligne autant que possible**.

### 7.1 Cascade de résolution

Pour un `lieu_nom` :
1. **Filtres** : termes nationaux (« France »), ambigus (« Nord », « Centre »),
   pays/villes étrangères, fragments génériques → renvoyés en « national » (pas
   de pastille au hasard).
2. **Département / région / DOM-TOM par nom ou code** → centroïdes **statiques**
   embarqués (101 départements), aucun réseau.
3. **Base communes locale** : ~**35 000 communes** avec coordonnées GPS, code
   INSEE, population, embarquée dans le backend (`app/data/communes_geo.csv`,
   construite à partir de la liste des communes enrichie par `geo.api.gouv.fr`).
   Résolution instantanée, hors-ligne, insensible aux pannes de l'API BAN.
4. **API BAN externe** (`api-adresse.data.gouv.fr`) — **uniquement en repli**
   pour les noms absents de la base locale.

### 7.2 Localisation depuis l'URL (presse)

Beaucoup d'articles de presse régionale encodent le lieu dans leur URL. Quand
l'IA renvoie « national », un **repli déterministe** lit l'URL :

- **Code INSEE** (actu.fr `…/saint-denis_93066/…`) → **commune exacte** (homonyme
  résolu : Saint-Denis 93, pas la Réunion).
- **Code postal** (Ouest-France `…/rennes-35000/…`) → commune exacte.
- **Commune dans le slug** (Le Parisien `…/essonne-91/morsang-sur-orge-…`) →
  commune, désambiguïsée par le département.
- Sinon **département** du chemin (`…/essonne-91/…`).

Un outil de **backfill** (`python -m app.maintenance backfill-locations`)
re-localise a posteriori les articles déjà stockés, sans appel IA.

### 7.3 Homonymes & précision

La base est indexée par nom, par code INSEE et par code postal. La
désambiguïsation se fait par le département (issu de l'URL) ou, à défaut, par la
commune la plus peuplée.

---

## 8. Taxonomie des catégories

**16 catégories** (source unique de vérité : `backend/app/categories.py`,
consommée par la validation API, les prompts IA et le classement par règles ;
miroir côté frontend pour la couleur/icône) :

`meteo`, `crue`, `seisme`, `energie`, `sante`, `transport`, `ordre_public`,
`actualite`, `incendie`, `nucleaire`, `pollution`, `cyber`, `sport`, `economie`,
`politique`, `culture`.

Chaque catégorie a une **couleur**, une **icône** et une **lettre** côté carte.
La **gravité** (0-3) module l'affichage (halo coloré, badge « Urgence »…).

---

## 9. Ordonnancement (APScheduler)

Tâches planifiées (fuseau **Europe/Paris**), avec **marge « misfire » d'1 h +
coalesce** (un job légèrement en retard s'exécute quand même au lieu d'être
silencieusement sauté) :

| Tâche | Horaires |
|---|---|
| **Ingestion** | 07h00, 12h00, 19h00 (+ au démarrage) |
| **Brief quotidien** (Mistral, 3 volets : Alertes, Actualité, En régions) | 09h00, 13h00, 20h00 |
| **Purge** (TTL par source : 36h météo, 72h presse, 30j séismes…) | 03h00 |

---

## 10. API (FastAPI)

Endpoints publics (préfixe `/api`) :

| Endpoint | Description |
|---|---|
| `GET /events` | Liste filtrée (bbox, catégories, gravité, période, dept, recherche texte…) |
| `GET /events/{id}` | Détail d'un événement |
| `GET /events/stream` | **SSE** « En direct » (push des nouveaux événements toutes les 30 s) |
| `GET /events/timeline` | Histogramme temporel |
| `GET /stats`, `GET /stats/geo` | Statistiques globales / géographiques |
| `GET /trends` | Tendances par catégorie |
| `GET /brief`, `POST /brief/run` | Brief du jour / régénération à la demande |
| `POST /ingest/run` | Déclenche une ingestion (+ brief), protégé par clé |
| `GET /feed.rss` | Flux Atom/RSS filtrable |
| `GET /health` | Santé des connecteurs + prochaine ingestion |

L'API est **en lecture seule** ; les deux endpoints mutants (`/ingest/run`,
`/brief/run`) exigent une **clé `X-Api-Key`** (comparaison en temps constant),
et sont **fail-closed en production** si la clé n'est pas configurée. La doc
Swagger/ReDoc est **désactivée** par défaut.

---

## 11. Frontend (Next.js 14 + Leaflet)

- **Carte de France** : marqueurs par catégorie, **clustering** (regroupement
  au dézoom), couche de risque par département, heatmap, panneau DOM-TOM,
  recherche de ville. Les contours départementaux viennent d'un fond GeoJSON.
- **Fil d'actualités** (colonne droite) : articles filtrables, onglets Carte /
  National, timeline, mini-statistiques.
- **Brief du jour** : encart dépliable, avec heure de génération.
- **Temps réel** : polling SWR (toutes les 5 min) **+ flux SSE** « En direct ».
- **Barre de statut** : pastilles vert/orange/rouge par connecteur, prochaine
  MàJ, bouton d'ingestion manuelle.
- **Divers** : mode sombre, export CSV, partage d'URL avec filtres, alertes
  navigateur, page `/stats`.

---

## 12. Base de données (modèle)

Trois tables principales :

- **events** : `id`, `source`, `source_url` (unique), `titre`, `auteur`,
  `date_publication`, `date_evenement`, `categorie`, `gravite`, `lieu_nom`,
  `lieu_code_insee`, `lieu_lat/lon`, `lieu_niveau` (commune/departement/region/
  national), `geom` (PostGIS `POINT`, index GiST), `resume_ia`, `tags`,
  `cluster_id`, `score_confiance`, `created_at`. Index sur date, source+gravité,
  gravité+date.
- **connector_status** : santé de chaque connecteur (`last_run`, `last_error`,
  `last_success`, `consecutive_failures`).
- **daily_briefs** : brief par jour (date, contenu, nb d'événements, généré_le).

---

## 13. Fiabilité & tolérance aux pannes

| Mécanisme | Effet |
|---|---|
| **Isolation des connecteurs** | `gather(return_exceptions=True)` + timeout 120 s/connecteur → une source morte n'arrête pas les autres |
| **Géocodage hors-ligne** | 35 k communes + 101 centroïdes embarqués → localisation sans réseau |
| **Extraction en cascade** | Mistral → Ollama → règles → jamais totalement bloqué |
| **Verrou d'ingestion** | empêche deux cycles simultanés (pas d'empilement CPU) |
| **Anti-doublon** | clé `source_url` + empreinte de titre (`cluster_id`) |
| **Garde-fous données** | dates futures bornées, fragments/homonymes filtrés |
| **Santé + webhook** | pastilles d'état + alerte configurable (≥ 3 échecs) |
| **Scheduler robuste** | marge misfire 1 h + coalesce → plus de jobs cron sautés |
| **Auto-restart** | `restart: unless-stopped` + healthchecks Docker |
| **CI** | 161 tests + build à chaque PR → plus de régression silencieuse |

**Points de fragilité résiduels** (assumés) :
- Le **fond de carte** (tuiles OpenStreetMap) vient d'un CDN externe : s'il
  bloque, le fond disparaît (les données/marqueurs restent).
- **Dépendance Mistral** : sans clé/quota, résumés et catégorisation fine
  dégradés (repli règles) et brief figé.
- **Mono-worker** : pas de scaling horizontal en l'état.
- **Migrations à la main** (`init_db` + `ALTER … IF NOT EXISTS`, pas d'Alembic).

---

## 14. Sécurité

- **Aucun port exposé** : tout en `127.0.0.1`, accès public uniquement via
  **Cloudflare Tunnel**.
- **Mot de passe DB** : en production, refus de démarrer avec un mot de passe
  faible/par défaut (`password`, `postgres`, `admin`…) ; `docker-compose` exige
  `POSTGRES_PASSWORD` (fail-closed).
- **CORS** : `*` **neutralisé en production** (le front étant same-origin, rien
  n'est cassé ; les XHR tierces sont bloquées). Overridable via `CORS_ORIGINS`.
- **Endpoints mutants** protégés par clé en **temps constant**, fail-closed en
  prod.
- **Doc API désactivée** (`ENABLE_DOCS=false`).
- **En-têtes nginx** : `X-Frame-Options`, `X-Content-Type-Options`,
  `Referrer-Policy`, HSTS.
- **Durcissement serveur** (`security/harden-server.sh`) : UFW, fail2ban SSH,
  `PermitRootLogin prohibit-password`, MAJ automatiques.
- **Anti-SSRF** dans le fetch d'articles (réseaux privés/loopback bloqués).

---

## 15. Exploitation (Ops)

### 15.1 Déploiement

```bash
cd /opt/aifaire
git pull origin main
docker compose build backend && docker compose up -d --no-deps backend   # backend
# (frontend si des fichiers frontend ont changé)
```

Pré-requis : `POSTGRES_PASSWORD` (fort) dans `.env`, ainsi que les clés
optionnelles (`MISTRAL_API_KEY`, `INGEST_API_KEY`, `CLOUDFLARE_TUNNEL_TOKEN`…).

### 15.2 Intégration continue

`.github/workflows/ci.yml` : à chaque push/PR, **tests backend** (pytest,
hors-ligne) + **typecheck/build frontend**. Le `main` n'est mis à jour que via
PR verte.

### 15.3 Sauvegardes chiffrées & vérifiées

- `security/backup-postgres.sh` : `pg_dump` → gzip → **chiffrement AES-256**,
  avec **vérification d'intégrité avant publication atomique** (jamais de backup
  corrompu) + rétention. Planifié à **02h30**.
- `security/backup-verify.sh` : contrôle quotidien (**08h00**) que le dernier
  backup est récent + déchiffrable + valide ; **alerte webhook** sinon.
- Restauration testée (dump → restore réel). Passphrase à conserver **hors du
  serveur**.

### 15.4 Outils de maintenance

```bash
docker compose exec backend python -m app.maintenance backfill-locations   # re-localise l'existant
docker compose exec backend python -m app.maintenance check-feeds          # santé des 877 flux
```

---

## 16. Configuration (variables d'environnement)

| Variable | Défaut | Rôle |
|---|---|---|
| `DATABASE_URL` | — | URL PostgreSQL async (mot de passe fort requis en prod) |
| `POSTGRES_PASSWORD` | — (obligatoire) | mot de passe DB |
| `APP_ENV` | `development` | `production` active les garde-fous |
| `MISTRAL_API_KEY` / `MISTRAL_MODEL` | vide / `mistral-small-latest` | extraction & briefs |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | vide | repli IA local |
| `INGEST_API_KEY` | vide | protège `/ingest/run` & `/brief/run` |
| `CORS_ORIGINS` | `*` (neutralisé en prod) | origines autorisées |
| `ENABLE_DOCS` | `false` | Swagger/ReDoc |
| `MAX_PRESSE_ARTICLES` | `120` | plafond presse par cycle |
| `FETCH_FULL_ARTICLES` | `true` | fetch du texte complet |
| `CONNECTOR_FETCH_TIMEOUT_SECONDS` | `120` | timeout par connecteur |
| `REDIS_URL` / `REDIS_EVENTS_TTL` | vide / `120` | cache API |
| `WEBHOOK_URL` / `WEBHOOK_THRESHOLD` | vide / `3` | alertes connecteurs |
| `SCHEDULER_TIMEZONE` | `Europe/Paris` | fuseau des tâches |

---

## 17. Structure du dépôt

```
backend/
├── app/
│   ├── main.py            # app FastAPI, cycle de vie, CORS
│   ├── config.py          # configuration + garde-fous prod
│   ├── categories.py      # taxonomie (source unique)
│   ├── communes_db.py     # base communes locale (géocodage offline)
│   ├── maintenance.py     # backfill-locations, check-feeds
│   ├── models.py          # ORM (Event, ConnectorStatus, DailyBrief)
│   ├── data/communes_geo.csv   # 35k communes + coordonnées (embarqué)
│   ├── connectors/        # 15 connecteurs de sources
│   ├── pipeline/          # extractor, geocoder, ingestor, brief, scheduler…
│   └── api/routes/        # events.py, health.py
├── scripts/               # build de la base communes (dev)
└── tests/                 # 161 tests (hors-ligne)
frontend/                  # Next.js 14 + Leaflet
nginx/ · cloudflared/ · security/ · .github/workflows/ci.yml
docker-compose.yml
```

---

## 18. Améliorations récentes (session de juin-juillet 2026)

- 🗺️ **Géolocalisation commune précise** depuis l'URL (INSEE/CP/département,
  homonymes résolus) + base 35 k communes hors-ligne + backfill de l'existant.
- 📡 **Diversité des sources** : sélection round-robin (fin de la domination d'un
  seul média).
- 🏷️ Ajout des catégories **sport / économie / politique / culture** + source
  unique de taxonomie.
- 📰 **Brief** : moins répétitif (vigilances regroupées), daté, régénéré après
  ingestion ; endpoint `/brief/run`.
- 🔴 **Flux SSE « En direct »** réparé ; dates futures bornées ; faux pins sport
  corrigés.
- 🔒 **Sécurité** : mot de passe DB fort + garde-fou, CORS fail-closed, clé
  d'ingest en temps constant.
- 💾 **Backups** chiffrés, **intégrité vérifiée**, monitorés (alerte si stale).
- ⏰ **Scheduler** fiabilisé (plus de jobs cron sautés).
- ✅ **CI** GitHub Actions (161 tests + build) sur chaque PR.

---

## 19. Pistes futures

- **Auto-skip** des flux RSS morts (circuit-breaker par flux, auto-maintenu).
- **Alembic** pour des migrations de schéma versionnées et sûres.
- **Fond de carte offline** (tuiles + contours servis localement) pour supprimer
  la dernière dépendance CDN.
- **Réplication / copie hors-site** des sauvegardes.
- **Scaling** (workers multiples + diffusion SSE partagée) si le trafic grandit.

---

*Document généré automatiquement à partir de l'analyse du code source.
FAIRE Info — API v1.0.0.*
