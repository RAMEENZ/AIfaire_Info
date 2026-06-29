#!/usr/bin/env bash
#
# backup-verify.sh — Vérifie que la DERNIÈRE sauvegarde existe, est RÉCENTE et
# réellement DÉCHIFFRABLE/valide. À planifier en cron (après l'heure du backup)
# pour être ALERTÉ si les sauvegardes s'arrêtent silencieusement ou se corrompent.
#
#   0 8 * * *  WEBHOOK_URL=https://ntfy.sh/ton-topic /opt/aifaire/security/backup-verify.sh >> /var/log/aifaire-backup.log 2>&1
#
# Code de sortie : 0 = OK, 1 = problème (et alerte webhook si WEBHOOK_URL).
#
set -euo pipefail

DB_NAME="${DB_NAME:-faire_info}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/aifaire}"
KEY_FILE="${KEY_FILE:-/etc/aifaire-backup.key}"
MAX_AGE_HOURS="${MAX_AGE_HOURS:-26}"        # un backup quotidien doit avoir < 26h
WEBHOOK_URL="${WEBHOOK_URL:-}"

log()    { printf '%s  %s\n' "$(date '+%F %T')" "$*"; }
notify() {
  [[ -n "${WEBHOOK_URL}" ]] || return 0
  curl -fsS -m 15 -H 'Content-Type: application/json' \
       -d "{\"text\":\"[aifaire-backup] $1\",\"content\":\"[aifaire-backup] $1\"}" \
       "${WEBHOOK_URL}" >/dev/null 2>&1 || true
}
fail() { log "ALERTE : $1"; notify "VÉRIF backup KO : $1"; exit 1; }

[[ -f "${KEY_FILE}" ]] || fail "passphrase absente (${KEY_FILE})"

latest="$(ls -1t "${BACKUP_DIR}"/${DB_NAME}-*.sql.gz.enc 2>/dev/null | head -n1 || true)"
[[ -n "${latest}" ]] || fail "aucune sauvegarde trouvée dans ${BACKUP_DIR}"

mtime="$(stat -c%Y "${latest}" 2>/dev/null || stat -f%m "${latest}")"
age_h=$(( ( $(date +%s) - mtime ) / 3600 ))
(( age_h <= MAX_AGE_HOURS )) \
  || fail "dernier backup trop ancien : ${latest} (${age_h}h > ${MAX_AGE_HOURS}h)"

dec() { openssl enc -d -aes-256-cbc -pbkdf2 -pass "file:${KEY_FILE}" -in "${latest}" 2>/dev/null; }
dec | gunzip > /dev/null 2>&1 \
  || fail "dernier backup non déchiffrable/décompressable : ${latest}"
if ! ( set +o pipefail; dec | gunzip 2>/dev/null | grep -qa "PostgreSQL database dump" ); then
  fail "dernier backup : contenu non reconnu (${latest})"
fi

log "OK : ${latest} récent (${age_h}h) et valide (déchiffrable + dump pg_dump)."
