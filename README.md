# (AI)Faire.info — Agrégateur d'information géolocalisé (France)

Vue cartographique unifiée de l'actualité publique française en quasi temps réel.

## Stack

- **Backend** : Python 3.13 + FastAPI + GeoAlchemy2 + APScheduler
- **Frontend** : Next.js 14 + Leaflet + Tailwind CSS
- **BDD** : PostgreSQL 16 + PostGIS 3.4
- **IA** : Claude Haiku (`claude-haiku-4-5-20251001`) — extraction lieu + catégorie + teaser
- **Géocodage** : BAN (api-adresse.data.gouv.fr) + geo.api.gouv.fr + tables locales

## Sources

| Source | Catégorie | Accès |
|---|---|---|
| Météo-France Vigilance | Météo, Crue | Open data |
| Vigicrues | Crue | API publique GeoJSON |
| USGS FDSNWS (RéNaSS) | Séisme | API publique |
| Enedis | Énergie | Open data |
| 114 flux RSS (presse, officiel) | Toutes | RSS |

### Flux RSS inclus
Presse nationale (France Info, Le Monde, BFM, RTL…), grandes régions (Actu.fr × 13 régions),
quotidiens régionaux (Ouest-France, La Voix du Nord, Sud-Ouest, DNA, Le Progrès…),
43 stations France Bleu, 10 La 1ère DOM-TOM, sources officielles
(Gouvernement.fr, Santé Publique France, ANSM, Ministère de l'Intérieur, Service-Public.fr, Sénat).

## Pipeline

```
[Sources] → [Connectors] → [Extractor IA / règles] → [Geocoder BAN] → [PostgreSQL+PostGIS] → [API FastAPI] → [Next.js + Leaflet]
```

Ingestions automatiques : **9h00, 13h00, 19h00, 23h00** (heure Paris).  
Purge quotidienne : **3h00** (TTL variable par source : 36h alertes, 72h presse, 30j séismes).

Pour déclencher manuellement : `POST /api/ingest/run` ou bouton "Ingérer" dans la StatusBar.

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
cp .env.example .env  # puis éditer .env (ANTHROPIC_API_KEY, DATABASE_URL)

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
API + Swagger : http://localhost:8000/docs

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
| `DATABASE_URL` | postgresql+asyncpg://... | URL PostgreSQL async |
| `ANTHROPIC_API_KEY` | _(vide)_ | Clé Claude Haiku (fallback règles si absent) |
| `SCHEDULER_TIMEZONE` | Europe/Paris | Timezone APScheduler |
| `DEFAULT_SINCE_HOURS` | 48 | Fenêtre d'affichage par défaut |

## Production (Docker Compose)

```bash
ANTHROPIC_API_KEY=sk-ant-... \
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
│   └── presse_rss.py
├── pipeline/
│   ├── extractor.py # Claude Haiku + fallback règles (cache SHA256)
│   ├── geocoder.py  # BAN + geo.api.gouv.fr + tables locales (cache 1024)
│   ├── ingestor.py  # Orchestrateur — fetch → extract → geocode → upsert
│   ├── purge.py     # TTL par source
│   └── scheduler.py # APScheduler cron jobs
├── api/routes/
│   ├── events.py    # GET /events, GET /events/{id}, POST /ingest/run
│   └── health.py    # GET /health (statut connecteurs + prochain run)
└── models.py        # ORM SQLAlchemy (Event + ConnectorStatus)
```
