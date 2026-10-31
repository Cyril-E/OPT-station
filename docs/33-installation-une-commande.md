# Installation en une commande

L’installateur est disponible à partir de la préversion **[v0.17.0](https://github.com/Cyril-E/OPT-station/releases/tag/v0.17.0)**. Il télécharge les sources complètes de la release et vérifie leur SHA-256 avant de demander les droits administrateur. La réinstallation réelle sur une station existante est validée; l’essai complet sur carte SD vierge reste à effectuer. Le [parcours manuel](12-installation-station-reelle.md) décrit les étapes séparées.

## Préparer le Raspberry Pi

1. Avec Raspberry Pi Imager, installer **Raspberry Pi OS 64 bits Trixie avec bureau** sur la carte SD. Le profil matériel de référence est un Raspberry Pi 5.
2. Dans Imager, choisir un nom de machine unique, créer le compte utilisateur et renseigner le Wi-Fi si nécessaire. Pour une installation à distance, activer SSH.
3. Démarrer le Pi, le connecter au réseau et ouvrir un terminal avec ce compte, sur son écran ou en SSH.
4. Brancher les accessoires USB. Les branchements des nappes caméra ou écran se font Pi éteint et alimentation débranchée.

Raspberry Pi OS fournit `curl`, `python3` et `sudo`. L’installation demande une connexion Internet, de l’espace pour les sources et les dépendances, ainsi qu’au moins 1 Gio libre supplémentaire et la place pour deux copies des données existantes. Les autres systèmes et les versions 32 bits sont refusés avant l’installation des paquets. Raspberry Pi OS Lite est pris en charge avec l’option sans écran ci-dessous.

## Lancer l’installation

Exécuter cette commande avec le **compte utilisateur ordinaire**, sans ajouter `sudo` devant :

```sh
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 https://raw.githubusercontent.com/Cyril-E/OPT-station/main/install.sh | bash
```

Le programme demande les droits administrateur dans le terminal quand ils deviennent nécessaires. Saisir le mot de passe du Pi uniquement à cette étape. Aucun compte GitHub, jeton GitHub ni clé API d’imprimante n’est demandé pour installer les sources publiques.

Le programme :

1. Vérifie le Pi, son système et la release. Les préversions publiées sont également prises en compte.
2. Télécharge l’archive complète et son SHA-256, contrôle leur correspondance et refuse les liens ou chemins dangereux dans l’archive.
3. Vérifie les ports et une installation existante. Il refuse d’interrompre une opération matérielle ou de remplacer un service personnalisé non reconnu.
4. Installe les bibliothèques NFC, caméra et étiquettes, puis les dépendances Python verrouillées dans un environnement séparé, sous le compte ordinaire. Le fichier de démarrage est contrôlé par systemd avant l’arrêt de l’application existante.
5. Arrête l’ancienne application, sauvegarde ses données et ses fichiers de lancement, puis active les nouvelles sources.
6. Installe les services de démarrage, Caddy, les certificats HTTPS et le lancement de Firefox en plein écran. Le bureau est configuré pour ouvrir automatiquement la session de ce compte au démarrage.
7. Vérifie le service et HTTPS, puis affiche l’adresse à ouvrir. Il **ne redémarre pas le Pi automatiquement**.

Le partage distant commence en mode **inventaire** sur une station neuve. L’accès complet reste un choix dans Configuration. L’installation n’ouvre aucun port sur le routeur et ne modifie pas SSH.

## Terminer dans Configuration

Sur le Pi, le navigateur utilise `https://localhost/`, avec le certificat local installé et les droits de la station. Si aucun bureau n’était ouvert pendant l’installation, ouvrir la session graphique ou redémarrer le Pi pour lancer le plein écran.

Depuis un autre ordinateur du même réseau, ouvrir l’adresse affichée, par exemple `https://opt-station.local/` en remplaçant ce nom par celui du Pi. Pour l’approbation initiale du certificat, ouvrir `http://opt-station.local/https` et suivre le [guide pas à pas](31-https-local.md). Le certificat apparaît dans le trousseau sous le nom **Caddy Local Authority - AAAA ECC Root**, où AAAA est l’année de création de l’autorité; son nom n’est pas « OPT Station ». Cette approbation reste à faire une fois sur chaque appareil client.

Dans **Configuration**, renseigner les équipements, PrusaLink, les caméras et les clés des fonctions optionnelles. L’installateur ne crée aucune bobine et n’écrit sur aucun tag RFID.

## Options

Sans écran, sur Raspberry Pi OS Lite ou avec un affichage local géré séparément :

```sh
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 https://raw.githubusercontent.com/Cyril-E/OPT-station/main/install.sh | bash -s -- --no-kiosk
```

Ajouter `--no-camera` pour ne pas activer la caméra QR. Sur une station existante, cela désactive son lancement par le service; les réglages enregistrés restent conservés. `--no-kiosk` retire le lancement d’OPT Station au bureau, mais conserve les autres réglages de session du système.

Choisir une version précise :

```sh
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 https://raw.githubusercontent.com/Cyril-E/OPT-station/main/install.sh | bash -s -- --version v0.17.0
```

Contrôler le téléchargement et voir le plan sans installer de paquets, arrêter un service ni modifier les données :

```sh
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 https://raw.githubusercontent.com/Cyril-E/OPT-station/main/install.sh | bash -s -- --dry-run
```

Ce dernier mode vérifie l’archive et affiche un plan préliminaire. Les contrôles complets des services et de l’état matériel ont lieu au lancement réel. Pour lire les scripts avant de les exécuter, consulter [install.sh](../install.sh), [bootstrap.py](../deploy/bootstrap.py) et [install-station.py](../deploy/install-station.py).

## Réinstallation et échec

Relancer la même commande télécharge une copie neuve des sources. Le chemin de données, le mode matériel/simulation et l’activation de la caméra sont conservés depuis le service existant. Les options explicites permettent de désactiver caméra ou kiosque. Le logiciel conserve l’inventaire, les notes, les paramètres, les sauvegardes RFID et l’autorité HTTPS existante. Il n’installe jamais une version antérieure à celle déjà présente.

Les sources restent sous `$HOME/apps/`, avec un lien stable `$HOME/apps/openprinttag-station`. Les données sont indépendantes, par défaut dans `$HOME/openprinttag-data`. Un dossier de sources créé manuellement à la place de ce lien et les surcharges de service inconnues sont signalés plutôt que remplacés.

Avant activation, une sauvegarde privée est placée sous `$HOME/openprinttag-backups/before-install-…`. Elle comprend l’archive des données, le chemin des anciennes sources, les fichiers de configuration sélectionnés et un manifeste avec leurs emplacements et permissions. Ces sauvegardes de l’installateur sont protégées par les droits système et peuvent demander `sudo` pour être consultées; elles ne remplacent pas les sauvegardes chiffrées de l’application.

En cas d’échec d’activation, le programme tente de rétablir les anciens fichiers, les données et les services. Les données de la tentative sont conservées dans un dossier voisin suffixé `.failed-before-install-…`. Les paquets système téléchargés restent installés. L’autorité privée HTTPS n’est ni supprimée ni recréée lors du retour arrière.

Si l’alimentation est coupée ou si le retour arrière est lui-même interrompu, conserver le dossier de sauvegarde et ses fichiers `installation-before.json` et `files/manifest.json` pour la reprise. Ne pas relancer simultanément plusieurs installations et ne pas effacer les anciennes sources avant validation.

## Qualification

Les essais automatisés couvrent le téléchargement, les contrôles d’intégrité, l’extraction, une première installation simulée, la réinstallation avec fichiers et SQLite réels, les conflits de service, les permissions sous une configuration restrictive et le retour arrière après échec. Les commandes de paquets et de services sont simulées dans ces scénarios; un test Linux utilise également le véritable analyseur systemd. Résultats : **677 tests réussis sur Raspberry Pi**, **676 sur Mac**, avec ce seul test Linux ignoré sur Mac.

Une **réinstallation réelle sur une station Raspberry Pi OS Trixie arm64 existante** est validée : environnement Python, activation des services, HTTPS local et distant, Firefox en kiosque, ouverture automatique du bureau, caméra et lecteur NFC détectés. Les données de l’inventaire, les paramètres privés et l’autorité HTTPS sont conservés. Le retour arrière après un refus du fichier de démarrage a également été vérifié, avec conservation des données et rétablissement de la version précédente.

La qualification d’une installation complète sur une **carte SD vierge reste à effectuer** avant de présenter ce parcours comme validé sur une station neuve. Aucun redémarrage supplémentaire, écriture RFID ni impression d’étiquette n’a été effectué pendant la validation de cette réinstallation.

Les contrôles de la passerelle et du certificat restent décrits dans le [guide HTTPS](31-https-local.md). La qualification matérielle NFC, caméra et impression est distincte de l’installation logicielle.

## Préparer une release installable

Pour les mainteneurs : finaliser la même version dans `pyproject.toml` et `openprinttag_app/__init__.py`, exécuter les vérifications, puis enregistrer les sources dans Git. Depuis ce commit :

```sh
python3 deploy/build-release.py --ref HEAD --output dist
```

Le programme construit et revalide une archive plate contenant **tous les fichiers du commit**, puis crée son fichier `.sha256`. Joindre ces deux fichiers `opt-station-vVERSION.tar.gz` et `opt-station-vVERSION.tar.gz.sha256` à une release GitHub dont le tag correspond à la version. Les archives automatiques « Source code » de GitHub ne remplacent pas ces deux assets : leur dossier racine diffère du format attendu.

La commande de construction ne publie rien. Le téléchargement public `install.sh` et `deploy/bootstrap.py` sur `main` doit être disponible avant d’annoncer la commande d’installation. Les répertoires de données, environnements et métadonnées Git locaux restent hors des assets.
