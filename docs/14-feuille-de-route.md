# Fonctions et évolutions techniques

La version courante est **[v0.16.1](https://github.com/Cyril-E/OPT-station/releases/tag/v0.16.1)**. Consulter les [notes de version](../CHANGELOG.md) et les [profils vérifiés](08-verification-prototype.md) pour les résultats et limites.

## Fonctions disponibles

- Lecture et écriture OpenPrintTag NFC-V/SLIX2 : aperçu, sauvegarde avant écriture et contrôle par relecture.
- Inventaire avec numéros uniques, états Stock/Service/Terminée, compteur, notes et date d’entrée.
- QR complets pour les bobines emballées, étiquettes NIIMBOT et création/recréation du RFID depuis une fiche.
- Modèles et favoris, création depuis RFID/QR/inventaire, modification, suppression et import/export.
- Configuration du matériel, langues française/anglaise, thèmes et niveaux d’accès réseau persistants.
- PrusaLink en lecture seule et jusqu’à quatre caméras d’imprimante.
- HTTPS local, aide pour approuver le certificat, démarrage en plein écran et commandes d’alimentation du Pi.
- Notifications Chrome de fin d’impression et d’intervention avec un onglet ouvert en arrière-plan.
- Douze outils MCP pour consulter le stock et le schéma et gérer la bibliothèque, sans accès aux commandes matérielles.
- Sauvegardes chiffrées manuelles/planifiées et indication des nouvelles versions GitHub, sans installation automatique de mise à jour.

## Évolutions à implémenter

- **Installation complète en une commande** : vérifier la plateforme, télécharger et contrôler l’archive, préparer les dépendances, les services et HTTPS, puis afficher l’adresse de Configuration. Le parcours manuel reste celui du [guide d’installation](12-installation-station-reelle.md).
- **Assistant IA pour les étiquettes** : analyser une photo, rechercher la fiche fabricant et proposer des champs sourcés à vérifier. Les valeurs individuelles inconnues restent absentes. Les clés API et les autorisations restent à intégrer dans Configuration.
- **Prusa Connect et consommation** : qualifier les informations et identités réellement exposées par les API avant une synchronisation avec l’inventaire. La préparation actuelle des réglages ne réalise aucune synchronisation.
- **Aperçu QR** : améliorer la taille et la visibilité de l’image existante et qualifier le placement avec une caméra adaptée.
- **Bibliothèque de photos** : enregistrement volontaire des captures et consultation après redémarrage.
- **Interface** : ajustements graphiques ciblés et qualification du tactile selon l’écran utilisé.

## Essais matériels complémentaires

- Notification lors d’une vraie fin d’impression et d’une intervention.
- Remplacement physique d’un RFID depuis l’inventaire; le parcours est actuellement vérifié avec un lecteur simulé.
- Sauvegarde planifiée sur un support externe inscriptible.
- Autofocus, QR à courte distance, écran tactile et autres profils matériels.

Les données de bobines ne doivent pas être remplacées par des valeurs supposées. Toute nouvelle intégration doit préserver identité, numéro, dates, notes, consommation connue et protections des tags.
