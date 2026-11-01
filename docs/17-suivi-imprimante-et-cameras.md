# Suivi imprimante et caméras

Le suivi utilise **PrusaLink en lecture seule**, avec jusqu’à quatre caméras configurables. Il est issu de l’[étude PrusaLink et Prusa Connect](16-etude-api-imprimante.md). Les réglages sont conservés sur la station, distincts des sources du logiciel.

## Configurer PrusaLink

Sur le Pi, ou depuis le réseau après choix de **Configuration → Accès distant → Accès complet sans code**, ouvrir **Configuration → Imprimante et caméras**.

1. Renseigner le nom et l’adresse IP ou le nom réseau de l’imprimante, par exemple `192.0.2.20`. Le préfixe `http://` est ajouté si nécessaire. HTTPS est accepté avec un certificat valide.
2. Choisir **Clé API PrusaLink**, ou **Utilisateur et mot de passe (Digest)** selon les accès affichés par l’imprimante. Ces accès sont distincts de ceux du compte Prusa Connect.
3. Renseigner le secret et cocher **Activer le suivi PrusaLink**.
4. Cliquer sur **Enregistrer et tester PrusaLink**. Le test enregistre les réglages puis lit la version, les informations, l’état et le travail courant. Il n’envoie aucune commande de pause, chauffe ou impression.
5. Ouvrir l’onglet **Imprimante**.

Un champ secret vide conserve la valeur enregistrée. **Effacer le secret enregistré** la retire; désactiver aussi le suivi si aucun nouvel accès ne sera saisi. Après un changement d’adresse, de mode d’authentification ou d’utilisateur, saisir à nouveau le secret : la station ne transfère pas les anciens identifiants vers une nouvelle destination.

Les réglages portent un numéro de révision. Si un autre navigateur les a modifiés, l’enregistrement est refusé : cliquer sur **Recharger les réglages**, puis reprendre les modifications. Le suivi périodique ne remplace pas une saisie en cours.

## Consulter l’impression

L’onglet affiche les informations disponibles : état, nom et aperçu du fichier, progression, temps écoulé, temps restant et heure de fin estimés, températures mesurées et demandées de buse/plateau, vitesse, hauteur Z et firmware. Les champs absents restent inconnus.

L’état est demandé toutes les cinq secondes lorsque l’onglet est visible. Le Pi partage les résultats entre les navigateurs et relit les informations stables moins souvent. Après une panne, il ralentit ses tentatives. La dernière mesure reste affichée avec sa date et **Connexion perdue**; elle ne produit pas une nouvelle heure de fin estimée.

Le suivi utilise uniquement des `GET` vers les routes PrusaLink étudiées. Il ne propose pas encore de commandes imprimante, ne met pas à jour l’inventaire et ne touche pas au lecteur NFC.

## Ajouter jusqu’à quatre caméras

Dans la même section Configuration, cliquer sur **Ajouter une caméra**. Chaque vue possède un nom et une source : **RTSP**, par exemple `rtsp://192.0.2.30/live`, ou une **image JPEG/PNG par HTTP/HTTPS**, éventuellement fournie par un relais existant.

Saisir les identifiants éventuels dans les champs séparés. Choisir **Utilisateur et mot de passe** pour RTSP ou HTTP Basic, ou **Digest (image HTTP)** pour un serveur de snapshots qui le demande. Ne pas mettre le mot de passe dans l’URL.

**Caméra active** détermine si la vue est affichée. **Retirer** enlève sa configuration lors du prochain enregistrement, sans modifier la caméra physique. Quatre configurations sont possibles au total, même si certaines sont désactivées.

Dans **Imprimante**, les images sont renouvelées pendant la consultation. La capture RTSP peut prendre plusieurs secondes : prévoir un renouvellement de cinq à dix secondes selon le matériel. Il s’agit de vues périodiques, sans son, pas d’une vidéo à 25 images/s. Cliquer sur une vue pour l’agrandir. En cas de panne, la dernière image reste visible avec une indication de perte de connexion.

Exemples fictifs de sources, à remplacer par les adresses des caméras :

