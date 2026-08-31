# Application Android (APK)

Empaquetage Android du front (ai)Faire Info, avec [Capacitor](https://capacitorjs.com).
Destiné à l'installation directe (« sideload ») ; rien ici ne vise le Play Store.

## Ce que c'est, et ce que ce n'est pas

Le front Next.js est **exporté en fichiers statiques et embarqué dans l'APK**.
L'application n'est donc pas un navigateur pointé sur le site : les pages, le
JavaScript, les contours des départements et le service worker vivent dans le
téléphone. Seules les **données** passent par le réseau, vers l'API publique.

Ce choix a une conséquence qui compte pour une application d'alertes : elle
démarre et affiche le dernier fil connu même sans réseau — précisément la
situation où on l'ouvre. Une simple enveloppe autour de l'URL du site aurait
montré la page d'erreur du navigateur.

**Le site web n'est pas modifié.** `frontend/` continue de se construire en
`output: "standalone"` pour Docker ; l'export statique est un second mode,
déclenché par `NEXT_OUTPUT=export`, que seul ce dossier utilise. Les deux
sorties se construisent depuis les mêmes sources, et rien n'a été retiré du
site pour rendre l'APK possible.

## Prérequis (une seule fois)

- Node 22+ et npm
- un JDK 21 (`sudo apt install openjdk-21-jdk`)
- le SDK Android — Android Studio suffit, ou en ligne de commande :

```bash
mkdir -p ~/android-sdk/cmdline-tools && cd ~/android-sdk
curl -sSLO https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
unzip -q commandlinetools-linux-*.zip -d cmdline-tools
mv cmdline-tools/cmdline-tools cmdline-tools/latest
export ANDROID_HOME=~/android-sdk          # à mettre dans ~/.bashrc
yes | $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager --licenses
$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager \
    "platform-tools" "platforms;android-36" "build-tools;36.0.0"
```

## Construire

```bash
cd mobile
npm install
./build-apk.sh debug
```

L'APK sort dans `mobile/dist/`. La variante `debug` est signée par la clé de
débogage d'Android : elle s'installe telle quelle, sans cérémonie de signature
— c'est celle qu'il faut pour un usage privé.

```bash
adb install -r dist/aifaire-info-1.0.0-debug.apk
```

Sans câble : copiez le fichier sur le téléphone et ouvrez-le. Android demandera
d'autoriser l'installation depuis cette source ; « Play Protect » signalera une
application inconnue, ce qui est le comportement normal pour un APK non publié.

### Variables

| Variable | Défaut | Rôle |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `https://aifaire.ramenz.qzz.io/api` | API interrogée par l'application |
| `NEXT_PUBLIC_SITE_URL` | `https://aifaire.ramenz.qzz.io` | Racine des permaliens partagés depuis l'app |
| `APP_VERSION_NAME` | `1.0.0` | Version affichée |
| `APP_VERSION_CODE` | `1` | Entier **strictement croissant**, exigé par Android pour réinstaller par-dessus |

`NEXT_PUBLIC_API_BASE_URL` doit être une **URL absolue**. La valeur `/api` du
site (que nginx route vers le backend) désignerait ici le téléphone lui-même ;
le script refuse de construire dans ce cas plutôt que de livrer une application
muette.

```bash
NEXT_PUBLIC_API_BASE_URL=https://mon-domaine/api APP_VERSION_CODE=2 \
  ./build-apk.sh debug
```

## Lisibilité sur téléphone

Le front est partagé avec le site : rien ici n'est propre à l'APK. Les
ajustements tactiles sont donc tous posés **sous le point de rupture `sm`**
(639 px) et rétablis au-delà — le site en version bureau garde ses dimensions
au pixel près, et le site consulté au téléphone profite des mêmes gains.

Ce qui a été réglé :

- **Marges d'encoche.** Visant l'API 36, l'application est dessinée bord à
  bord : sans `env(safe-area-inset-top)`, l'en-tête passait sous l'horloge et
  la batterie. Sur le web ces `env()` valent zéro, le site est intact.
- **Cibles tactiles.** 29 commandes mesuraient moins de 44 px de côté ; il en
  reste 4, dont 3 sont les liens d'attribution de Leaflet — des mentions
  légales, pas des commandes.
- **Typographie de lecture.** Titre d'événement 14 → 16 px, résumé 12 → 14 px,
  métadonnées 11 → 12 px.
- **Panneau DOM-TOM replié par défaut.** Déplié, ses onze territoires
  mangeaient près d'un tiers de la carte. Une pastille de couleur sur l'onglet
  replié signale toujours une alerte outre-mer.

Les commandes de Leaflet sont figées à 30 px par sa feuille de style, hors de
portée d'une classe utilitaire : elles sont reprises dans un bloc média en fin
de `frontend/src/app/globals.css`.

## Prérequis côté serveur : CORS

**À faire une fois, sinon l'application s'ouvre mais reste vide.**

La WebView sert les fichiers embarqués depuis `https://localhost` : pour le
backend, l'application est donc une origine tierce, et ses appels sont soumis
au CORS. Or `cors_origins_list` neutralise le caractère générique `*` en
production (fail-closed délibéré) : sans réglage, l'API ne renvoie aucun
`Access-Control-Allow-Origin` et le navigateur jette les réponses.

Dans le `.env` du serveur :

```
CORS_ORIGINS=https://aifaire.ramenz.qzz.io,https://localhost
```

puis `./deploy.sh`. `https://localhost` est l'origine de l'application, et non
une brèche vers la machine du serveur : c'est une chaîne d'origine que seule
une page servie localement peut présenter, et l'API est en lecture seule.
Conservez l'origine du site dans la liste, sinon vous n'autorisez plus que
l'application.

Pour vérifier depuis n'importe quelle machine :

```bash
curl -sI -H 'Origin: https://localhost' https://aifaire.ramenz.qzz.io/api/health \
  | grep -i access-control-allow-origin
```

Une ligne en retour : c'est bon. Rien : le réglage n'est pas actif.

## Signer une version release

Inutile pour un usage privé — `debug` s'installe déjà. À faire seulement pour
distribuer l'application ailleurs.

```bash
keytool -genkey -v -keystore ~/aifaire-release.jks -keyalg RSA -keysize 4096 \
        -validity 10000 -alias aifaire
cat > android/keystore.properties <<'EOF'
storeFile=/chemin/absolu/vers/aifaire-release.jks
storePassword=…
keyAlias=aifaire
keyPassword=…
EOF
./build-apk.sh release
```

`android/keystore.properties` et les fichiers `*.jks` sont ignorés par git.
**Sauvegardez la clé hors du dépôt** : la perdre interdit toute mise à jour de
l'application déjà installée, Android exigeant la même signature.

## Icônes et écran de démarrage

Tout est dérivé de `frontend/public/icon.svg`, l'unique fichier de marque du
dépôt :

```bash
npm run assets
```

Le script régénère `assets/*.png` puis les décline en mipmaps et drawables
Android. Il repasse aussi derrière `@capacitor/assets` pour donner à l'icône
adaptative un fond de couleur pleine — l'outil y met une image encartée de
16,7 %, dont les coins transparents se voient sur les lanceurs qui découpent
au-delà du cercle standard.

## Ce qui est versionné, ce qui ne l'est pas

`android/` est dans le dépôt : c'est là que vivent le manifeste, les icônes et
la configuration Gradle, et les régénérer effacerait ces réglages. En revanche
`android/app/src/main/assets/public/` en est exclu — ce répertoire n'est qu'une
copie de `frontend/out`, refaite à chaque `npx cap sync`.
