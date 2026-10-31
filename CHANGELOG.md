# Versions publiques

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
