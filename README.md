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
| Enedis | Énergie | Open data |
| 870+ flux RSS (presse, officiel, thématique) | Toutes | RSS |

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

Ingestions automatiques : **7h00, 12h00, 19h00** (heure Paris).  
Purge quotidienne : **3h00** — TTL variable par source : 36h météo/vigicrues, 48h Enedis, 72h presse, 30j séismes.

Pour déclencher manuellement : `POST /api/ingest/run` (clé `INGEST_API_KEY`) ou bouton "Ingérer" dans la StatusBar.

### Robustesse & qualité

- **Requêtes HTTP conditionnelles** : les flux RSS utilisent ETag / Last-Modified (`If-None-Match` / `If-Modified-Since`). Un flux inchangé répond `304` : bande passante économisée et risque de `429` réduit.
- **Déduplication des dépêches** : empreinte de titre déterministe (mots significatifs, insensible accents/casse) — les reprises d'une même dépêche sont regroupées sous un `cluster_id`. L'interface n'affiche le fait qu'une fois avec « +N sources ».
- **Plafond presse** : `MAX_PRESSE_ARTICLES` (défaut 120) — cap appliqué après dédup pour éviter de saturer le LLM sur un cycle.
- **Santé des connecteurs** : chaque run met à jour `last_success` et un compteur d'échecs consécutifs. Un raté isolé → « dégradé » (orange) ; panne chronique (≥ 3 runs) → « erreur » (rouge). Visible dans la StatusBar. Webhook configurable (`WEBHOOK_URL`).
- **Géocodage départemental hors-ligne** : les centroïdes des 101 départements sont une table statique (`geo_data.DEPT_CENTROIDS`), pas un appel réseau. `geo.api.gouv.fr` ayant cessé de renvoyer le champ `centre`, les vigilances Météo-France (par département) retombaient toutes en « national » et n'apparaissaient pas sur la carte ; la table locale rend cette donnée constante déterministe et instantanée.

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
| `CORS_ORIGINS` | `*` | Origines CORS autorisées (séparées par virgule) |

## Production (Docker Compose)

```bash
MISTRAL_API_KEY=... \
INGEST_API_KEY=... \
NEXT_PUBLIC_API_BASE_URL=https://api.faire.info/api \
docker compose up -d
```

## Architecture des composants backend

```
app/
├── connectors/      # Collecteurs de données (1 fichier = 1 source)
│   ├── base.py      # Classe abstraite BaseConnector
│   ├── meteo_france.py
│   ├── vigicrues.py
│   ├── renass.py    # USGS FDSNWS
│   ├── enedis.py
│   └── presse_rss.py  # 870+ flux RSS avec dédup et ETag
├── pipeline/
│   ├── extractor.py # Mistral AI + fallback Ollama + fallback règles (cache SHA256)
│   ├── geocoder.py  # BAN (communes) + centroïdes départementaux statiques + tables régions/DOM-TOM (cache 1024)
│   ├── ingestor.py  # Orchestrateur — fetch → extract → geocode → upsert
│   ├── brief.py     # Génération brief quotidien (Mistral)
│   ├── purge.py     # TTL par source (36h–30j)
│   └── scheduler.py # APScheduler — ingestions 7h/12h/19h, briefs 9h/13h/20h, purge 3h
├── api/routes/
│   ├── events.py    # GET /events, GET /events/{id}, POST /ingest/run
│   └── health.py    # GET /health (statut connecteurs + prochain run)
└── models.py        # ORM SQLAlchemy (Event + ConnectorStatus)
```
