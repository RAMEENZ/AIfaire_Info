# Faire.info — Agrégateur d'information géolocalisé (France)

Vue cartographique unifiée de l'actualité publique française en quasi temps réel.

## Stack

- **Backend** : Python 3.11 + FastAPI + GeoAlchemy2 + APScheduler
- **Frontend** : Next.js 14 + Leaflet + Tailwind CSS
- **BDD** : PostgreSQL 16 + PostGIS 3.4
- **IA** : Claude Haiku (extraction lieu + teaser)
- **Géocodage** : BAN (api-adresse.data.gouv.fr) + geo.api.gouv.fr

## Sources (MVP Lot 0)

| Source | Catégorie | Accès |
|---|---|---|
| Météo-France Vigilance | Météo | Open data |
| Vigicrues | Crue | API publique |
| RéNaSS | Séisme | FDSN API |
| Enedis | Énergie | Open data |
| RSS Presse régionale | Actualité | RSS |

## Démarrage local

### Prérequis
- Docker + Docker Compose
- Python 3.11+
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

L'interface est disponible sur http://localhost:3000.  
L'API est disponible sur http://localhost:8000/docs (Swagger auto-généré).

## Pipeline

Le pipeline tourne automatiquement à **9h00** et **19h00** (heure Paris).  
Pour déclencher manuellement : `POST /api/ingest/run`

## Architecture

```
[Sources] → [Connectors] → [Extractor IA] → [Geocoder BAN] → [PostgreSQL/PostGIS] → [API FastAPI] → [Next.js + Leaflet]
```
