# Sécurité Cloudflare — FAIRE INFO

Tout le trafic du site entre par **Cloudflare** (`cf-ray` présent dans les
réponses). C'est donc **la meilleure première ligne de défense** : le rate
limiting, le WAF et le blocage doivent se faire **au niveau de Cloudflare**, pas
sur le serveur (qui ne voit que l'IP interne du tunnel, jamais l'IP réelle du
visiteur).

Domaine concerné : `aifaire.ramenz.qzz.io`.

---

## 1. Headers de sécurité & TLS (5 min)

**SSL/TLS → Overview**
- Mode de chiffrement : **Full (strict)** si possible, sinon **Full**.

**SSL/TLS → Edge Certificates**
- ✅ **Always Use HTTPS** : ON (force la redirection http→https).
- ✅ **HTTP Strict Transport Security (HSTS)** : Enable, `max-age` 6 mois,
  *sans* « Include subdomains » au début (évite de bloquer d'autres
  sous-domaines de `ramenz.qzz.io`). Active-le quand tu es sûr.
- ✅ **Minimum TLS Version** : `TLS 1.2`.

> Les headers `X-Frame-Options`, `X-Content-Type-Options`, etc. sont déjà
> ajoutés côté nginx (`nginx/nginx.conf`). Cloudflare les laisse passer.

---

## 2. WAF — règles managées (10 min)

**Security → WAF → Managed rules**
- Active le **Cloudflare Managed Ruleset** (OWASP de base, gratuit).
- Laisse l'action par défaut (Managed Challenge / Block selon le plan).

**Security → WAF → Custom rules** — quelques règles utiles :

| But | Expression | Action |
|-----|-----------|--------|
| Bloquer l'écriture sauf depuis toi | `http.request.method eq "POST" and not ip.src in {TON_IP}` | Block |
| Bloquer les scanners de doc | `http.request.uri.path in {"/docs" "/redoc" "/openapi.json" "/.env" "/.git"}` | Block |
| Geo-restreindre (optionnel) | `not ip.geoip.country in {"FR" "BE" "CH" "LU"}` | Managed Challenge |

> Le POST `/api/ingest/run` est déjà protégé par `X-Api-Key` côté appli ;
> la règle WAF ajoute une 2e couche (défense en profondeur).

---

## 3. Rate Limiting (5 min)

**Security → WAF → Rate limiting rules** (le plan gratuit en autorise une)

Règle recommandée sur l'API :
- **If** : `http.request.uri.path contains "/api/"`
- **Rate** : `100 requests / 1 minute` par IP
- **Then** : *Block* pendant 1 minute (ou *Managed Challenge*).

Ça absorbe les boucles de scraping abusives sans gêner un usage normal
(la carte fait quelques appels par chargement).

---

## 4. Protéger `/docs` et l'ingestion avec Cloudflare Access (optionnel, 15 min)

Si tu veux **garder** la doc Swagger accessible à toi seul plutôt que de la
désactiver totalement :

**Zero Trust → Access → Applications → Add an application → Self-hosted**
- Application domain : `aifaire.ramenz.qzz.io`
- Path : `/docs` (puis répéter pour `/api/ingest`)
- Policy : *Allow* → *Emails* → ton adresse Google.

Résultat : ces chemins exigent une connexion Google. Gratuit jusqu'à 50 users.

> Dans ce repo, la doc est désactivée par défaut (`ENABLE_DOCS=false`). Cette
> étape n'est utile que si tu réactives `ENABLE_DOCS=true` pour ton usage perso.

---

## 5. Vérifier que l'origine n'est pas joignable en direct

Avec le tunnel, le serveur n'expose aucun port web : c'est déjà le cas après
avoir bindé les ports Docker sur `127.0.0.1` (fait dans `docker-compose.yml`).
Pour confirmer depuis l'extérieur, qu'aucun `http://IP_DU_SERVEUR:3000` ou
`:8000` ne réponde :

```bash
# Depuis une autre machine (remplace par l'IP publique du serveur) :
curl -m 5 http://IP_PUBLIQUE:3000/   # doit timeout / refuser la connexion
curl -m 5 http://IP_PUBLIQUE:8000/   # idem
```

Si ça répond → un port est encore exposé : vérifier `docker-compose.yml`
(bind `127.0.0.1:`) et le pare-feu UFW (`security/harden-server.sh`).

---

## Récapitulatif des couches de défense

```
Visiteur
   │  HTTPS
   ▼
Cloudflare edge ──→ [Always HTTPS · HSTS · WAF · Rate limit · Access]
   │  tunnel chiffré sortant
   ▼
cloudflared (Docker) ──→ nginx:80 [headers sécurité · /docs fermé]
   │  réseau Docker interne
   ▼
frontend:3000 / backend:8000   (bindés 127.0.0.1, invisibles d'Internet)
   ▼
PostgreSQL   (jamais exposé · mot de passe fort · backups chiffrés)

Hôte : UFW (entrée fermée sauf SSH) · fail2ban · SSH clé-only · MAJ auto
```
