#!/usr/bin/env bash
#
# restore-drill.sh — Restaure RÉELLEMENT la dernière sauvegarde dans un
# conteneur jetable et vérifie que la base obtenue est exploitable.
#
# Pourquoi un script et non un mode opératoire à copier-coller : le mode
# opératoire qui figurait dans security/README.md ne pouvait pas aboutir. Il
# n'avait jamais été exécuté (« dernier test : à faire »), et rien ne pouvait
# le dire, puisque rien ne l'exécutait. Deux défauts :
#
#   1. `pg_dump -d faire_info` (sans --create) ne contient NI `CREATE DATABASE`
#      NI `\connect` : envoyé à `psql -U postgres`, tout atterrissait dans la
#      base `postgres`. L'étape suivante, `psql -d faire_info`, échouait sur
#      « database "faire_info" does not exist » — un message qui accuse la
#      sauvegarde alors que le fautif est le mode opératoire.
#   2. Sans `-v ON_ERROR_STOP=1`, psql sort 0 même après une erreur au milieu
#      du script (mesuré : 0 sans le drapeau, 3 avec). Une restauration
#      partielle passait donc pour un succès — exactement ce qu'un exercice de
#      restauration est censé attraper.
#
# À lancer à la main trimestriellement, ou en cron :
#   0 6 1 */3 *  WEBHOOK_URL=https://ntfy.sh/ton-topic /opt/aifaire/security/restore-drill.sh >> /var/log/aifaire-backup.log 2>&1
#
# Code de sortie : 0 = restauration vérifiée, 1 = problème (+ alerte webhook).
#
set -euo pipefail

DB_NAME="${DB_NAME:-faire_info}"
# Rôle propriétaire des objets. Le dump de production est pris avec
# `pg_dump -U faire_info` : il contient des `ALTER … OWNER TO faire_info`. Un
# conteneur de test qui ignore ce rôle rejette la restauration dès la première
# de ces instructions — un échec du banc d'essai, pas de la sauvegarde.
DB_USER="${DB_USER:-faire_info}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/aifaire}"
KEY_FILE="${KEY_FILE:-/etc/aifaire-backup.key}"
# Même image que la production (docker-compose.yml) : restaurer sur une version
# majeure différente ne prouverait rien de ce qu'on veut prouver.
PG_IMAGE="${PG_IMAGE:-postgis/postgis:16-3.4}"
# Une base restaurée vide se « restaure » parfaitement. Le seuil rend l'exercice
# capable d'échouer sur un dump structurellement valide mais vidé de sa substance.
MIN_EVENTS="${MIN_EVENTS:-1}"
BOOT_TIMEOUT="${BOOT_TIMEOUT:-90}"
# Trace machine du dernier exercice réussi : « noter la date à la main » ne
# survit pas au premier trimestre chargé.
STAMP_FILE="${STAMP_FILE:-${BACKUP_DIR}/.last-restore-drill}"
WEBHOOK_URL="${WEBHOOK_URL:-}"

CONTAINER="aifaire-restore-drill-$$"

log()    { printf '%s  %s\n' "$(date '+%F %T')" "$*"; }
notify() {
  [[ -n "${WEBHOOK_URL}" ]] || return 0
  curl -fsS -m 15 -H 'Content-Type: application/json' \
       -d "{\"text\":\"[aifaire-backup] $1\",\"content\":\"[aifaire-backup] $1\"}" \
       "${WEBHOOK_URL}" >/dev/null 2>&1 || true
}
# Le conteneur part quoi qu'il arrive : un exercice qui laisse des débris
# derrière lui ne sera plus jamais lancé.
nettoyer() { docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true; }
trap nettoyer EXIT
fail() { log "ALERTE : $1"; notify "EXERCICE de restauration KO : $1"; exit 1; }

psql_drill() { docker exec -i "${CONTAINER}" psql -U "${DB_USER}" -X -q "$@"; }

# ── Pré-requis ───────────────────────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || fail "docker introuvable"
[[ -f "${KEY_FILE}" ]] || fail "passphrase absente (${KEY_FILE})"

LATEST="${1:-$(ls -1t "${BACKUP_DIR}"/${DB_NAME}-*.sql.gz.enc 2>/dev/null | head -n1 || true)}"
[[ -n "${LATEST}" ]] || fail "aucune sauvegarde trouvée dans ${BACKUP_DIR}"
[[ -f "${LATEST}" ]] || fail "sauvegarde introuvable : ${LATEST}"
log "Sauvegarde retenue : ${LATEST}"

