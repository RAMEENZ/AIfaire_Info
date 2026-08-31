# 🛡️ Sécurité — (ai)Faire Info

Mesures de durcissement adaptées à l'architecture réelle du projet :
site exposé **uniquement via Cloudflare Tunnel** (connexion sortante,
aucun port web entrant), stack Docker, base PostgreSQL/PostGIS.

## Contenu

| Fichier | Rôle | Où l'exécuter |
|---------|------|---------------|
| `harden-server.sh` | UFW, fail2ban, durcissement SSH, MAJ auto, arrêt Apache2 | Serveur (root, SSH) |
| `backup-postgres.sh` | Sauvegarde chiffrée + **vérifiée** (intégrité avant publication) + rétention | Serveur (cron 02h30) |
| `backup-verify.sh` | Contrôle quotidien : dernier backup récent + déchiffrable + valide (alerte webhook sinon) | Serveur (cron 08h00) |
| `restore-drill.sh` | Exercice de restauration : restaure vraiment la dernière sauvegarde dans un conteneur jetable et contrôle la base obtenue | Serveur (à la main ou cron trimestriel) |
| `cloudflare-setup.md` | WAF, Rate Limiting, Access, HSTS via le dashboard CF | Dashboard Cloudflare |

### Sauvegardes : fiabilité

Le backup écrit d'abord un fichier **temporaire**, **vérifie l'intégrité**
(déchiffrement + décompression + contrôle que c'est bien un dump pg_dump) puis
**publie atomiquement** : un `.enc` présent est donc toujours restaurable (jamais
de fichier final corrompu/partiel). `backup-verify.sh`, planifié après le backup,
**alerte** (webhook `WEBHOOK_URL` : Discord/Slack/ntfy) si la dernière sauvegarde
manque, est trop ancienne (`MAX_AGE_HOURS`, défaut 26 h) ou ne se déchiffre pas.

Activation (en root) :
```bash
echo 'PHRASE_SECRETE_FORTE' > /etc/aifaire-backup.key && chmod 600 /etc/aifaire-backup.key
crontab -e   # puis :
#   30 2 * * *  WEBHOOK_URL=https://ntfy.sh/ton-topic /opt/aifaire/security/backup-postgres.sh >> /var/log/aifaire-backup.log 2>&1
#   0  8 * * *  WEBHOOK_URL=https://ntfy.sh/ton-topic /opt/aifaire/security/backup-verify.sh   >> /var/log/aifaire-backup.log 2>&1
```
Restauration : voir l'en-tête de `backup-postgres.sh`. Vérifier qu'elle marche
vraiment : `restore-drill.sh` (§ exercice de restauration).

### L'alerte : configurée n'est pas fonctionnelle

Les trois scripts alertent par la même fonction :

```bash
curl -fsS -m 15 ... "${WEBHOOK_URL}" >/dev/null 2>&1 || true
```

Le `|| true` est délibéré — un webhook injoignable ne doit pas faire échouer une
sauvegarde par ailleurs réussie. Mais il rend un **webhook cassé silencieux** :
le terminal affiche exactement la même chose que la notification soit partie ou
non. Une ligne de cron qui contient `WEBHOOK_URL` n'est donc pas une alerte qui
fonctionne.

Le vérifier une fois, sans toucher aux sauvegardes — on retire la passphrase,
ce qui fait échouer la vérification pour une raison connue :

```bash
sudo mv /etc/aifaire-backup.key /etc/aifaire-backup.key.bak
sudo WEBHOOK_URL=https://ntfy.sh/ton-topic /opt/aifaire/security/backup-verify.sh
sudo mv /etc/aifaire-backup.key.bak /etc/aifaire-backup.key
sudo /opt/aifaire/security/backup-verify.sh      # pour finir sur un vert
```

Attendu : `ALERTE : passphrase absente`, sortie 1, **et une notification reçue**.
Si le terminal alerte et que le téléphone reste muet, c'est le webhook qu'il faut
reprendre. Pour isoler `curl`, dont le script masque le code de sortie :

```bash
TOPIC=$(sudo crontab -l | head -1 | sed -n 's|.*ntfy.sh/\([^ ]*\).*|\1|p')
curl -fsS -m 15 -H 'Content-Type: application/json' \
  -d '{"text":"test","content":"test"}' "https://ntfy.sh/$TOPIC"; echo "curl : $?"
```

Deux détails qui se découvrent sinon à la première vraie alerte :

- **Le format du message.** La charge utile est `{"text": …, "content": …}` —
  `text` est la clé de Slack, `content` celle de Discord, et l'un ou l'autre
  affiche un message propre sans rien changer. **ntfy prend le corps brut comme
  message** : la notification montrera le JSON tel quel. Lisible, mais laid.
- **Le nom du topic ntfy est le seul secret.** Sans authentification, qui le
  connaît lit les alertes et peut y publier. Ces messages ne contiennent ni
  identifiant ni donnée — seulement « la sauvegarde a échoué » — mais autant
  tirer le nom au hasard (`openssl rand -hex 6`) plutôt que de le choisir
  lisible.

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

### Sauvegardes : hors-site + exercice de restauration

`backup-postgres.sh` vérifie chaque backup avant publication, mais un backup
sur le même disque que la base ne protège ni d'une panne disque ni d'une perte
du serveur. Deux compléments :

**Copie hors-site (une fois rclone configuré)** — le fichier étant chiffré
AES-256, n'importe quel stockage objet convient (Backblaze B2 : 10 Go
gratuits ; Scaleway ; un simple SFTP…) :

