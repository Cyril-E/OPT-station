# OPT Station — lecteur-écrivain et inventaire de bobines

**OPT Station** lit et écrit le format NFC **OpenPrintTag** et conserve un inventaire local de bobines. L’interface web est disponible en français, anglais, espagnol et allemand, avec thèmes clair et sombre.

## Fonctions

- Lecture, préparation, écriture NFC et vérification par relecture, avec sauvegarde du contenu précédent.
- Réception de bobines par QR, fiche produit prise en charge, modèle ou saisie manuelle.
- Numéros uniques B0000, B0001…, date d’entrée, notes et recherche dans l’inventaire.
- États **En stock / En service** indépendants de l’identification QR/RFID, archives et compteur de bobines terminées.
- Ajustement du filament restant depuis une fiche de bobine, avec aperçu de la consommation recalculée et référence de poids explicite.
- Création et recréation du RFID depuis une fiche d’inventaire, avec réutilisation confirmée d’un ancien tag; modèles réutilisables depuis l’inventaire, un tag ou un QR.
- Favoris et modèles modifiables, import/export, étiquettes QR et impression USB NIIMBOT.
- Suivi PrusaLink en lecture seule et jusqu’à quatre caméras réseau.
- Suivi de consommation Prusa Connect par identité de bobine, actualisation de l’inventaire et envoi explicite vers l’entrepôt avec contrôle des doublons.
- Assistant IA par clé API ou compte ChatGPT depuis une photo d’étiquette, avec recherche Web facultative et validation des propositions avant remplissage.
- Sommaire de Configuration avec accès direct aux réglages et navigation adaptée à l’écran.
- Accès réseau configurable et serveur MCP optionnel : treize outils pour consulter et corriger les fiches de bobines, et gérer les favoris et modèles.
- Filtres d’inventaire par état, marque et matière; photos des bobines et modèles depuis un fichier ou la caméra du Pi.
- Sauvegardes manuelles et planifiées avec mot de passe facultatif, incluant les photos des fiches.
- Détection des versions GitHub disponibles, affichage local en plein écran et commandes d’arrêt/redémarrage du Pi.

Une valeur inconnue reste inconnue. Le poids nominal, le poids réellement mesuré, la tare et la consommation sont des informations distinctes. Les modèles ne copient pas les données individuelles d’une bobine.

## Version et état du projet

