# Configuration et apparence

Ouvrir l’onglet Configuration pour les préférences d’affichage, le matériel et les accès.

**Configuration reste accessible depuis le réseau sans code**, y compris en mode Désactivé, pour choisir le thème, consulter le matériel et réactiver le partage depuis le bureau. Les grands bandeaux matériel et réseau ont été retirés des pages; les informations et réglages sont regroupés ici.

## Se déplacer dans les réglages

Le **Sommaire** regroupe les douze rubriques en trois ensembles : **Station**, **Connexions et IA** et **Maintenance**. Cliquer sur une rubrique affiche directement ses réglages, sans recharger la page ni effacer les saisies en cours.

Sur grand écran, le sommaire reste sur le côté pendant le défilement. Sur un écran plus petit, ouvrir le bouton **Sommaire** en haut de la page pour choisir une autre rubrique; il se replie après la sélection. Le sommaire est disponible dans les quatre langues de l’interface, avec tous les niveaux d’accès.

## Choisir le thème

Le thème sombre utilise des surfaces anthracite, du texte clair et des accents orange, inspirés des interfaces Prusa et de [Prusa Connect](https://www.prusa3d.com/p/prusa-connect/). Il s’applique par défaut sur un navigateur sans préférence enregistrée.

Ouvrir **Configuration → Apparence**, puis choisir **Sombre** ou **Clair**. Le bouton soleil/lune de la barre supérieure permet aussi de basculer. Le choix est mémorisé pour ce navigateur; le Mac et l’écran du Pi peuvent utiliser des thèmes différents. Aucun rechargement ni redémarrage n’est nécessaire. Si le navigateur refuse le stockage des préférences, le thème reste appliqué pour la page ouverte.

## Consulter le matériel

Depuis **v0.8.0**, **Apparence → Langue de l’interface** permet aussi de choisir **Français**, **English**, **Español** ou **Deutsch**, sans rechargement ni perte des champs saisis. Le choix est conservé pour le navigateur; voir le [guide des langues](22-langues-interface.md). La carte **Accès des IA · Serveur MCP** regroupe son activation persistante, son adresse et sa fenêtre d’information; voir le [guide MCP](21-serveur-mcp.md).

L’onglet **Configuration** présente :

- Le modèle du lecteur RFID/NFC pris en charge et son état. Son nom PC/SC complet se consulte en dépliant **Identifiant du lecteur**. Un lecteur simulé est identifié comme tel.
- Le modèle du capteur de lecture QR fourni par Picamera2, par exemple **OV5647**. Une absence de caméra et une détection indisponible sont distinguées.

**Actualiser le matériel** relance l’énumération du capteur, sans démarrer de capture. Pendant un scan, la station conserve l’information disponible et attend sa fin pour une nouvelle détection. Détecter un capteur ne prouve pas qu’il transmet des images : cette vérification se fait lors du scan QR.

## Régler les accès distants

Sur le Pi ou depuis une machine du même réseau, ouvrir **Configuration → Accès distant**. Choisir un niveau et cliquer sur **Enregistrer le partage**.

| Niveau | Depuis une autre machine du réseau |
| --- | --- |
| Désactivé | Configuration accessible pour réactiver le partage; stock, modèles et appareils réservés à l’écran local. |
| Inventaire et modèles | Consulter et gérer le stock; créer ou modifier les favoris et modèles. NFC, suivi imprimante et caméras restent locaux. |
| Accès complet sans code | Stock, modèles, NFC, caméra QR, suivi PrusaLink, caméras réseau et réglages des appareils. |

Les modifications s’appliquent immédiatement côté serveur et sont conservées après redémarrage. Le choix est commun au réseau : l’accès complet n’expire plus et ne repose pas sur une session navigateur. Les autres pages actualisent leurs droits à leur prochain contrôle d’état, environ toutes les cinq secondes. Une écriture NFC déjà autorisée termine sa vérification.

Le partage est modifiable depuis le bureau, même lorsqu’il est désactivé. Le stock et les favoris ne sont pas effacés lors d’une désactivation. Voir le [guide d’accès persistant](18-acces-distant-persistant.md).

## Installation et sauvegarde

Depuis le développement **0.7.0.dev1**, la carte **Alimentation du Raspberry Pi** permet aussi d’arrêter ou redémarrer la station avec confirmation, depuis l’écran local ou en accès distant complet. Voir les [droits, contrôles et limites](20-arret-et-redemarrage-pi.md).

Les dépendances et la commande de lancement restent celles du [guide d’installation](12-installation-station-reelle.md). Pour rendre la station joignable, le serveur doit déjà être lancé avec `--lan` : le formulaire ne change pas l’adresse d’écoute du processus. Exemple de lancement manuel, après arrêt d’un éventuel service occupant le même port :

```sh
cd "$HOME/apps/openprinttag-station"
.venv/bin/python -m openprinttag_app --mode hardware --camera --lan --data-dir "$HOME/openprinttag-data"
```

Le niveau choisi est enregistré dans **`network-settings.json`** au format 2 avec permissions `0600`. Inclure ce fichier dans la sauvegarde privée des données avec les bases SQLite et `printer-settings.json`. L’ancien `network-access.json` n’est plus utilisé; le conserver pour un éventuel retour en arrière. Un ancien accès complet protégé par code demande un choix explicite avant son ouverture sans code; voir la [migration](18-acces-distant-persistant.md#installation-et-migration).

En mode désactivé, le serveur reste en écoute pour afficher Configuration et permettre la remise en service depuis le bureau; les routes de données et d’actions sont refusées aux clients distants. Aucun réglage du routeur ni accès Internet n’est ajouté.

## Vérification de l’installation

Les vérifications logicielles et les limites matérielles de la version courante sont détaillées dans le [guide de vérification](08-verification-prototype.md).

Les essais matériels couvrent la détection ACS ACR1552U-M1/OV5647, le choix du thème, le suivi PrusaLink et les vues caméra. La conservation des données lors de la mise à jour a également été vérifiée. Voir le [détail des vérifications](18-acces-distant-persistant.md#vérifications).

## Après une mise à jour de l’interface

Recharger normalement la page sur les autres machines. Les URLs des scripts et du CSS incluent désormais une empreinte de contenu : le navigateur récupère les fichiers correspondant à la page, même si d’anciennes versions sont encore dans son cache. Aucun effacement du stock ni des préférences n’est nécessaire.

Un essai avec l’ancien script gardé en cache a reproduit les trois symptômes signalés : onglet Configuration inactif sans code, thème inactif et matériel restant sur « Vérification… ». Après un rechargement normal de la page corrigée, Configuration et le matériel étaient disponibles sans code, et le choix clair/sombre était conservé au rechargement.

La configuration, le choix du thème et l’affichage du matériel détecté ont également été vérifiés depuis un autre navigateur du réseau après rechargement.
