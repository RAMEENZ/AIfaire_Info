#!/usr/bin/env bash
#
# deploy.sh — déploiement idempotent de FAIRE Info (Docker Compose).
#
# Enchaîne : pull → build → recreate, puis REFUSE de valider le déploiement si
#   - APP_ENV n'est pas "production" (avant ET après recréation), ou
#   - un conteneur ne devient pas "healthy".
# Évite l'oubli classique d'un .env resté en APP_ENV=development.
#
# Usage :
#   ./deploy.sh                     # pull + build/recreate backend & frontend
#   ./deploy.sh backend             # ne (re)construit que le backend
#   SKIP_PULL=1 ./deploy.sh         # ne fait pas de git pull (déploie l'état local)
#   ALLOW_DEV=1  ./deploy.sh        # autorise un déploiement hors production (dev)
#
# Variables d'environnement reconnues :
#   SKIP_PULL=1   → saute l'étape git pull
#   ALLOW_DEV=1   → n'exige pas APP_ENV=production (déploiement de dev assumé)
#   HEALTH_TIMEOUT=120  → délai max (s) d'attente du healthcheck backend
#
set -euo pipefail

# Se placer à la racine du dépôt (là où vit ce script et docker-compose.yml),
# quel que soit le répertoire d'appel.
cd "$(dirname "$(readlink -f "$0")")"

HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-120}"
# Services à (re)construire : arguments passés, sinon backend + frontend.
if [ "$#" -eq 0 ]; then
  SERVICES=(backend frontend)
else
  SERVICES=("$@")
fi

log()  { printf '\033[1;34m▶ %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
err()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; }

die() { err "$*"; exit 1; }

# ── Pré-requis ────────────────────────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || die "docker introuvable."
docker compose version >/dev/null 2>&1 || die "'docker compose' (v2) introuvable."
[ -f docker-compose.yml ] || die "docker-compose.yml absent — mauvais répertoire ?"

# ── Garde-fou APP_ENV (AVANT de déployer) ─────────────────────────────────────
# Valeur effective : ligne explicite du .env, sinon défaut du compose (production).
effective_app_env() {
  local v=""
  if [ -f .env ]; then
    v="$(grep -E '^[[:space:]]*APP_ENV=' .env | tail -1 | cut -d= -f2- | tr -d '[:space:]')"
  fi
  printf '%s' "${v:-production}"
}

APP_ENV_FILE="$(effective_app_env)"
if [ "$APP_ENV_FILE" != "production" ] && [ "${ALLOW_DEV:-0}" != "1" ]; then
  die "APP_ENV=$APP_ENV_FILE dans .env — refus de déployer en production.
  Corrige .env (APP_ENV=production) ou force explicitement avec ALLOW_DEV=1."
fi
ok "Pré-vol : APP_ENV=$APP_ENV_FILE"

# ── 1) Pull ───────────────────────────────────────────────────────────────────
if [ "${SKIP_PULL:-0}" = "1" ]; then
  log "git pull sauté (SKIP_PULL=1)"
else
  branch="$(git rev-parse --abbrev-ref HEAD)"
  log "git pull --ff-only origin $branch"
  git pull --ff-only origin "$branch"
fi

# Commit déployé → exposé par GET / (champ "commit") pour le diagnostic.
export GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo '')"
ok "Commit déployé : ${GIT_SHA:-inconnu}"

# ── 2) Build ──────────────────────────────────────────────────────────────────
log "docker compose build ${SERVICES[*]}"
docker compose build "${SERVICES[@]}"

# ── 3) Recreate ───────────────────────────────────────────────────────────────
log "docker compose up -d --no-deps ${SERVICES[*]}"
docker compose up -d --no-deps "${SERVICES[@]}"

# ── 4) Attente healthcheck ────────────────────────────────────────────────────
wait_healthy() {
  local svc="$1" timeout="$2" waited=0 cid status has_health
  cid="$(docker compose ps -q "$svc" 2>/dev/null || true)"
  [ -n "$cid" ] || { err "$svc : conteneur introuvable"; return 1; }

  has_health="$(docker inspect -f '{{if .State.Health}}yes{{else}}no{{end}}' "$cid")"
  if [ "$has_health" = "no" ]; then
    # Pas de healthcheck (frontend, nginx…) : on vérifie juste qu'il tourne.
    if [ "$(docker inspect -f '{{.State.Running}}' "$cid")" = "true" ]; then
      ok "$svc : running (pas de healthcheck défini)"; return 0
    fi
    err "$svc : arrêté"; return 1
  fi

  while [ "$waited" -lt "$timeout" ]; do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$cid")"
    case "$status" in
      healthy)   ok "$svc : healthy"; return 0 ;;
      unhealthy) err "$svc : unhealthy"; docker compose logs --tail=40 "$svc" || true; return 1 ;;
    esac
    sleep 3; waited=$((waited + 3))
  done
  err "$svc : timeout (${timeout}s) — dernier statut=$status"
  docker compose logs --tail=40 "$svc" || true
  return 1
}

log "Vérification de la santé des services…"
for svc in "${SERVICES[@]}"; do
  wait_healthy "$svc" "$HEALTH_TIMEOUT" || die "Déploiement échoué : $svc n'est pas sain."
done

# ── 5) Garde-fou APP_ENV (APRÈS recréation, valeur réellement vue par le process)
if printf '%s\n' "${SERVICES[@]}" | grep -qx backend; then
  running_env="$(docker compose exec -T backend printenv APP_ENV 2>/dev/null | tr -d '[:space:]' || true)"
  if [ "$running_env" != "production" ] && [ "${ALLOW_DEV:-0}" != "1" ]; then
    die "Le backend tourne en APP_ENV='$running_env' (attendu: production).
  Vérifie le .env et relance, ou force avec ALLOW_DEV=1."
  fi
  ok "Backend en cours d'exécution : APP_ENV=$running_env"
fi

ok "Déploiement terminé."
echo
echo "Vérifs rapides :"
echo "  curl -s http://127.0.0.1:8000/            # {version, commit=${GIT_SHA:-null}}"
echo "  curl -s http://127.0.0.1:8088/api/metrics # état ops (connecteurs, fraîcheur)"