Dernière préversion : **[v0.25.1](https://github.com/Cyril-E/OPT-station/releases/tag/v0.25.1)**, avec une icône indiquant les bobines présentes dans l’entrepôt Prusa Connect, en complément du suivi de consommation et de l’envoi des bobines. L’interface est disponible en français, anglais, espagnol et allemand. L’installation en une commande sur Raspberry Pi OS 64 bits Trixie comprend les dépendances, les services, HTTPS et le démarrage en plein écran. La publication fournit les sources complètes et leur empreinte SHA-256. Le [dépôt du projet](https://github.com/Cyril-E/OPT-station) est public. Les téléchargements ne nécessitent pas de compte ni de jeton GitHub.

La qualification comprend les sauvegardes et restaurations avec ou sans mot de passe, les notes de version et leur cache, ainsi que les moteurs de langue et de notifications. La réinstallation réelle, le retour arrière, HTTPS et le kiosque sont validés sur une station existante. L’installation complète sur carte SD vierge reste à qualifier. Voir le [guide d’installation](docs/33-installation-une-commande.md) et le [journal des versions](CHANGELOG.md).

La [procédure HTTPS](docs/31-https-local.md) installe des certificats propres à chaque station et une aide dans les quatre langues de l’interface. L’[installateur](docs/33-installation-une-commande.md) conserve l’inventaire et les certificats sur une station existante, sauvegarde les fichiers avant activation et tente un retour arrière en cas d’échec. L’[assistant IA](docs/34-assistant-ia-etiquettes.md) est optionnel : choisir une clé API ou connecter un compte ChatGPT dans Paramètres. La [feuille de route](docs/14-feuille-de-route.md) et les [issues GitHub](https://github.com/Cyril-E/OPT-station/issues) regroupent les validations et évolutions suivies.

La version comprend les [notifications Chrome](docs/32-notifications-imprimante.md) de fin d’impression et d’intervention, avec un onglet ouvert en arrière-plan et des réglages propres à chaque navigateur.

## Nouveautés

### [v0.25.1 — Présence dans l’entrepôt Prusa Connect](https://github.com/Cyril-E/OPT-station/releases/tag/v0.25.1)

- Petit nuage coché à côté du numéro de bobine : vert si sa présence dans l’entrepôt est confirmée, orange si elle doit être revérifiée. La date du dernier contrôle s’affiche au survol.
- Repère disponible aussi en accès Inventaire, dans les quatre langues et les deux thèmes, à partir des lectures déjà effectuées par le Pi. Il indique une présence ; l’envoi des modifications de fiche reste explicite. Voir le [guide Connect](docs/39-prusa-connect-et-entrepot.md).

### [v0.25.0 — Consommation Prusa Connect et entrepôt](https://github.com/Cyril-E/OPT-station/releases/tag/v0.25.0)

- Actualisation optionnelle de la consommation de la bobine chargée et des quantités connues dans l’entrepôt, avec rapprochement exact par UUID, priorité aux corrections manuelles et conservation de la précision RFID. Le collecteur travaille sur le Pi même lorsque l’interface est fermée.
- Depuis une fiche d’inventaire, **Envoyer vers Prusa Connect** : aperçu, correction des poids si nécessaire, contrôle des doublons, identité conservée et vérification dans le catalogue de l’entrepôt. Les fiches déjà présentes sont conservées ; une reprise après interruption ne recrée pas la bobine.
- Accès et renouvellement de session dans **Paramètres → Prusa Connect · Consommations et entrepôt**. L’intégration utilise le client web Connect actuel et une session dédiée ; l’envoi reste explicite, sans synchronisation bidirectionnelle des fiches ni écriture RFID. Voir le [guide Connect](docs/39-prusa-connect-et-entrepot.md).

### [v0.24.1 — Compatibilité RFID et consommation Prusa](https://github.com/Cyril-E/OPT-station/releases/tag/v0.24.1)

- L’aperçu d’écriture avertit lorsque la masse ou la longueur initiale manque, sans inventer de mesure ni remettre à zéro la consommation. Voir le [guide Prusa](docs/38-suivi-consommation-prusa.md).
- Les nombres écrits sur RFID utilisent des entiers ou la simple précision compatible avec le lecteur Prusa publié. Chargement sans alerte, consommation après impression et inventaire actualisé à la relecture NFC vérifiés sur CORE One, firmware 8.0.0+17068.
- Le MCP expose les exigences de suivi et les unités pour préparer les prochaines fiches; une longueur estimée reste nominale et les consommations connues sont conservées.

### [v0.24.0 — Réutiliser un tag RFID](https://github.com/Cyril-E/OPT-station/releases/tag/v0.24.0)

- Depuis une fiche de bobine, possibilité explicite de remplacer le contenu d’un ancien tag, avec sauvegarde et relecture avant association. La fiche précédemment liée au tag est conservée. Voir le [guide RFID](docs/29-creation-et-recreation-rfid-inventaire.md).

### [v0.23.0 — Ajustement du filament restant](https://github.com/Cyril-E/OPT-station/releases/tag/v0.23.0)

- Dans une fiche de bobine en stock ou en service, saisir le poids du filament restant et vérifier la consommation recalculée avant enregistrement. Le tag RFID s’actualise séparément. Voir le [guide](docs/37-ajuster-filament-restant.md).

### [v0.22.0 — Espagnol et allemand](https://github.com/Cyril-E/OPT-station/releases/tag/v0.22.0)

- Choix **Français / English / Español / Deutsch** dans **Paramètres → Apparence**, également disponible dans l’aide HTTPS.
- Messages, confirmations, formats des dates et nombres et explications IA dans la langue choisie, avec conservation des saisies et des données des bobines. Voir le [guide des langues](docs/22-langues-interface.md).

### [v0.21.0 — Connexion ChatGPT et accueil Inventaire](https://github.com/Cyril-E/OPT-station/releases/tag/v0.21.0)

- Assistant IA : choix explicite entre clé API et compte ChatGPT, modèles proposés par le compte connecté, renouvellement et déconnexion. Une limite du forfait ne bascule pas automatiquement vers les crédits API.
- [Connexion ChatGPT pas à pas](docs/36-connexion-chatgpt.md) dans l’interface française/anglaise et la documentation : retour automatique sur le Pi, copie de l’adresse complète sur Mac/PC et reprise après rechargement.
- Menu **Inventaire / Imprimante / Lecture / Écriture / Paramètres**, avec ouverture sur **Inventaire** à chaque chargement et actualisation.

### [v0.20.0 — Filtres d’inventaire et photos](https://github.com/Cyril-E/OPT-station/releases/tag/v0.20.0)

- Vues **Tout / Stock / Production / Terminées**, avec plusieurs marques et matières cochables, combinables avec la recherche par numéro ou texte.
- [Photos des bobines et modèles](docs/35-filtres-et-photos.md) : import depuis l’ordinateur ou capture par la caméra du Pi, aperçu avant ajout, vignettes, consultation et suppression confirmée. Jusqu’à huit photos par fiche.
- Photos incluses dans les sauvegardes Inventaire et Complète, avec restauration des anciens fichiers conservée. Schéma SQLite 6; limites de sauvegarde de 128 Mo pour le fichier et 256 Mo décompressés. Les photos restent hors des QR et des tags RFID.

### [v0.19.0 — Édition des bobines par MCP](https://github.com/Cyril-E/OPT-station/releases/tag/v0.19.0)

- Correction des informations produit, poids connus, consommation, notes et état Stock/Service d’une bobine existante par MCP, avec contrôle des versions et conservation de son identité.
- Corrections locales RFID signalées dans l’inventaire, conservées lors des relectures et incluses dans les sauvegardes. L’écriture du tag reste une action distincte.
- Catalogue de treize outils; la modification des modèles et favoris reste disponible. Reconnecter le client MCP pour découvrir `update_spool`.

### [v0.18.0 — Assistant IA et sommaire de Configuration](https://github.com/Cyril-E/OPT-station/releases/tag/v0.18.0)

- [Assistant IA pour les étiquettes](docs/34-assistant-ia-etiquettes.md) : photo avec le Pi ou fichier image, recherche Web facultative et propositions avec sources à vérifier avant remplissage. La clé API reste dans les réglages privés; les mesures individuelles inconnues ne sont pas inventées.
- [Sommaire de Configuration](docs/15-configuration-et-apparence.md#se-déplacer-dans-les-réglages) : accès direct aux douze rubriques, navigation visible sur grand écran et repliable sur petit écran, sans perte des saisies.
- Notification de fin d’impression validée en conditions réelles. Les [issues publiques](https://github.com/Cyril-E/OPT-station/issues) complètent la feuille de route pour le suivi des demandes.

### [v0.17.1 — Sauvegardes et notes de version](https://github.com/Cyril-E/OPT-station/releases/tag/v0.17.1)

- Mot de passe facultatif pour les sauvegardes manuelles et planifiées. Le téléchargement manuel est sans mot de passe par défaut; les anciennes sauvegardes protégées restent restaurables.
- Nouveautés de la dernière version consultables directement depuis l’indicateur de mise à jour et dans Configuration, à partir des notes publiées sur GitHub.

### [v0.17.0 — Installation en une commande](https://github.com/Cyril-E/OPT-station/releases/tag/v0.17.0)

- Installation des dépendances, services, HTTPS et affichage plein écran avec une seule commande; options sans écran ou caméra et réinstallation préservant les données et certificats.

### [v0.16.1 — Première distribution publique](https://github.com/Cyril-E/OPT-station/releases/tag/v0.16.1)

- Lecture et écriture NFC, inventaire, QR et étiquettes, modèles et favoris, PrusaLink et caméras, notifications Chrome, MCP et interface française/anglaise/espagnole/allemande.

Cette section présente les ajouts de chaque version, de la plus récente à la plus ancienne. Le [journal complet](CHANGELOG.md) et les [publications GitHub](https://github.com/Cyril-E/OPT-station/releases) détaillent les changements et les conditions de validation.

## Installer et configurer

Le profil matériel de référence utilise **Raspberry Pi 5**, Raspberry Pi OS 64 bits, **ACS ACR1552U-M1** et tags NFC-V/ISO 15693 **SLIX2**. La capture QR a été qualifiée avec un capteur OV5647. Les autres capteurs, écrans et lecteurs doivent être vérifiés sur le système retenu. Le [guide écran](docs/10-ecran-tactile.md) précise les limites du Touch Display 2 de 10,1 pouces.

Sur **Raspberry Pi OS 64 bits Trixie avec bureau**, ouvrir un terminal avec le compte ordinaire du Pi et exécuter, sans ajouter `sudo` devant :

```sh
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 https://raw.githubusercontent.com/Cyril-E/OPT-station/main/install.sh | bash
```

Le mot de passe administrateur est demandé dans le terminal quand il devient nécessaire. Après installation, ouvrir l’adresse affichée et renseigner les appareils et leurs clés dans **Configuration**. Sur chaque autre ordinateur, approuver une fois le certificat selon l’[aide HTTPS](docs/31-https-local.md). Les chemins reposent sur le compte qui installe la station; aucun compte ou adressage réseau particulier n’est requis.

Consulter le **[guide d’installation en une commande](docs/33-installation-une-commande.md)** pour le parcours complet, les réinstallations et les options `--no-kiosk`, `--no-camera`, `--version` et `--dry-run`. Raspberry Pi OS Lite demande `--no-kiosk`. Le **[guide manuel](docs/12-installation-station-reelle.md)** décrit les étapes séparées.

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
- [Prusa Connect et entrepôt](docs/39-prusa-connect-et-entrepot.md) : configuration de la session dédiée, réception des consommations par UUID et envoi explicite des bobines, disponibles depuis v0.25.0.
- [Modèles depuis RFID/QR](docs/28-modeles-depuis-rfid-et-qr.md), [états et modèles depuis l’inventaire](docs/30-utilisation-et-modeles-inventaire.md), [création et recréation RFID](docs/29-creation-et-recreation-rfid-inventaire.md).
- [Filtres et photos des fiches](docs/35-filtres-et-photos.md).
- [Import/export de bibliothèque](docs/25-import-export-bibliotheque.md), [sauvegardes et restauration](docs/26-sauvegardes-et-restauration.md), [mises à jour](docs/27-detection-mises-a-jour.md).
- [Serveur MCP](docs/21-serveur-mcp.md), [HTTPS local](docs/31-https-local.md) et [alimentation du Pi](docs/20-arret-et-redemarrage-pi.md).
- [Assistant IA pour les étiquettes](docs/34-assistant-ia-etiquettes.md), [connexion ChatGPT pas à pas](docs/36-connexion-chatgpt.md) et [fonctions et évolutions](docs/14-feuille-de-route.md).

## Format et sources

Le codec utilise une copie gelée de la spécification officielle OpenPrintTag et un catalogue local. Les données de référence et leurs licences sont indiquées dans [Sources et provenance](docs/04-sources-et-provenance.md), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) et [references/README.md](references/README.md).

Les références tierces conservent leurs notices. Les exemples et fichiers distribués ont été vérifiés avant publication; voir les [règles de distribution et de stockage des données](docs/03-contexte-et-publication.md).
