#!/usr/bin/env bash
#
# harden-server.sh — Durcissement du serveur hôte FAIRE INFO (Debian/Ubuntu).
#
# Architecture : le site est exposé UNIQUEMENT via Cloudflare Tunnel (cloudflared
# ouvre une connexion SORTANTE). AUCUN port web entrant n'est nécessaire.
# Ce script verrouille donc tout le trafic entrant sauf SSH.
#
# ⚠️  À RELIRE AVANT EXÉCUTION. Lance-le toi-même en SSH, en root :
#       sudo bash security/harden-server.sh
#
# Idempotent : peut être relancé sans danger. Ne touche PAS à Docker ni au stack.
#
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Lance ce script en root : sudo bash $0" >&2
  exit 1
fi

SSH_PORT="${SSH_PORT:-22}"
log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }

# ─────────────────────────────────────────────────────────────────────
_log "1/6 — Mises à jour de sécurité automatiques (unattended-upgrades)"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq unattended-upgrades apt-listchanges
dpkg-reconfigure -f noninteractive unattended-upgrades
systemctl enable --now unattended-upgrades
echo "   → patchs de sécurité Debian appliqués automatiquement."

# ─────────────────────────────────────────────────────────────────────
log "2/6 — Pare-feu UFW : tout fermé en entrée sauf SSH"
# RAPPEL IMPORTANT : Docker écrit ses propres règles iptables et CONTOURNE UFW.
# Les ports publiés par Docker doivent être bindés sur 127.0.0.1 dans le
# docker-compose.yml (déjà fait dans ce repo). UFW protège ici l'hôte (SSH).
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ufw
ufw --force reset
ufw default deny incoming
ufw default allow outgoing          # cloudflared a besoin du sortant
ufw allow "${SSH_PORT}/tcp" comment 'SSH'
# On n'ouvre NI 80 NI 443 : le tunnel Cloudflare est sortant, rien à exposer.
ufw --force enable
ufw status verbose

# ─────────────────────────────────────────────────────────────────────
log "3/6 — fail2ban : bannit les IP qui brute-forcent SSH"
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq fail2ban
cat > /etc/fail2ban/jail.d/sshd.local <<EOF
[sshd]
enabled  = true
port     = ${SSH_PORT}
backend  = systemd
maxretry = 4
findtime = 10m
bantime  = 1h
# Bannissement progressif : récidive = ban plus long.
bantime.increment = true
bantime.factor    = 2
EOF
systemctl enable --now fail2ban
systemctl restart fail2ban
fail2ban-client status sshd || true

# ─────────────────────────────────────────────────────────────────────
log "4/6 — Durcissement SSH (clé uniquement, pas de root par mot de passe)"
warn "Ne ferme PAS ta session actuelle. Ouvre une 2e session pour tester avant."
warn "Assure-toi d'avoir déjà une clé publique dans ~/.ssh/authorized_keys !"
SSHD_HARDEN=/etc/ssh/sshd_config.d/99-hardening.conf
mkdir -p /etc/ssh/sshd_config.d
cat > "${SSHD_HARDEN}" <<'EOF'
# Durcissement FAIRE INFO — clé only
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
MaxAuthTries 3
LoginGraceTime 30
X11Forwarding no
EOF
if sshd -t; then
  systemctl reload ssh 2>/dev/null || systemctl reload sshd
  echo "   → SSH rechargé : authentification par clé uniquement."
else
  warn "Config SSH invalide — modifications NON appliquées. Vérifie ${SSHD_HARDEN}."
  rm -f "${SSHD_HARDEN}"
fi

# ─────────────────────────────────────────────────────────────────────
log "5/6 — Arrêt d'Apache2 résiduel (port 80 inutile, le tunnel suffit)"
if systemctl is-enabled apache2 >/dev/null 2>&1 || systemctl is-active apache2 >/dev/null 2>&1; then
  systemctl disable --now apache2
  echo "   → apache2 arrêté et désactivé."
else
  echo "   → apache2 absent ou déjà désactivé, rien à faire."
fi

# ─────────────────────────────────────────────────────────────────────
log "6/6 — Vérifications finales"
echo "Ports en écoute exposés hors localhost (devrait ne montrer que SSH) :"
ss -tlnp 2>/dev/null | awk 'NR==1 || ($4 !~ /127\.0\.0\.1|::1/)' || true

log "Terminé. Récapitulatif :"
cat <<'EOF'
  ✓ Mises à jour de sécurité automatiques
  ✓ UFW : entrée bloquée sauf SSH
  ✓ fail2ban actif sur SSH
  ✓ SSH par clé uniquement (si une clé était déjà en place)
  ✓ Apache2 désactivé

  PROCHAINES ÉTAPES MANUELLES :
  - Ouvre une NOUVELLE session SSH pour confirmer que la connexion par clé marche
    AVANT de fermer celle-ci (filet de sécurité).
  - Configure Cloudflare WAF + Rate Limiting : voir security/cloudflare-setup.md
  - Mets en place les sauvegardes : security/backup-postgres.sh
EOF
