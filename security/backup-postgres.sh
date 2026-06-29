#!/usr/bin/env bash
#
# backup-postgres.sh — Sauvegarde chiffrée + VÉRIFIÉE de la base PostgreSQL/PostGIS.
#
# pg_dump → gzip → chiffrement AES-256 (openssl), avec :
#   - écriture dans un fichier TEMPORAIRE puis publication ATOMIQUE (jamais de
#     fichier final corrompu/partiel) ;
#   - VÉRIFICATION d'intégrité avant publication (déchiffrement + décompression +
#     contrôle que c'est bien un dump pg_dump) → un backup « réussi » est
#     réellement restaurable ;
#   - ALERTE webhook optionnelle en cas d'échec (WEBHOOK_URL) ;
#   - rétention.
#
# Installation (en root, sur le serveur) :
#   1. chmod +x security/backup-postgres.sh security/backup-verify.sh
#   2. echo 'UNE_PHRASE_SECRETE_FORTE' > /etc/aifaire-backup.key && chmod 600 /etc/aifaire-backup.key
#   3. Test :   ./security/backup-postgres.sh
#   4. Cron (sauvegarde 02h30 + vérification 08h00) :  crontab -e
#        30 2 * * *  WEBHOOK_URL=https://ntfy.sh/ton-topic /opt/aifaire/security/backup-postgres.sh >> /var/log/aifaire-backup.log 2>&1
#        0  8 * * *  WEBHOOK_URL=https://ntfy.sh/ton-topic /opt/aifaire/security/backup-verify.sh   >> /var/log/aifaire-backup.log 2>&1
#
# Restauration :
#   openssl enc -d -aes-256-cbc -pbkdf2 -pass file:/etc/aifaire-backup.key \
#     -in faire_info-AAAA-MM-JJ.sql.gz.enc | gunzip | \
#     docker compose exec -T db psql -U faire_info -d faire_info
#
set -euo pipefail

# ── Configuration (surchargée par l'environnement) ───────────────────────────
COMPOSE_DIR="${COMPOSE_DIR:-/opt/aifaire}"
DB_SERVICE="${DB_SERVICE:-db}"
DB_USER="${DB_USER:-faire_info}"
DB_NAME="${DB_NAME:-faire_info}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/aifaire}"
KEY_FILE="${KEY_FILE:-/etc/aifaire-backup.key}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
MIN_SIZE_BYTES="${MIN_SIZE_BYTES:-1024}"     # un dump valide pèse > 1 Ko
WEBHOOK_URL="${WEBHOOK_URL:-}"               # alerte échec (Discord/Slack/ntfy…)

DATE="$(date +%F)"
OUT="${BACKUP_DIR}/${DB_NAME}-${DATE}.sql.gz.enc"
TMP="${OUT}.tmp.$$"

log()    { printf '%s  %s\n' "$(date '+%F %T')" "$*"; }
notify() {
  [[ -n "${WEBHOOK_URL}" ]] || return 0
  curl -fsS -m 15 -H 'Content-Type: application/json' \
       -d "{\"text\":\"[aifaire-backup] $1\",\"content\":\"[aifaire-backup] $1\"}" \
       "${WEBHOOK_URL}" >/dev/null 2>&1 || true
}
fail()   { log "ERREUR : $1"; notify "ÉCHEC backup ${DB_NAME} : $1"; rm -f "${TMP}"; exit 1; }
trap 'fail "interruption inattendue (ligne ${LINENO})"' ERR

# ── Pré-requis ───────────────────────────────────────────────────────────────
[[ -f "${KEY_FILE}" ]] || fail "passphrase absente (${KEY_FILE}) — voir l'en-tête"
mkdir -p "${BACKUP_DIR}"; chmod 700 "${BACKUP_DIR}"

if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC="docker-compose"; fi
cd "${COMPOSE_DIR}" 2>/dev/null || true

# Commande de dump (surchargeable : Postgres hors Docker, tests…).
DUMP_CMD="${DUMP_CMD:-${DC} exec -T ${DB_SERVICE} pg_dump -U ${DB_USER} -d ${DB_NAME}}"

dec() { openssl enc -d -aes-256-cbc -pbkdf2 -pass "file:${KEY_FILE}" -in "${TMP}" 2>/dev/null; }

# ── Dump → gzip → chiffrement, vers un fichier TEMPORAIRE ─────────────────────
log "Sauvegarde de ${DB_NAME} → ${OUT}"
eval "${DUMP_CMD}" \
  | gzip -9 \
  | openssl enc -aes-256-cbc -pbkdf2 -salt -pass "file:${KEY_FILE}" -out "${TMP}"

# ── Vérification d'intégrité AVANT publication ───────────────────────────────
SIZE_BYTES="$(stat -c%s "${TMP}" 2>/dev/null || stat -f%z "${TMP}")"
[[ "${SIZE_BYTES}" -ge "${MIN_SIZE_BYTES}" ]] \
  || fail "dump trop petit (${SIZE_BYTES} o) — base vide ou dump échoué ?"

# 1) déchiffrement + décompression COMPLETS (lecture totale → pas de SIGPIPE).
dec | gunzip > /dev/null 2>&1 \
  || fail "le backup ne se déchiffre/décompresse pas (corrompu ou mauvaise clé)"

# 2) contenu = bien un dump pg_dump (pipefail off : grep -q ferme le pipe tôt).
if ! ( set +o pipefail; dec | gunzip 2>/dev/null | grep -qa "PostgreSQL database dump" ); then
  fail "contenu déchiffré non reconnu comme un dump pg_dump"
fi

# ── Publication atomique ─────────────────────────────────────────────────────
chmod 600 "${TMP}"; mv -f "${TMP}" "${OUT}"
trap - ERR
log "OK (intégrité vérifiée) : ${OUT} ($(du -h "${OUT}" | cut -f1))"

# ── Rétention ────────────────────────────────────────────────────────────────
find "${BACKUP_DIR}" -name "${DB_NAME}-*.sql.gz.enc" -mtime "+${RETENTION_DAYS}" -print -delete \
  | while read -r f; do log "Purge (>${RETENTION_DAYS}j) : ${f}"; done

log "Terminé. Sauvegardes conservées :"
ls -1t "${BACKUP_DIR}"/${DB_NAME}-*.sql.gz.enc 2>/dev/null | head -n 20 || true
