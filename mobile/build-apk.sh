#!/usr/bin/env bash
#
# Génère l'APK Android de (ai)Faire Info.
#
#   ./build-apk.sh [debug|release]
#
# L'application n'est pas un navigateur déguisé : le front Next.js est exporté
# en fichiers statiques (`NEXT_OUTPUT=export`) et EMBARQUÉ dans l'APK. Seules
# les données transitent par le réseau, vers l'API publique. L'application
# démarre donc même hors ligne, et son service worker sert le dernier fil connu
# — ce qui a du sens pour une application d'alertes, qu'on ouvre justement
# quand le réseau est mauvais.
#
# Ce que le script attend :
#   - Node 22+ et npm (le dépôt s'en sert déjà)
#   - un JDK 21
#   - le SDK Android, via ANDROID_HOME ou ANDROID_SDK_ROOT
#
# Variables utiles :
#   NEXT_PUBLIC_API_BASE_URL   API interrogée par l'application (défaut :
#                              l'instance publique). Une URL RELATIVE comme
#                              « /api » est ici inutilisable : dans la WebView
#                              elle désignerait le téléphone lui-même.
#   NEXT_PUBLIC_SITE_URL       Origine publique du site : racine des permaliens
#                              partagés depuis l'application.
#   APP_VERSION_NAME           Version affichée (défaut 1.0.0)
#   APP_VERSION_CODE           Entier croissant exigé par Android (défaut 1)
set -euo pipefail

VARIANTE="${1:-debug}"
case "$VARIANTE" in
  debug|release) ;;
  *) echo "Usage : $0 [debug|release]" >&2; exit 2 ;;
esac

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONT="$ICI/../frontend"

: "${ANDROID_HOME:=${ANDROID_SDK_ROOT:-}}"
if [[ -z "$ANDROID_HOME" || ! -d "$ANDROID_HOME/platforms" ]]; then
  cat >&2 <<'MSG'
SDK Android introuvable. Renseignez ANDROID_HOME (ou ANDROID_SDK_ROOT).
Installation minimale, sans Android Studio :

  mkdir -p ~/android-sdk/cmdline-tools && cd ~/android-sdk
  curl -sSLO https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
  unzip -q commandlinetools-linux-*.zip -d cmdline-tools
  mv cmdline-tools/cmdline-tools cmdline-tools/latest
  export ANDROID_HOME=~/android-sdk
  yes | $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager --licenses
  $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager \
      "platform-tools" "platforms;android-36" "build-tools;36.0.0"
MSG
  exit 1
fi
export ANDROID_HOME
export ANDROID_SDK_ROOT="$ANDROID_HOME"

export NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-https://aifaire.ramenz.qzz.io/api}"
export NEXT_PUBLIC_SITE_URL="${NEXT_PUBLIC_SITE_URL:-https://aifaire.ramenz.qzz.io}"
APP_VERSION_NAME="${APP_VERSION_NAME:-1.0.0}"
APP_VERSION_CODE="${APP_VERSION_CODE:-1}"

# Une URL relative fonctionne sur le web (nginx route /api/) mais pas dans une
# WebView, dont l'origine est https://localhost — c'est-à-dire l'appareil.
# Mieux vaut l'arrêter ici qu'obtenir une application vide et muette.
if [[ "$NEXT_PUBLIC_API_BASE_URL" != http://* && "$NEXT_PUBLIC_API_BASE_URL" != https://* ]]; then
  echo "NEXT_PUBLIC_API_BASE_URL doit être une URL absolue (reçu : $NEXT_PUBLIC_API_BASE_URL)" >&2
  exit 2
fi

echo "==> API      : $NEXT_PUBLIC_API_BASE_URL"
echo "==> Site     : $NEXT_PUBLIC_SITE_URL"
echo "==> Version  : $APP_VERSION_NAME ($APP_VERSION_CODE), variante $VARIANTE"

echo "==> Export statique du front Next.js"
cd "$FRONT"
[[ -d node_modules ]] || npm ci --no-audit --no-fund
rm -rf out
NEXT_OUTPUT=export npx next build

echo "==> Copie des fichiers dans le projet Android"
cd "$ICI"
[[ -d node_modules ]] || npm ci --no-audit --no-fund
npx cap sync android

echo "==> Compilation Gradle"
cd "$ICI/android"
TACHE=$([[ "$VARIANTE" == "debug" ]] && echo assembleDebug || echo assembleRelease)
./gradlew --no-daemon "$TACHE" \
  -PappVersionCode="$APP_VERSION_CODE" \
  -PappVersionName="$APP_VERSION_NAME"

SRC=$(find "$ICI/android/app/build/outputs/apk/$VARIANTE" -name '*.apk' | head -1)
DEST="$ICI/dist/aifaire-info-$APP_VERSION_NAME-$VARIANTE.apk"
mkdir -p "$(dirname "$DEST")"
cp "$SRC" "$DEST"

echo
echo "APK : $DEST"
ls -lh "$DEST" | awk '{print "Taille :", $5}'
if [[ "$VARIANTE" == "release" && "$SRC" == *unsigned* ]]; then
  echo "ATTENTION : construit sans clé de signature — Android refusera de l'installer."
  echo "Voir la section « Signer une version release » du README."
fi
echo "Installation : adb install -r \"$DEST\""