| Vue | Exemple de source |
| --- | --- |
| Chambre d’impression | `rtsp://192.0.2.30/live` |
| Bobine de filament | `rtsp://192.0.2.31/live` |

Les adresses `192.0.2.x` sont réservées à la documentation et ne sont pas utilisables telles quelles. Ces sources sont indépendantes de la caméra de lecture QR. Deux emplacements supplémentaires sont disponibles dans cet exemple.

### Installer la capture RTSP

En plus des dépendances du [guide d’installation](12-installation-station-reelle.md), installer FFmpeg sur une nouvelle station :

```sh
sudo apt update
sudo apt install --no-install-recommends ffmpeg
ffmpeg -version
```

Vérifier la présence de FFmpeg sur la station avant de configurer une source RTSP. Aucune dépendance Python supplémentaire n’est nécessaire. La capture produit une image de largeur 960 pixels, avec délai borné; les requêtes simultanées partagent la même capture par caméra.

## Complément Prusa Connect

La version `0.25.0` ajoute un collecteur Connect distinct de PrusaLink, désactivé par défaut. Dans **Paramètres → Prusa Connect · Consommations et entrepôt**, il permet de consulter les compteurs des bobines chargées et l’entrepôt, puis d’activer l’actualisation des quantités locales par UUID d’instance. Les identifiants PrusaLink restent distincts.

L’accès utilise l’import d’une session utilisateur dédiée, avec renouvellement facultatif, et les lectures du client web actuel ; ce n’est pas une API tierce stable ni un parcours OAuth enregistré au nom d’OPT Station. Les valeurs sont des compteurs totaux en grammes, jamais une estimation du fichier. La date affichée est celle de leur lecture cloud. La relecture NFC conserve son rôle et les écritures physiques restent explicites.

Voir le [guide Connect et entrepôt](39-prusa-connect-et-entrepot.md) pour la configuration, les conflits, les sauvegardes et les essais réels restant à qualifier. La synchronisation complète des fiches dans les deux sens n’est pas réalisée.

## Accès et sauvegarde

L’onglet Imprimante, les images et les réglages de connexion nécessitent l’accès **local** ou **complet sans code**. Le partage complet est commun au réseau et reste actif jusqu’à modification. Configuration reste accessible pour choisir ce partage depuis le bureau, y compris en mode désactivé; en mode inventaire, elle présente matériel et thème sans les adresses ou réglages des appareils. Voir le [guide d’accès persistant](18-acces-distant-persistant.md).

Le fichier **`printer-settings.json`**, par défaut `$HOME/openprinttag-data/printer-settings.json`, est enregistré atomiquement avec permissions **`0600`**. L’inclure dans les sauvegardes privées avec les bases SQLite et les réglages réseau. Ne pas l’ajouter à Git ou à un rapport. Les secrets ne sont jamais renvoyés par l’API; leur présence est indiquée à un navigateur autorisé.

Les images passent par les routes protégées du Pi; les URLs des appareils ne servent pas de sources d’image dans les pages. Les lectures HTTP ne suivent pas les redirections et les miniatures PrusaLink restent limitées aux chemins de l’imprimante.

## Vérifications

Les vérifications logicielles et les limites matérielles de la version courante sont détaillées dans le [guide de vérification](08-verification-prototype.md).

Les essais matériels couvrent les captures RTSP, leur affichage et leur agrandissement, ainsi que la connexion PrusaLink par clé API sur une **CORE One, firmware 8.0.0+17068**. Le suivi a été validé au repos puis pendant des impressions réelles. Aucune commande de chauffe, pause ou lancement de travail n’est envoyée par ce suivi.

La réponse PrusaLink v1 observée au repos fournit états, températures, axes, vitesse, débit et ventilateurs, sans mesure de poids ou de consommation. Cette observation ne suffit pas à conclure sur les réponses pendant une impression. Le collecteur Connect fournit un suivi distinct : le rapprochement d’une bobine chargée au repos et l’actualisation automatique de sa consommation pendant une impression réelle sont vérifiés. Les valeurs reçues de Connect sont en grammes entiers.
