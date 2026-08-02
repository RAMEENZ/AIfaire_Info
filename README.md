# Faire.info — Agrégateur d'information géolocalisé (France)

Vue cartographique unifiée de l'actualité publique française en quasi temps réel.

## Stack

- **Backend** : Python 3.13 + FastAPI + GeoAlchemy2 + APScheduler
- **Frontend** : Next.js 14 + Leaflet + Tailwind CSS
- **BDD** : PostgreSQL 16 + PostGIS 3.4
- **IA** : Mistral AI (extraction lieu + catégorie + teaser + briefs) — Ollama en fallback local
- **Géocodage** : BAN (api-adresse.data.gouv.fr) pour les communes + tables locales pour départements (101 centroïdes statiques), régions et DOM-TOM

## Sources

| Source | Catégorie | Accès |
|---|---|---|
| Météo-France Vigilance | Météo, Crue | Open data |
| Vigicrues | Crue | API publique GeoJSON |
| USGS FDSNWS (RéNaSS) | Séisme | API publique |
| 870+ flux RSS (presse, officiel, thématique) | Toutes | RSS |

_Enedis (coupures d'électricité) a été retiré en 07/2026 : le portail open data a migré et le dataset temps réel a disparu._

### Flux RSS inclus

**Presse nationale** — France Info, France 24, France Inter, RFI, Le Monde, Le Figaro, Libération, CNews, Euronews…

**Presse régionale** — Ouest-France, La Voix du Nord, Sud-Ouest, DNA, Le Progrès, La Dépêche, Nice-Matin, L'Est Républicain, L'Indépendant, Le Télégramme, Paris-Normandie, Le Berry Républicain, L'Yonne Républicaine, et des centaines de titres locaux via actu.fr (13 régions) et MaVille.

**Radio publique** — 43 stations France Bleu, 10 antennes La 1ère (DOM-TOM).

**Sources officielles** — Santé Publique France, ANSM, Service-Public.fr, Sénat, Vie Publique.

**Thématiques** (F1, Gaming, Tech, Streaming, YouTube, Automobile, Art & Design, IT, Hardware, Overclocking, Info Positive).

## Pipeline

```
[Sources] → [Connectors] → [Extractor IA / règles] → [Geocoder BAN] → [Dédup] → [PostgreSQL+PostGIS] → [API FastAPI] → [Next.js + Leaflet]
```

Ingestions automatiques : **7h00, 12h00, 19h00** (heure Paris), plus un **passage horaire léger** (à :30) des sources d'alerte temps réel — météo, crues, séismes — sans coût LLM (`HOURLY_ALERT_INGESTION`).  
Purge quotidienne : **3h00** — TTL variable par source : 36h météo/vigicrues, 72h presse, 30j séismes. Juste avant la purge, les comptes quotidiens (jour × catégorie × département) sont figés dans `daily_stats` (exposés par `GET /api/stats/history`) : les tendances longues survivent à la purge.

Pour déclencher manuellement : `POST /api/ingest/run` (clé `INGEST_API_KEY`). Le bouton "Ingérer" de la StatusBar est réservé au dev/local (l'endpoint étant protégé par clé en production) : il est masqué par défaut et s'active via `NEXT_PUBLIC_ENABLE_INGEST_BUTTON=true`.

### Robustesse & qualité

- **Requêtes HTTP conditionnelles** : les flux RSS utilisent ETag / Last-Modified (`If-None-Match` / `If-Modified-Since`). Un flux inchangé répond `304` : bande passante économisée et risque de `429` réduit.
- **Déduplication des dépêches** : empreinte de titre déterministe (mots significatifs, insensible accents/casse) — les reprises d'une même dépêche sont regroupées sous un `cluster_id`. L'interface n'affiche le fait qu'une fois avec « +N sources ».
- **Plafond presse** : `MAX_PRESSE_ARTICLES` (défaut 120) — cap appliqué après dédup pour éviter de saturer le LLM sur un cycle.
- **Santé des connecteurs** : chaque run met à jour `last_success` et un compteur d'échecs consécutifs. Un raté isolé → « dégradé » (orange) ; panne chronique (≥ 3 runs) → « erreur » (rouge). Visible dans la StatusBar. Webhook configurable (`WEBHOOK_URL`).
- **Géocodage départemental hors-ligne** : les centroïdes des 101 départements sont une table statique (`geo_data.DEPT_CENTROIDS`), pas un appel réseau. `geo.api.gouv.fr` ayant cessé de renvoyer le champ `centre`, les vigilances Météo-France (par département) retombaient toutes en « national » et n'apparaissaient pas sur la carte ; la table locale rend cette donnée constante déterministe et instantanée.
- **Healthcheck de fraîcheur** : `GET /healthz` répond `503` si le scheduler ne planifie plus d'ingestion (ou la déclenche avec plus d'1 h de retard), ou si aucun événement n'a été ingéré depuis 26 h (`HEALTHZ_*`, grâce de 30 min au démarrage). Le healthcheck Docker pointe dessus, et le service `autoheal` redémarre automatiquement un backend « unhealthy ». Leçon de la panne de 07/2026 : un scheduler mort dans un processus vivant restait invisible avec un healthcheck qui ne testait que « l'API répond ».
- **Alerte de staleness** : contrôle horaire de fraîcheur (`app/pipeline/freshness.py`) — si aucun événement n'est ingéré depuis 26 h, notification `WEBHOOK_URL` (anti-spam : une alerte par 12 h, réarmée dès le retour à la normale). Complète autoheal : si le redémarrage ne guérit pas, vous êtes prévenu au lieu d'une boucle silencieuse.
- **Logs persistants** : en plus de stdout, le backend écrit dans `LOG_DIR` (monté sur `./logs`, rotation 5 × 10 Mo). Les logs Docker `json-file` meurent avec le conteneur — l'autopsie de la panne de 07/2026 a été impossible pour cette raison.
- **Limite de concurrence par hôte** : au plus 3 requêtes simultanées vers un même domaine lors de la collecte RSS — une rafale de 12 flux d'un même éditeur (Le Télégramme…) déclenchait des 403 anti-bot.
- **Rapport de santé des flux** : `GET /api/health/feeds` liste les flux RSS en échec (compteur, dernière erreur, mis de côté ou non) — le tri des flux morts devient une lecture de quelques minutes. Complémentaire du sondage complet `python -m app.maintenance check-feeds`.
- **Métrique de localisation** : `/api/metrics` expose `localized_pct_24h` (% d'événements géolocalisés sur 24 h) — une chute brutale signale une régression silencieuse du géocodeur ou de l'extraction LLM.
- **Charge utile bornée** : `/events` est paginé (`offset`, `has_more`) et tronque les résumés IA à 220 caractères (`?full=true` pour le texte intégral). La réponse par défaut est passée de 451 Ko à environ un tiers ; le fil charge 200 événements puis la suite à la demande.
- **Reconnaissance de commune dans les titres** : `communes_db.commune_from_text` couvre les 35 000 communes de la table locale (contre ~70 grandes villes auparavant), avec trois garde-fous contre les homonymes — population ≥ 3 000, nom propre (majuscule), liste noire de noms ambigus (« Bar », « Le Port »…). Un faux marqueur trompant plus qu'une absence de marqueur, la détection s'abstient au moindre doute.
- **Jeu d'évaluation hors-ligne** : `tests/test_extraction_eval.py` rejoue un corpus annoté (catégorisation, détection de commune) sans réseau ni LLM, avec des seuils de non-régression. Permet de retoucher mots-clés, prompt ou modèle sans régresser à l'aveugle.
- **Mode hors ligne** : service worker à priorité réseau (`frontend/public/sw.js`) — cache uniquement en repli, version épinglée et purgée à l'activation, HTML jamais servi depuis le cache tant que le réseau répond. Bandeau « Hors ligne » dans l'interface.
- **Sauvegardes chiffrées + hors-site** : `security/backup-postgres.sh` (dump vérifié avant publication, rétention, copie rclone optionnelle vers un stockage objet) et exercice de restauration documenté dans `security/README.md`.

### Notifications Web Push (optionnel)

Désactivées tant qu'aucune clé VAPID n'est configurée : les endpoints
répondent alors `enabled: false` et l'interface masque le bouton. Pour les
activer :

```bash
docker compose exec backend python -m app.maintenance vapid-keys
# → reporter VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY / VAPID_CONTACT_EMAIL
#   dans le .env du serveur, puis :
docker compose up -d backend
docker compose exec backend alembic upgrade head   # table push_subscriptions
```

Fonctionnement : après chaque ingestion, les événements **nouvellement
insérés** de gravité ≥ 2 déclenchent une notification vers les abonnés dont le
département et le seuil correspondent. Trois garde-fous : au plus 3
notifications par cycle (une vigilance nationale produit des dizaines
d'événements graves d'un coup), rien au-delà de 6 h d'ancienneté (pas de
réveil pour du rattrapage après panne), et regroupement par `cluster_id` (une
reprise de la même dépêche remplace la notification au lieu de s'empiler).
Les abonnements révoqués (404/410) sont purgés automatiquement.

Changer de paire de clés invalide tous les abonnements existants. La clé
privée ne doit jamais être commitée.

### Interface

- **Page Tendances** (`/tendances`) : historique quotidien tiré de `daily_stats` — événements par jour empilés par catégorie, cumuls par catégorie et top des départements, sur 30 j / 90 j / 1 an.
- **Département épinglé** : un clic sur un département (carte) filtre le fil (événements du département + nationaux) ; l'épingle 📌 le mémorise entre les visites.
- **Archive des briefs** : les briefs précédents (14 derniers) sont consultables depuis le panneau Brief (`GET /api/brief/history`).

### Supervision externe (recommandé)

Tout ce qui tourne sur le serveur meurt avec lui : ajoutez un moniteur externe
gratuit (UptimeRobot, healthchecks.io…) qui interroge `https://<votre-domaine>/api/metrics`
toutes les 5 minutes et alerte si la réponse est en erreur — ou, mieux, si
`events_last_24h` tombe à 0 (healthchecks.io accepte un simple ping planifié
depuis le serveur : `curl -fsS https://hc-ping.com/<uuid>` en cron après chaque
ingestion réussie).

### Brief quotidien

Généré à **9h00, 13h00 et 20h00** (heure Paris) par Mistral, en trois volets distincts : **Alertes & vigilances**, **Actualité générale** et **En régions** (faits ancrés dans différents territoires).

## Sécurité

Architecture : tout le trafic entre via Cloudflare Tunnel — aucun port web exposé directement.

- Ports Docker bindés sur `127.0.0.1` (pas d'accès direct IP:port depuis Internet)
- Doc API fermée par défaut (`ENABLE_DOCS=false`)
- Headers de sécurité nginx (`X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, HSTS)
- Résolution DNS Docker dynamique (`resolver 127.0.0.11 valid=30s`) — évite les 502 après restart

Voir [`security/README.md`](security/README.md) pour les scripts de durcissement, backups chiffrés et config Cloudflare WAF.

## Démarrage local

### Prérequis
- Docker + Docker Compose
- Python 3.13+
- Node.js 20+

### Base de données (PostgreSQL + PostGIS)

```bash
docker compose -f docker-compose.dev.yml up -d
```

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # puis éditer .env

# Créer les tables
python -c "import asyncio; from app.database import init_db; asyncio.run(init_db())"

# Lancer
uvicorn app.main:app --reload --port 8000
```

### Migrations de schéma (Alembic)

Le démarrage crée/complète toujours le schéma automatiquement (`init_db` +
`migrate_db`, idempotents) — rien ne change pour l'existant. Alembic est la
voie **pour les évolutions futures** :

```bash
cd backend
alembic stamp head          # une seule fois sur une base EXISTANTE (marque la baseline)
alembic upgrade head        # applique les migrations (crée tout sur une base neuve)
alembic revision -m "..."   # nouvelle migration (opérations op.* explicites)
```

En production : `docker compose exec backend alembic upgrade head`.

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Interface disponible sur http://localhost:3000  
API + Swagger : http://localhost:8000/docs _(nécessite `ENABLE_DOCS=true` dans `.env`)_

### Tests (backend)

Suite de tests unitaires hors-ligne (pas de base de données ni de réseau requis) :

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

Couvre le géocodeur (termes nationaux, articles, alias, régions, DOM-TOM),
l'extracteur (catégorisation/gravité par règles, overrides de source) et
le calcul de statut des connecteurs.

**Tests d'intégration** (vraie base PostgreSQL/PostGIS) — ignorés
automatiquement si `TEST_DATABASE_URL` n'est pas défini ; la CI fournit un
service PostGIS. Ils vérifient le SQL réellement émis : pagination, troncature
des résumés, recherche, filtre spatial bbox, endpoint carte, brief local,
upsert d'abonnement push.

```bash
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/faire_test \
  pytest tests/test_integration_api.py
```

**Jeu d'évaluation** (`tests/test_extraction_eval.py`) : corpus annoté rejoué
sans réseau ni LLM, avec seuils de non-régression — permet de retoucher
mots-clés, prompt ou modèle sans régresser à l'aveugle.

### Tests (frontend)

Tests unitaires des fonctions pures (Vitest, environnement jsdom) :

```bash
cd frontend
npm test
```

Couvre la déduction du département depuis le code INSEE (métropole/Corse/DOM/COM),
la logique d'alertes navigateur (`shouldAlert`, persistance localStorage) et la
cohérence des tables de configuration (labels de connecteurs, catégories).

**Tests de bout en bout** (Playwright, API simulée — ni backend ni base) :

```bash
cd frontend
npm run build && npm run test:e2e
# Environnement fournissant déjà un Chromium : CHROMIUM_PATH=/chemin/vers/chromium npm run test:e2e
```

Couvre les régressions d'interface qu'aucun test unitaire ne voit — hauteur
utile du fil et défilement effectif sur mobile, panneau de brief défilable,
accès aux pages secondaires sur petit écran, pagination et recherche serveur —
ainsi qu'un audit d'accessibilité automatisé (axe-core, WCAG 2 A/AA).

### Variables d'environnement backend

| Variable | Défaut | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` | URL PostgreSQL async |
| `APP_ENV` | `development` | `production` active les garde-fous (refuse le mot de passe DB par défaut) |
| `MISTRAL_API_KEY` | _(vide)_ | Clé Mistral AI — extraction + briefs |
| `MISTRAL_MODEL` | `mistral-small-latest` | Modèle Mistral utilisé |
| `OLLAMA_BASE_URL` | _(vide)_ | Fallback local si `MISTRAL_API_KEY` absent |
| `OLLAMA_MODEL` | `qwen2.5:1.5b` | Modèle Ollama |
| `METEO_FRANCE_API_KEY` | _(vide)_ | Clé API Météo-France Vigilance |
| `INGEST_API_KEY` | _(vide)_ | Clé POST `/api/ingest/run` (vide = pas d'auth, dev uniquement) |
| `ENABLE_DOCS` | `false` | Swagger `/docs` — mettre `true` en local pour explorer l'API |
| `SCHEDULER_TIMEZONE` | `Europe/Paris` | Timezone APScheduler |
| `DEFAULT_SINCE_HOURS` | `48` | Fenêtre d'affichage par défaut |
| `MAX_PRESSE_ARTICLES` | `120` | Plafond articles presse traités par cycle (chacun passe par le LLM) |
| `FETCH_FULL_ARTICLES` | `true` | Fetch du contenu complet avant extraction IA (désactiver si bande passante limitée) |
| `CONNECTOR_FETCH_TIMEOUT_SECONDS` | `120` | Timeout fetch par connecteur — au-delà, le connecteur est abandonné sans bloquer les autres |
| `WEBHOOK_URL` | _(vide)_ | URL webhook alertes connecteurs (Discord, Slack, ntfy…) |
| `WEBHOOK_THRESHOLD` | `3` | Nb d'échecs consécutifs déclenchant le webhook |
| `REDIS_URL` | _(vide)_ | Cache Redis optionnel (`redis://redis:6379` en prod) |
| `REDIS_EVENTS_TTL` | `120` | TTL cache API événements (secondes) |
| `MAX_SSE_CONNECTIONS` | `100` | Plafond de flux SSE `/events/stream` simultanés (au-delà : 503, repli polling) |
| `FEED_FAILURE_THRESHOLD` | `3` | Échecs consécutifs avant mise à l'écart d'un flux RSS (circuit-breaker) |
| `HEALTHZ_MAX_DATA_AGE_HOURS` | `26` | `/healthz` passe unhealthy si aucun événement ingéré depuis ce délai |
| `HEALTHZ_SCHEDULER_GRACE_MINUTES` | `60` | Retard toléré sur la prochaine ingestion planifiée avant unhealthy |
| `HEALTHZ_BOOT_GRACE_MINUTES` | `30` | Fenêtre post-démarrage sans exigence de fraîcheur (ingestion initiale en cours) |
| `HOURLY_ALERT_INGESTION` | `true` | Passage horaire des sources d'alerte (météo, crues, séismes) sans coût LLM |
| `LOG_DIR` | _(vide)_ | Répertoire de logs persistants (rotation 5×10 Mo) ; `/app/logs` en prod |
| `FEED_SKIP_RUNS` | `8` | Nb de cycles d'ingestion pendant lesquels un flux mort est sauté avant re-test |
| `CORS_ORIGINS` | `*` | Origines CORS autorisées (séparées par virgule) |
| `GIT_SHA` | _(vide)_ | Commit déployé, exposé par `GET /` (diagnostic « quelle version tourne ? ») |

## Production (Docker Compose)

```bash
MISTRAL_API_KEY=... \
INGEST_API_KEY=... \
NEXT_PUBLIC_API_BASE_URL=https://api.faire.info/api \
docker compose up -d
```

### Redéploiement (`deploy.sh`)

Pour mettre à jour un serveur existant, le script `deploy.sh` enchaîne
`pull → build → recreate` et **refuse de valider** si `APP_ENV` n'est pas
`production` (avant *et* après recréation) ou si un conteneur ne devient pas
`healthy` — de quoi éviter un `.env` resté en `development`. Il exporte aussi
`GIT_SHA` pour que `GET /` reflète le commit déployé.

```bash
cd /opt/aifaire
./deploy.sh                 # pull + build/recreate backend & frontend
./deploy.sh backend         # ne (re)construit que le backend
SKIP_PULL=1 ./deploy.sh     # déploie l'état local sans git pull
ALLOW_DEV=1  ./deploy.sh    # autorise un déploiement hors production (dev)
```

## Architecture des composants backend

```
app/
├── connectors/      # Collecteurs de données (1 fichier = 1 source)
│   ├── base.py      # Classe abstraite BaseConnector
│   ├── meteo_france.py
│   ├── vigicrues.py
│   ├── renass.py    # USGS FDSNWS
│   └── presse_rss.py  # 870+ flux RSS avec dédup, ETag et limite par hôte
├── pipeline/
│   ├── extractor.py # Mistral AI + fallback Ollama + fallback règles (cache SHA256)
│   ├── geocoder.py  # BAN (communes) + centroïdes départementaux statiques + tables régions/DOM-TOM (cache 1024)
│   ├── ingestor.py  # Orchestrateur — fetch → extract → geocode → upsert
│   ├── brief.py     # Génération brief quotidien (Mistral)
│   ├── freshness.py # Alerte webhook si plus rien n'est ingéré (staleness)
│   ├── stats.py     # Agrégats quotidiens daily_stats (avant purge)
│   ├── purge.py     # TTL par source (36h–30j)
│   └── scheduler.py # APScheduler — ingestions 7h/12h/19h + alertes horaires, briefs 9h/13h/20h, purge 3h
├── api/routes/
│   ├── events.py    # GET /events, GET /events/{id}, POST /ingest/run
│   └── health.py    # GET /health (statut connecteurs + prochain run)
└── models.py        # ORM SQLAlchemy (Event + ConnectorStatus)
```
