# 🛡️ Sécurité — FAIRE INFO

Mesures de durcissement adaptées à l'architecture réelle du projet :
site exposé **uniquement via Cloudflare Tunnel** (connexion sortante,
aucun port web entrant), stack Docker, base PostgreSQL/PostGIS.

## Contenu

| Fichier | Rôle | Où l'exécuter |
|---------|------|---------------|
| `harden-server.sh` | UFW, fail2ban, durcissement SSH, MAJ auto, arrêt Apache2 | Serveur (root, SSH) |
| `backup-postgres.sh` | Sauvegarde chiffrée + rétention de la base | Serveur (cron) |
| `cloudflare-setup.md` | WAF, Rate Limiting, Access, HSTS via le dashboard CF | Dashboard Cloudflare |

## Déjà appliqué dans le code (Tier 1)

Ces correctifs sont **dans le repo** (commités), pas à refaire :

- **Ports Docker bindés sur `127.0.0.1`** (`docker-compose.yml`) — le backend,
  le frontend et nginx ne sont plus joignables en direct depuis Internet. Le
  tunnel les atteint par le réseau Docker interne. ⚠️ C'était la faille #1
  (accès brut `http://IP:3000`).
- **Doc API fermée par défaut** (`ENABLE_DOCS=false`) — Swagger `/docs`, ReDoc
  et `/openapi.json` ne sont plus exposés publiquement (`backend/app/config.py`,
  `backend/app/main.py`, `nginx/nginx.conf`).
- **Headers de sécurité nginx** — `X-Frame-Options`, `X-Content-Type-Options`,
  `Referrer-Policy`, `Strict-Transport-Security`, masquage `Server` et
  `X-Powered-By` (`nginx/nginx.conf`).

### Appliquer le Tier 1 sur le serveur (sans rien casser)

Le tunnel passe par le réseau Docker interne, donc rebuild + restart ne coupe
rien d'exposé :

```bash
cd /opt/aifaire
git pull origin main
docker compose up -d --build backend nginx frontend
# Vérifier que /docs est bien fermé (doit renvoyer 404) :
curl -s -o /dev/null -w '%{http_code}\n' https://aifaire.ramenz.qzz.io/docs
```

## Priorités

1. **Tier 1** (ci-dessus) — déjà fait, juste à déployer.
2. **`harden-server.sh`** — UFW + fail2ban + SSH (relire puis `sudo bash`).
3. **`cloudflare-setup.md`** — WAF + Rate Limiting (10 min dans le dashboard).
4. **`backup-postgres.sh`** — sauvegardes chiffrées planifiées.

## Ce qui est volontairement écarté

- **ClamAV** : faible intérêt ici (aucun upload utilisateur, aucun stockage de
  fichiers tiers). Coûteux en RAM pour un gain quasi nul sur cette app.
- **fail2ban sur le web** : inutile, nginx ne voit que l'IP du tunnel. Le rate
  limiting se fait chez Cloudflare. fail2ban ne sert qu'à protéger **SSH**.
- **CSP stricte** : casserait les tuiles Leaflet et les styles inline Next.js.
  À ajouter séparément après test, pas en automatique.
