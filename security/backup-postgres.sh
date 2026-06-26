#!/usr/bin/env bash
#
# backup-postgres.sh — Sauvegarde chiffrée de la base PostgreSQL/PostGIS.
#
# Fait un pg_dump du conteneur Docker `db`, le compresse, le chiffre avec une
# passphrase (AES-256 via openssl), applique une rétention et journalise.
#
# Installation (en root, sur le serveur) :
#   1. Copier ce script :        /opt/aifaire/security/backup-postgres.sh
#   2. Le rendre exécutable :     chmod +x backup-postgres.sh
#   3. Définir la passphrase :    echo 'UNE_PHRASE_SECRETE_FORTE' > /etc/aifaire-backup.key
#                                 chmod 600 /etc/aifaire-backup.key
#   4. Tester :                   ./backup-postgres.sh
#   5. Planifier (cron, 02h30) :  crontab -e
#        30 2 * * *  /opt/aifaire/security/backup-postgres.sh >> /var/log/aifaire-backup.log 2>&1
#
# Restauration :
#   openssl enc -d -aes-256-cbc -pbkdf2 -pass file:/etc/aifaire-backup.key \
#     -in faire_info-AAAA-MM-JJ.sql.gz.enc | gunzip | \
#     docker compose exec -T db psql -U faire_info -d faire_info
#
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────────
COMPOSE_DIR="${COMPOSE_DIR:-/opt/aifaire}"   # dossier contenant docker-compose.yml
DB_SERVICE="${DB_SERVICE:-db}"
DB_USER="${DB_USER:-faire_info}"
DB_NAME="${DB_NAME:-faire_info}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/aifaire}"
KEY_FILE="${KEY_FILE:-/etc/aifaire-backup.key}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

DATE="$(date +%F)"
OUT="${BACKUP_DIR}/${DB_NAME}-${DATE}.sql.gz.enc"

log() { printf '%s  %s\n' "$(date '+%F %T')" "$*"; }

# ── Pré-requis ───────────────────────────────────────────────────────────────────
if [[ ! -f "${KEY_FILE}" ]]; then
  log "ERREUR : passphrase absente (${KEY_FILE}). Voir l'en-tête du script."
  exit 1
fi
mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

# docker compose (v2) ou docker-compose (v1)
if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC="docker-compose"; fi
cd "${COMPOSE_DIR}"

# ── Dump → gzip → chiffrement (flux, sans fichier clair intermédiaire) ────────
log "Sauvegarde de ${DB_NAME} → ${OUT}"
${DC} exec -T "${DB_SERVICE}" pg_dump -U "${DB_USER}" -d "${DB_NAME}" \
  | gzip -9 \
  | openssl enc -aes-256-cbc -pbkdf2 -salt -pass "file:${KEY_FILE}" -out "${OUT}"
chmod 600 "${OUT}"

SIZE="$(du -h "${OUT}" | cut -f1)"
log "OK : ${OUT} (${SIZE})"

# ── Rétention : purge des sauvegardes plus vieilles que RETENTION_DAYS ────────
find "${BACKUP_DIR}" -name "${DB_NAME}-*.sql.gz.enc" -mtime "+${RETENTION_DAYS}" -print -delete \
  | while read -r f; do log "Purge (>${RETENTION_DAYS}j) : ${f}"; done

log "Terminé. Sauvegardes conservées :"
ls -1t "${BACKUP_DIR}"/${DB_NAME}-*.sql.gz.enc 2>/dev/null | head -n 20 || true
