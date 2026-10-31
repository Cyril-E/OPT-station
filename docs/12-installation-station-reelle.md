# Installer OPT Station avec le matériel réel

Procédure manuelle pour **Raspberry Pi OS 64 bits**, Raspberry Pi 5 et ACS ACR1552U-M1. Les dépendances et essais de référence utilisent Trixie arm64. La caméra QR et l’affichage local restent optionnels selon le montage; les profils matériels sont décrits dans les guides [caméra](11-camera-qr.md) et [écran](10-ecran-tactile.md).

L’[installateur en une commande](33-installation-une-commande.md) est disponible depuis v0.17.0. Sa réinstallation réelle est validée; une première installation complète sur carte SD vierge reste à qualifier. Cette procédure manuelle installe **v0.17.0**, puis active HTTPS avec Caddy, les certificats et l’aide aux clients. Le dépôt est public et les téléchargements ne demandent ni compte ni jeton GitHub.

## Conventions des exemples

Les commandes sur le Pi s’exécutent avec le compte ordinaire qui utilisera la station, sauf celles préfixées par `sudo`. `$HOME` désigne le dossier de ce compte. Les exemples SSH utilisent `maker@opt-station.local` : remplacer **maker** et **opt-station.local** par le compte et le nom réels du Pi.

Les adresses `192.0.2.x` mentionnées ailleurs sont réservées à la documentation; ne pas les recopier comme adresses d’équipements. Le logiciel annonce l’adresse détectée au lancement. Une IP fixe particulière n’est pas nécessaire.

## 1. Installer les paquets sur le Pi

Brancher le lecteur en USB. Manipuler les nappes caméra et écran alimentation débranchée.

```sh
sudo apt update
sudo apt install --no-install-recommends python3 python3-venv python3-picamera2 python3-libcamera python3-numpy python3-pil firefox desktop-file-utils libglib2.0-bin pcscd libccid pcsc-tools python3-pyscard ffmpeg
sudo systemctl enable --now pcscd.socket
lsusb -d 072f:2303
dpkg-query -W pcscd libccid pcsc-tools python3-pyscard ffmpeg
mkdir -p "$HOME/apps"
```

Les mots de passe administrateur se saisissent uniquement dans le terminal du Pi. Aucun pilote ACS séparé ni `sudo pip` n’est nécessaire pour le profil ACR1552U-M1 qualifié. Les versions installées peuvent varier selon les dépôts du système; vérifier qu’elles prennent en charge le matériel utilisé.

## 2. Télécharger les sources complètes

Depuis un ordinateur disposant de curl et d’un accès SSH au Pi :

```sh
OPT_VERSION=v0.17.0
OPT_PI=maker@opt-station.local
OPT_DOWNLOAD="$PWD/opt-station-downloads/$OPT_VERSION"
mkdir -p "$OPT_DOWNLOAD"
OPT_RELEASE_URL="https://github.com/Cyril-E/OPT-station/releases/download/$OPT_VERSION"
curl --fail --location --proto "=https" --tlsv1.2 "$OPT_RELEASE_URL/opt-station-${OPT_VERSION}.tar.gz" --output "$OPT_DOWNLOAD/opt-station-${OPT_VERSION}.tar.gz"
curl --fail --location --proto "=https" --tlsv1.2 "$OPT_RELEASE_URL/opt-station-${OPT_VERSION}.tar.gz.sha256" --output "$OPT_DOWNLOAD/opt-station-${OPT_VERSION}.tar.gz.sha256"
(cd "$OPT_DOWNLOAD" && shasum -a 256 -c "opt-station-${OPT_VERSION}.tar.gz.sha256")
ssh "$OPT_PI" 'mkdir -p "$HOME/apps"'
scp "$OPT_DOWNLOAD/opt-station-${OPT_VERSION}.tar.gz" "$OPT_DOWNLOAD/opt-station-${OPT_VERSION}.tar.gz.sha256" "${OPT_PI}:apps/"
```

Sur Linux, `sha256sum -c` peut remplacer `shasum -a 256 -c`. Les archives publiques ne demandent aucun jeton. Ces commandes téléchargent uniquement les sources pour le parcours manuel; le [parcours en une commande](33-installation-une-commande.md) automatise les étapes suivantes.

**Sur le Pi**, vérifier l’archive et l’extraire dans un dossier neuf :

```sh
OPT_VERSION=v0.17.0
OPT_SOURCE="$HOME/apps/opt-station-$OPT_VERSION"
(cd "$HOME/apps" && sha256sum -c "opt-station-${OPT_VERSION}.tar.gz.sha256")
if [ -e "$OPT_SOURCE" ]; then
  echo "Le dossier existe déjà. Choisir un nouveau dossier ou reprendre son installation."
  exit 1
fi
mkdir -p "$OPT_SOURCE"
tar -xzf "$HOME/apps/opt-station-${OPT_VERSION}.tar.gz" -C "$OPT_SOURCE"
```

