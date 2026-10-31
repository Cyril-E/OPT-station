# Mise en service de la station

Ce document décrit les étapes techniques de mise en service d’OPT Station. Les fonctions livrées et les travaux restant à réaliser sont suivis dans la [feuille de route](14-feuille-de-route.md).

## 1. Préparer la plateforme

Utiliser une installation Raspberry Pi OS 64 bits compatible avec Python 3.11 ou ultérieur. Le profil matériel qualifié utilise un Raspberry Pi 5 et un lecteur ACS ACR1552U-M1 USB. L’écran, la caméra et leurs câbles doivent être compatibles avec le modèle de Pi retenu; voir les fiches [écran](10-ecran-tactile.md) et [caméra](11-camera-qr.md).

Commencer avec le mode simulation pour vérifier l’interface et les données, puis suivre le [guide d’installation matérielle](12-installation-station-reelle.md). Les données simulées et matérielles restent séparées.

## 2. Vérifier le lecteur et les tags

OpenPrintTag MK1 utilise NFC-V/ISO 15693. Un lecteur limité à ISO 14443/NTAG ne convient pas. L’ACS ACR1552U-M1 est le lecteur USB pris en charge par l’adaptateur actuel; la chaîne logicielle utilise PC/SC et CCID. Le modèle ACR122U ne fournit pas le protocole nécessaire à ce profil.

Avant une écriture, vérifier le modèle et le firmware du lecteur, la mémoire du tag, ses protections et la lecture complète de son contenu. Effectuer les premiers essais sur un tag de test réinscriptible. Chaque écriture doit conserver une sauvegarde et être contrôlée par relecture. Les blocs réservés et le compteur du SLIX2 restent préservés.

Une réussite en simulation ne prouve pas la compatibilité d’un matériel. Un lecteur RFID intégré à une imprimante est une intégration distincte de celui de la station.

## 3. Vérifier les parcours métier

- Lire une bobine et l’ajouter explicitement à l’inventaire.
- Recevoir une bobine emballée depuis un QR, un modèle ou une saisie manuelle.
- Créer une étiquette complète, retrouver la même fiche et préparer son RFID.
- Modifier un tag existant en conservant son identité et les valeurs non modifiées.
- Relire une consommation mise à jour ailleurs, sans réécrire automatiquement un ancien état de l’inventaire.
- Réutiliser les caractéristiques d’un modèle tout en attribuant une identité et un numéro distincts à chaque nouvelle bobine.

Les valeurs inconnues restent inconnues. Un poids nominal n’est pas une pesée réelle; la tare et la consommation doivent être renseignées ou mesurées séparément. Les [règles fonctionnelles](05-cahier-des-charges.md) détaillent ces distinctions.

## 4. Configurer les accès et périphériques

Dans Configuration, renseigner uniquement les équipements présents : imprimante PrusaLink, caméras réseau, imprimante d’étiquettes, destination des sauvegardes et éventuel accès GitHub privé. Les clés et mots de passe restent sur la station.

Le partage local distingue les modes Désactivé, Inventaire et modèles, et Accès complet sans code. Le suivi PrusaLink est en lecture seule. La synchronisation de consommation cloud et les autres fonctions non livrées restent indiquées comme telles dans la feuille de route.

## 5. Activer les fonctions optionnelles

HTTPS et les notifications sont disponibles; suivre les guides [HTTPS](31-https-local.md) et [notifications](32-notifications-imprimante.md). La bibliothèque et le stock peuvent aussi être consultés par le [MCP](21-serveur-mcp.md), désactivé par défaut.

L’installateur complet en une commande, l’assistant IA et la consommation via Prusa Connect restent à intégrer. Les capacités disponibles et les travaux techniques sont précisés dans la [feuille de route](14-feuille-de-route.md).
