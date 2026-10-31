# OPT Station — lecteur-écrivain et inventaire de bobines

**OPT Station** lit et écrit le format NFC **OpenPrintTag** et conserve un inventaire local de bobines. L’interface web est disponible en français et en anglais, avec thèmes clair et sombre.

## Fonctions

- Lecture, préparation, écriture NFC et vérification par relecture, avec sauvegarde du contenu précédent.
- Réception de bobines par QR, fiche produit prise en charge, modèle ou saisie manuelle.
- Numéros uniques B0000, B0001…, date d’entrée, notes et recherche dans l’inventaire.
- États **En stock / En service** indépendants de l’identification QR/RFID, archives et compteur de bobines terminées.
- Création et recréation du RFID depuis une fiche d’inventaire; modèles réutilisables depuis l’inventaire, un tag ou un QR.
- Favoris et modèles modifiables, import/export, étiquettes QR et impression USB NIIMBOT.
- Suivi PrusaLink en lecture seule et jusqu’à quatre caméras réseau.
- Accès réseau configurable, serveur MCP optionnel, sauvegardes chiffrées manuelles et planifiées.
- Détection des versions GitHub disponibles, affichage local en plein écran et commandes d’arrêt/redémarrage du Pi.

Une valeur inconnue reste inconnue. Le poids nominal, le poids réellement mesuré, la tare et la consommation sont des informations distinctes. Les modèles ne copient pas les données individuelles d’une bobine.

## Version et état du projet

Dernière préversion : **[v0.16.1](https://github.com/Cyril-E/OPT-station/releases/tag/v0.16.1)**, avec notifications Chrome de fin d’impression et d’intervention, actives lorsqu’un onglet reste ouvert en arrière-plan. Elle fournit les sources complètes et leur empreinte SHA-256. Le [dépôt du projet](https://github.com/Cyril-E/OPT-station) est public. Les téléchargements de cette version ne nécessitent pas de compte ni de jeton GitHub.

La qualification de v0.16.1 comprend **628 tests sur Mac et Raspberry Pi**, dont le flux d’événements réel et la passerelle HTTPS Caddy, ainsi que les moteurs de langue et de notifications. L’affichage d’une notification de test dans Chrome sur Mac est validé. Les événements sur une impression réelle restent à qualifier; voir le [guide des notifications](docs/32-notifications-imprimante.md) et le [journal des versions](CHANGELOG.md).

La [procédure HTTPS](docs/31-https-local.md) installe des certificats propres à chaque station et une aide bilingue. L’installation complète en une commande et l’identification d’étiquettes par IA restent en préparation. Aucun installateur `curl … | bash` n’est encore publié comme fonction opérationnelle. La [feuille de route](docs/14-feuille-de-route.md) distingue les fonctions livrées et les travaux à réaliser.

La version comprend les [notifications Chrome](docs/32-notifications-imprimante.md) de fin d’impression et d’intervention, avec un onglet ouvert en arrière-plan et des réglages propres à chaque navigateur.

## Installer et configurer

Le profil matériel de référence utilise **Raspberry Pi 5**, Raspberry Pi OS 64 bits, **ACS ACR1552U-M1** et tags NFC-V/ISO 15693 **SLIX2**. La capture QR a été qualifiée avec un capteur OV5647. Les autres capteurs, écrans et lecteurs doivent être vérifiés sur le système retenu. Le [guide écran](docs/10-ecran-tactile.md) précise les limites du Touch Display 2 de 10,1 pouces.

Suivre le **[guide d’installation matérielle](docs/12-installation-station-reelle.md)** pour les paquets, les sources, l’environnement Python, les services et le navigateur en plein écran. Les adresses des appareils et leurs identifiants se renseignent ensuite dans **Configuration**. Les chemins reposent sur le compte qui installe la station; aucun compte ou adressage réseau particulier n’est requis.

Depuis un autre ordinateur, utiliser l’adresse annoncée au lancement de la station. Dans **Configuration → Accès distant**, choisir **Désactivé**, **Inventaire et modèles** ou **Accès complet sans code**. Le choix est persistant et commun aux clients du réseau. Voir le [guide d’accès](docs/18-acces-distant-persistant.md).

Les exemples d’installation et de réseau sont fictifs; les fixtures officielles restent identifiées par leur source publique. Les adresses `192.0.2.x` sont réservées à la documentation et ne désignent pas des équipements à joindre; les remplacer par l’adresse ou le nom réel de l’appareil. Les mots de passe, clés, captures privées, inventaires et images de tags restent hors du dépôt.

## Essayer le mode simulation

Avec Python 3.11 ou ultérieur et les dépendances du projet installées dans `.venv` :

```sh
.venv/bin/python -m openprinttag_app
```

Ouvrir [http://127.0.0.1:8765](http://127.0.0.1:8765). **Configuration → Matériel détecté** indique la simulation. Les tags et écritures sont virtuels; la base d’essai est distincte de l’inventaire matériel. Voir le [guide de développement et des premiers essais](docs/09-deploiement-raspberry-pi.md).

## Guides

- [Périmètre fonctionnel](docs/05-cahier-des-charges.md), [mode d’emploi](docs/06-mode-emploi.md) et [architecture](docs/07-architecture.md).
- [Configuration et apparence](docs/15-configuration-et-apparence.md), [langues](docs/22-langues-interface.md) et [accès réseau](docs/13-acces-reseau.md).
- [Suivi PrusaLink et caméras](docs/17-suivi-imprimante-et-cameras.md), avec [étude des API](docs/16-etude-api-imprimante.md).
- [Réception, QR et étiquettes](docs/19-stock-qr-et-etiquettes.md), [numéros et notes](docs/24-numeros-et-notes-inventaire.md), [archives](docs/23-bobines-terminees-et-archives.md).
- [Modèles depuis RFID/QR](docs/28-modeles-depuis-rfid-et-qr.md), [états et modèles depuis l’inventaire](docs/30-utilisation-et-modeles-inventaire.md), [création et recréation RFID](docs/29-creation-et-recreation-rfid-inventaire.md).
- [Import/export de bibliothèque](docs/25-import-export-bibliotheque.md), [sauvegardes et restauration](docs/26-sauvegardes-et-restauration.md), [mises à jour](docs/27-detection-mises-a-jour.md).
- [Serveur MCP](docs/21-serveur-mcp.md), [HTTPS local](docs/31-https-local.md) et [alimentation du Pi](docs/20-arret-et-redemarrage-pi.md).

## Format et sources

Le codec utilise une copie gelée de la spécification officielle OpenPrintTag et un catalogue local. Les données de référence et leurs licences sont indiquées dans [Sources et provenance](docs/04-sources-et-provenance.md), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) et [references/README.md](references/README.md).

Les références tierces conservent leurs notices. Les exemples et fichiers distribués ont été vérifiés avant publication; voir les [règles de distribution et de stockage des données](docs/03-contexte-et-publication.md).