```bash
apt install rclone && rclone config        # créer le remote, ex. « b2 »
# puis ajouter RCLONE_REMOTE au cron existant :
30 2 * * *  WEBHOOK_URL=… RCLONE_REMOTE=b2:aifaire-backups /opt/aifaire/security/backup-postgres.sh >> /var/log/aifaire-backup.log 2>&1
```

Rétention hors-site : 35 jours par défaut (`OFFSITE_RETENTION_DAYS`). Un échec
de la copie hors-site alerte via webhook sans invalider le backup local.

**Exercice de restauration (trimestriel)** — une sauvegarde jamais restaurée
n'est qu'un espoir. Le test se fait dans un conteneur jetable, sans toucher à
la production :

```bash
sudo /opt/aifaire/security/restore-drill.sh          # dernière sauvegarde
sudo /opt/aifaire/security/restore-drill.sh /var/backups/aifaire/faire_info-2026-08-01.sql.gz.enc
```

Le script restaure réellement la sauvegarde dans un conteneur
`postgis/postgis:16-3.4` jetable, avec le même `POSTGRES_USER` que le service
`db` de production — le dump porte les propriétaires
(`ALTER … OWNER TO faire_info`), et un conteneur qui ignore ce rôle rejette la
restauration en accusant la sauvegarde à tort. La cible, elle, est créée à part
depuis `template1`, donc **vierge** : un dump complet crée lui-même ses schémas
(`tiger`, `topology`) et ses extensions, et se heurterait à ceux que l'image
installe d'office. C'est aussi la situation réelle d'un sinistre — une machine
neuve. Il vérifie ensuite que la base obtenue est exploitable : les cinq tables applicatives présentes, PostGIS active, au moins
un événement (`MIN_EVENTS`), la géométrie relisible et `alembic_version`
renseignée. Sortie 0 = exercice réussi ; 1 = alerte (webhook si `WEBHOOK_URL`).
Chaque réussite s'inscrit dans `/var/backups/aifaire/.last-restore-drill`.

Planifiable, tant qu'à faire — un exercice qu'on se promet de lancer ne se
lance pas :

```bash
0 6 1 */3 *  WEBHOOK_URL=https://ntfy.sh/ton-topic /opt/aifaire/security/restore-drill.sh >> /var/log/aifaire-backup.log 2>&1
```

> **Ce qui figurait ici avant était un mode opératoire qui ne pouvait pas
> aboutir**, et que rien n'exécutait — d'où le « dernier test : à faire » resté
> tel quel. `pg_dump -d faire_info` (sans `--create`) ne contient ni
> `CREATE DATABASE` ni `\connect` : tout atterrissait dans la base `postgres`,
> et l'étape de vérification échouait sur « database "faire_info" does not
> exist ». Plus grave, sans `-v ON_ERROR_STOP=1`, `psql` sort **0** même après
> une erreur au milieu du script (mesuré : 0 sans le drapeau, 3 avec) : une
> restauration à moitié appliquée passait pour un succès. Un exercice de
> restauration qui ne peut pas échouer ne vérifie rien.

### Hostname du tunnel : config locale non versionnée

Le `cloudflared/config.yml` versionné contient un **placeholder** (dépôt
anonymisé). cloudflared ne lit ce fichier qu'au démarrage du conteneur :
recréer le conteneur avec le placeholder rend tout le site inaccessible en 404
(incident du 30/07/2026). Sur le serveur, une seule fois :

```bash
cd /opt/aifaire
cp cloudflared/config.yml cloudflared/config.local.yml
# → éditer config.local.yml : remplacer le hostname placeholder par le vrai

cat > docker-compose.override.yml <<'EOF'
services:
  cloudflared:
    volumes:
      - ./cloudflared/config.local.yml:/home/nonroot/.cloudflared/config.yml:ro
EOF
docker compose up -d cloudflared
```

Les deux fichiers sont dans `.gitignore` : le vrai domaine ne retourne jamais
dans le dépôt public, et aucun `git pull` ne peut plus le remplacer par le
placeholder.

### Appliquer le Tier 1 sur le serveur (sans rien casser)

Le tunnel passe par le réseau Docker interne, donc rebuild + restart ne coupe
rien d'exposé :

```bash
cd /opt/aifaire
git pull origin main
docker compose up -d --build backend nginx frontend
# Vérifier que /docs est bien fermé (doit renvoyer 404) :
curl -s -o /dev/null -w '%{http_code}\n' https://aifaire.example.com/docs
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