# ── 1) Serveur jetable ───────────────────────────────────────────────────────
# Pas de port publié : on entre par `docker exec`. Aucun risque de collision
# avec la base de production, ni d'exposition réseau.
#
# POSTGRES_USER et POSTGRES_DB reprennent ceux du service `db` de production
# (docker-compose.yml) : l'entrypoint de l'image crée alors le rôle ET la base
# exactement comme en production, et l'image postgis installe l'extension dans
# cette base. Sans cela, la restauration échouait sur
# `role "faire_info" does not exist` — le dump portant les propriétaires, un
# banc d'essai qui les ignore accuse la sauvegarde à tort.
docker run -d --name "${CONTAINER}" \
  -e POSTGRES_USER="${DB_USER}" -e POSTGRES_PASSWORD=drill -e POSTGRES_DB="${DB_NAME}" \
  "${PG_IMAGE}" >/dev/null \
  || fail "impossible de démarrer ${PG_IMAGE}"

# `sleep 15` était un pari sur la vitesse de démarrage ; on attend le serveur.
deadline=$(( $(date +%s) + BOOT_TIMEOUT ))
until docker exec "${CONTAINER}" pg_isready -U "${DB_USER}" -d "${DB_NAME}" >/dev/null 2>&1; do
  (( $(date +%s) < deadline )) || fail "le serveur de test n'accepte pas les connexions après ${BOOT_TIMEOUT}s"
  sleep 1
done
log "Serveur de test prêt (${PG_IMAGE})."

# ── 2) Restauration ──────────────────────────────────────────────────────────
# La base existe déjà (créée par l'entrypoint, cf. POSTGRES_DB ci-dessus).
#
# ON_ERROR_STOP=1 : la moindre instruction en échec avorte la restauration et
# fait sortir psql en 3. C'est tout l'intérêt de l'exercice — sans ce drapeau,
# psql sort 0 après une erreur au milieu du script et une restauration à moitié
# appliquée passerait pour un succès.
journal="$(mktemp)"
if ! openssl enc -d -aes-256-cbc -pbkdf2 -pass "file:${KEY_FILE}" -in "${LATEST}" 2>/dev/null \
     | gunzip \
     | psql_drill -d "${DB_NAME}" -v ON_ERROR_STOP=1 >/dev/null 2>"${journal}"; then
  # Montrer l'erreur de PostgreSQL : elle dit si la sauvegarde est en cause ou
  # si c'est l'environnement de test qui ne sait pas l'accueillir.
  tail -5 "${journal}" >&2 || true
  rm -f "${journal}"
  fail "la restauration de ${LATEST} a échoué (déchiffrement, décompression ou SQL)"
fi
rm -f "${journal}"
log "Restauration terminée sans erreur SQL."

# ── 3) Vérifications sur la base restaurée ───────────────────────────────────
# Restaurer sans erreur ne prouve pas qu'on a récupéré quelque chose d'utile.
requete() { psql_drill -d "${DB_NAME}" -tAc "$1" 2>/dev/null | tr -d '[:space:]'; }

for table in events connector_status daily_stats push_subscriptions daily_briefs; do
  [[ "$(requete "SELECT to_regclass('public.${table}') IS NOT NULL")" == "t" ]] \
    || fail "table absente de la base restaurée : ${table}"
done
log "Les cinq tables applicatives sont présentes."

[[ "$(requete "SELECT postgis_version() IS NOT NULL")" == "t" ]] \
  || fail "PostGIS absente de la base restaurée (la colonne geom serait inexploitable)"

nb_events="$(requete "SELECT count(*) FROM events")"
[[ "${nb_events}" =~ ^[0-9]+$ ]] || fail "impossible de compter les événements restaurés"
(( nb_events >= MIN_EVENTS )) \
  || fail "base restaurée quasi vide : ${nb_events} événement(s) < ${MIN_EVENTS}"

# La géométrie est le seul type non trivial du schéma : la relire prouve que
# l'extension et les données binaires ont survécu à l'aller-retour.
nb_geom="$(requete "SELECT count(*) FROM events WHERE geom IS NOT NULL")"
if [[ "${nb_geom}" =~ ^[0-9]+$ ]] && (( nb_geom > 0 )); then
  requete "SELECT ST_AsText(geom) FROM events WHERE geom IS NOT NULL LIMIT 1" >/dev/null \
    || fail "géométrie illisible dans la base restaurée"
fi

# Depuis l'unification du schéma, Alembic est le seul maître : une base
# restaurée sans niveau de migration repartirait dans le brouillard.
version="$(requete "SELECT version_num FROM alembic_version" || true)"
[[ -n "${version}" ]] || fail "alembic_version absente ou vide dans la base restaurée"

printf '%s  %s  events=%s  alembic=%s\n' \
  "$(date '+%F %T')" "$(basename "${LATEST}")" "${nb_events}" "${version}" \
  >> "${STAMP_FILE}" 2>/dev/null || true

log "OK : ${nb_events} événement(s), ${nb_geom} géolocalisé(s), schéma au niveau ${version}."
log "Exercice de restauration réussi. Trace : ${STAMP_FILE}"