L’archive jointe à cette release contient les sources à sa racine. Conserver `references/`, `resources/`, `deploy/`, les verrous et les tests avec le code. Ne pas transférer une `.venv`, une base d’essai ou les fichiers privés d’une autre machine.

## 3. Préparer Python sur le Pi

```sh
cd "$OPT_SOURCE"
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --only-binary=:all: -r requirements.lock -r requirements-camera.lock
.venv/bin/python -c 'import smartcard, picamera2, libcamera, zxingcpp; print("Composants NFC et caméra disponibles")'
.venv/bin/python -m pytest -q
```

L’option `--system-site-packages` donne accès aux bibliothèques NFC/caméra de Raspberry Pi OS; les autres dépendances restent dans l’environnement. Les tests utilisent des périphériques fictifs et ne doivent pas écrire sur un tag branché. La version v0.17.0 est qualifiée par 677 tests sur Pi et 676 sur Mac, avec le test propre à systemd ignoré sur Mac, dont un test réel de passerelle qui demande Caddy (voir le [guide HTTPS](31-https-local.md#vérifications-et-références)); sans ce binaire, ce test est ignoré.

## 4. Sauvegarder une installation existante

Terminer les opérations matérielles avant d’arrêter le serveur :

```sh
systemctl --user stop openprinttag.service
```

Sur une première installation, l’absence de ce service est attendue. Sauvegarder les données et les fichiers de lancement existants :

```sh
umask 077
OPT_BACKUP="$HOME/openprinttag-backups/before-update-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OPT_BACKUP"
for OPT_FILE in .config/systemd/user/openprinttag.service .config/systemd/user/openprinttag.service.d/network.conf .config/systemd/user/openprinttag.service.d/https.conf .config/systemd/user/openprinttag-display.service .config/systemd/user/openprinttag-display.service.d/https.conf .config/autostart/openprinttag.desktop .local/lib/openprinttag-screen/launch.py; do
  if [ -f "$HOME/$OPT_FILE" ]; then
    mkdir -p "$OPT_BACKUP/$(dirname "$OPT_FILE")"
    cp -p "$HOME/$OPT_FILE" "$OPT_BACKUP/$OPT_FILE"
  fi
done
if [ -L "$HOME/apps/openprinttag-station" ]; then
  readlink -f "$HOME/apps/openprinttag-station" > "$OPT_BACKUP/source-before.txt"
fi
if [ -d "$HOME/openprinttag-data" ]; then
  tar -czf "$OPT_BACKUP/data-before.tar.gz" -C "$HOME" openprinttag-data
fi
```

Conserver cette sauvegarde privée : elle peut contenir des clés, mots de passe, données d’inventaire et images de tags. La base doit être sauvegardée de façon cohérente, serveur arrêté. La version v0.20.0 utilise le schéma 6 pour inclure les photos, après le schéma 5 des versions v0.14.0 à v0.19.0. Les anciennes bases compatibles sont migrées sans remplacer les fiches. Pour revenir à une version antérieure, restaurer ensemble les sources et les données sauvegardées avant migration. Une station déjà en HTTPS doit aussi conserver ses fichiers système et son autorité, selon le [guide HTTPS](31-https-local.md#redémarrage-et-mises-à-jour).

## 5. Installer les services et le plein écran

Depuis un terminal de la session graphique du Pi, dans le dossier des sources préparées :

```sh
cd "$OPT_SOURCE"
mkdir -p "$HOME/.config/systemd/user" "$HOME/.config/autostart" "$HOME/.local/lib/openprinttag-screen" "$HOME/openprinttag-data"
ln -s "$PWD" "$HOME/apps/openprinttag-station.next"
mv -Tf "$HOME/apps/openprinttag-station.next" "$HOME/apps/openprinttag-station"
install -m 600 deploy/openprinttag.service "$HOME/.config/systemd/user/openprinttag.service"
install -m 600 deploy/openprinttag-display.service "$HOME/.config/systemd/user/openprinttag-display.service"
install -m 600 deploy/openprinttag-display.py "$HOME/.local/lib/openprinttag-screen/launch.py"
python3 - <<'SETUP'
from pathlib import Path
home = Path.home()
target = home / '.config/autostart/openprinttag.desktop'
target.write_text(Path('deploy/openprinttag.desktop.in').read_text().replace('@HOME@', str(home)))
target.chmod(0o600)
SETUP
desktop-file-validate "$HOME/.config/autostart/openprinttag.desktop"
systemctl --user daemon-reload
systemd-analyze --user verify "$HOME/.config/systemd/user/openprinttag.service" "$HOME/.config/systemd/user/openprinttag-display.service"
systemctl --user enable --now openprinttag.service
gio launch "$HOME/.config/autostart/openprinttag.desktop"
```

Si le lien `.next` existe déjà, inspecter son origine avant de reprendre. Pour une installation déjà configurée, comparer ses services et éventuels fichiers `override` avant de les remplacer. Les modèles fournis activent `--mode hardware --camera --lan` et utilisent `$HOME/openprinttag-data`. La caméra absente est signalée par l’interface; adapter le lancement au matériel présent.

Le service d’affichage attend le serveur puis ouvre Firefox en mode kiosque. Il démarre à l’ouverture du bureau via XDG Autostart. L’ouverture automatique de la session graphique relève des réglages du système; ces commandes ne modifient pas LightDM, polkit ou les mots de passe. Le service d’affichage n’est pas à activer sur `default.target`.

Pour un lancement manuel avant activation de HTTPS, après arrêt du service :

```sh
cd "$HOME/apps/openprinttag-station"
.venv/bin/python -m openprinttag_app --mode hardware --camera --lan --data-dir "$HOME/openprinttag-data"
```

## 6. Activer HTTPS et approuver le certificat

Sur le Pi, depuis les sources actives :

```sh
cd "$HOME/apps/openprinttag-station"
python3 deploy/install-https.py --dry-run
sudo python3 deploy/install-https.py
```

Le script prépare la passerelle et relance les services. Conserver l’adresse HTTPS qu’il affiche. Sur chaque autre appareil, ouvrir l’adresse d’aide HTTP annoncée, télécharger le certificat public et suivre la [procédure détaillée](31-https-local.md#reconnaître-le-certificat-sur-un-autre-appareil). Sur Mac, rechercher le **nom interne Caddy** dans **Système → Certificats**, puis approuver **SSL**. Le fichier téléchargé s’appelle **opt-station-root-ca.crt**; son nom diffère de celui affiché dans Trousseaux d’accès.

Sur une station déjà en HTTPS, les réglages et certificats restent en place lors du remplacement des sources. Une réexécution de l’installateur est possible, notamment après un changement d’adresse IP.

## 7. Contrôler et configurer

```sh
systemctl --user status openprinttag.service openprinttag-display.service --no-pager
systemctl status pcscd.socket --no-pager
systemctl status opt-station-https.service --no-pager
journalctl --user -u openprinttag.service -n 60 --no-pager
hostname -I
```

Sur le Pi, ouvrir `https://localhost/`. Sur un autre ordinateur, utiliser l’adresse HTTPS annoncée par l’installateur après approbation du certificat. Dans **Configuration**, vérifier le matériel détecté puis choisir le partage distant et renseigner les appareils. Les noms autorisés et les certificats sont gérés par l’installateur HTTPS; le relancer pour actualiser les adresses plutôt que d’accepter tous les noms.

L’accès complet sans code reste actif jusqu’à modification du partage. Il permet notamment NFC, caméra et suivi PrusaLink depuis les machines du réseau autorisées par ce choix. Les adresses, utilisateurs et secrets se règlent dans **Configuration → Imprimante et caméras**; le test PrusaLink effectue uniquement des lectures. Voir le [guide réseau](18-acces-distant-persistant.md) et le [guide imprimante](17-suivi-imprimante-et-cameras.md).

Les [notifications Chrome](32-notifications-imprimante.md) s’activent ensuite sur chaque navigateur en HTTPS, avec autorisation explicite et bouton de test.

Les fonctions optionnelles se configurent séparément : [MCP](21-serveur-mcp.md), [étiquettes](19-stock-qr-et-etiquettes.md), [sauvegardes](26-sauvegardes-et-restauration.md) et [détection des versions GitHub](27-detection-mises-a-jour.md). Aucune clé externe n’est livrée avec l’application.

## 8. Diagnostiquer le lecteur

Pour une lecture indépendante depuis la session utilisateur du Pi :

```sh
cd "$HOME/apps/openprinttag-station"
systemd-run --user --collect --wait --pipe --unit=openprinttag-reader-check /usr/bin/python3 "$PWD/deploy/check-acr1552.py" --iso15693 --wait-seconds 45 --dump "$HOME/openprinttag-data/diagnostics/tag-$(date +%Y%m%d-%H%M%S).bin"
```

La session locale doit être ouverte. Un client PC/SC lancé directement depuis SSH peut être refusé par la politique du système; diagnostiquer les droits avant de les modifier. Le fichier créé contient les données du tag et reste privé.

Avant une première écriture, utiliser un tag de test vierge et lisible, vérifier son identité et ses protections, puis suivre l’aperçu et la confirmation de l’interface. Une écriture n’est réussie qu’après relecture identique. Les blocs réservés du SLIX2 sont conservés. Les autres tags, lecteurs ou firmwares nécessitent une qualification spécifique; une simulation réussie ne suffit pas.
