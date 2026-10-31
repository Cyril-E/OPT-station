# Versions publiques

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
