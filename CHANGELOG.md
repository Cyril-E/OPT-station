# Versions publiques

## v0.19.0 — 31 octobre 2026

- MCP : modification partielle des fiches de bobines, y compris poids et consommation connus, notes et utilisation Stock/Service, avec contrôle des versions et sans écriture RFID.
- Corrections RFID locales conservées lors des relectures et signalées dans l’inventaire; possibilité explicite de reprendre les dernières données observées du tag.
- Modification des modèles et favoris maintenue; catalogue de treize outils, dont six lectures et sept écritures.

Le fonctionnement de l’édition des fiches par MCP est validé par un essai utilisateur. **Vérifications : 751 tests réussis sur Mac**, avec un test réservé à Linux ignoré, et **752 sur Raspberry Pi**. Les corrections et les révisions, les lectures RFID, la sauvegarde/restauration, les conflits et l’affichage français/anglais sont vérifiés sur des données de test; les appels de contrôle sur le stock réel ne changent aucune valeur.

L’archive complète `opt-station-v0.19.0.tar.gz` et son SHA-256 accompagnent cette préversion. Le schéma SQLite reste à **5**. Reconnecter les clients MCP pour découvrir `update_spool`. Les corrections locales ne réécrivent pas le RFID et restent signalées tant qu’elles ne sont pas réconciliées. Pour revenir à une version antérieure, restaurer ensemble les sources et les données sauvegardées avant la mise à jour.

## v0.18.0 — 31 octobre 2026

- Assistant IA : photo couleur avec le Pi ou fichier image, recherche Web facultative, propositions avec preuves et sources avant remplissage d’une nouvelle fiche.
- Configuration de la clé et du modèle OpenAI, clé masquée et incluse dans les sauvegardes de configuration.
- Conservation des inconnues et exclusion des mesures individuelles : tare, poids réel et consommation ne sont pas déduits.
- Sommaire de Configuration : accès direct aux douze rubriques, navigation fixe sur grand écran et menu repliable sur les petits écrans, sans perte des saisies.
- Validation du déclenchement des notifications lors d’une fin d’impression réelle; l’intervention réelle reste à qualifier.
- Suivi des demandes publiques dans les issues GitHub, à consulter avec la feuille de route lors de chaque bilan.

L’assistant est désactivé à la première installation; la clé API se renseigne dans Configuration. Le schéma d’inventaire reste à **5**. L’archive complète `opt-station-v0.18.0.tar.gz` et son SHA-256 accompagnent cette préversion. L’identification depuis une vraie étiquette sous la caméra et l’installation sur carte SD vierge restent à qualifier.

**Vérifications : 719 tests réussis sur Mac**, avec un test réservé à Linux ignoré, et **720 sur Raspberry Pi**; moteurs d’interface IA, langues, notifications et nouveautés vérifiés. Les propositions IA sont testées avec des réponses contrôlées et un essai API sur une étiquette de test. Le sommaire a été vérifié en français/anglais, clair/sombre et aux largeurs 390, 1280 et 1920 pixels.

## v0.17.1 — 31 octobre 2026

- Mot de passe facultatif pour les sauvegardes manuelles et planifiées, avec un choix explicite dans Configuration.
- Téléchargement manuel sans mot de passe par défaut; format compressé avec contrôle d’intégrité et restauration sans saisie de mot de passe.
- Compatibilité des sauvegardes protégées existantes et maintien du choix de protection des anciennes planifications.
- Notes de la dernière version GitHub accessibles dans une fenêtre depuis le bandeau, l’indicateur latéral ou Configuration, y compris en accès Inventaire. Le dernier contenu connu reste disponible en cas de panne réseau.
- Section Nouveautés sur la page principale du projet, avec un résumé des versions et les liens vers leurs publications.

L’archive complète `opt-station-v0.17.1.tar.gz` et son SHA-256 accompagnent cette préversion. Les stations existantes conservent leur inventaire, leurs réglages et leur autorité HTTPS. L’installation complète sur une carte SD vierge reste à qualifier.


## v0.17.0 — 31 octobre 2026

- Installation en une commande sur Raspberry Pi OS 64 bits Trixie : téléchargement public et SHA-256, dépendances, environnement Python, services, HTTPS et plein écran avec ouverture automatique du bureau.
- Options sans écran/sans caméra, choix de release et vérification du téléchargement sans appliquer l’installation.
- Réinstallation conservant données et certificats; sauvegarde cohérente avant activation et tentative de retour arrière en cas d’échec. Les écritures et sauvegardes planifiées attendent la fin de l’installation.
- Contrôle natif du fichier de démarrage avant arrêt de l’application et permissions explicites des dossiers de configuration, indépendantes des permissions restrictives de l’installation.
- Procédure d’installation et distinction entre essais automatisés et qualification d’une station neuve.

**Qualification : 677 tests réussis sur Pi, 676 sur Mac**, avec un test propre à Linux ignoré sur Mac. La réinstallation réelle et le retour arrière sur une station existante sont validés; données, paramètres et certificat sont conservés. HTTPS, le kiosque et l’accès réseau répondent après réinstallation.

L’archive complète `opt-station-v0.17.0.tar.gz` et son SHA-256 accompagnent cette préversion. L’installation complète sur une carte SD vierge reste à qualifier.

## v0.16.1 — 31 octobre 2026

Première distribution publique d’OPT Station.

- Lecture et écriture contrôlée OpenPrintTag NFC-V/SLIX2 avec sauvegarde avant écriture et relecture de vérification.
- Inventaire, états Stock/Service/Terminée, numéros de bobines, notes, favoris et modèles, import/export, QR complets et étiquettes USB.
- Interface française/anglaise, thèmes clair/sombre, configuration du matériel et niveaux de partage réseau persistants.
- PrusaLink en lecture seule, jusqu’à quatre caméras et notifications Chrome de fin d’impression ou d’intervention avec un onglet ouvert en arrière-plan.
- HTTPS local, guide d’approbation des certificats, démarrage en plein écran, arrêt et redémarrage du Pi.
- Douze outils MCP : six lectures d’inventaire et de schéma, six opérations sur la bibliothèque; aucun accès matériel via MCP.
- Sauvegardes chiffrées manuelles/planifiées et détection des nouvelles versions GitHub. Le dépôt public est consultable sans jeton.

**Validation : 628 tests sur Mac et Pi**, plus les moteurs de langue et de notifications. Les profils et limites physiques sont détaillés dans le [guide de vérification](docs/08-verification-prototype.md).

**Mise à jour d’une station existante :** sauvegarder les données, installer les nouvelles sources et conserver le répertoire de données, les services et l’autorité HTTPS. Le schéma SQLite reste à **5**. Les exemples d’installation sont indépendants du compte et du réseau utilisés. Voir le [guide d’installation](docs/12-installation-station-reelle.md).

L’archive complète `opt-station-v0.16.1.tar.gz` et son empreinte SHA-256 accompagnent cette préversion. L’installateur complet en une commande, l’assistant IA et la synchronisation de consommation Prusa Connect ne sont pas encore disponibles; voir les [évolutions techniques](docs/14-feuille-de-route.md).
