# Fonctions et évolutions techniques

La dernière version publiée est **[v0.18.0](https://github.com/Cyril-E/OPT-station/releases/tag/v0.18.0)**. Consulter les [notes de version](../CHANGELOG.md) et les [profils vérifiés](08-verification-prototype.md) pour les résultats et limites.

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
- Sauvegardes manuelles/planifiées avec protection par mot de passe facultative et indication des nouvelles versions GitHub avec leurs nouveautés, sans installation automatique de mise à jour.
- Assistant IA par clé API : photo, recherche Web facultative et propositions avec sources à vérifier avant remplissage d’une fiche. Voir le [guide de l’assistant](34-assistant-ia-etiquettes.md).
- Sommaire de Configuration : accès direct aux douze rubriques, menu latéral sur grand écran et repliable sur les petits écrans, sans perte des saisies.

## Suivi des demandes GitHub

À chaque bilan, consulter les [issues ouvertes du projet](https://github.com/Cyril-E/OPT-station/issues?q=is%3Aissue%20is%3Aopen) et leurs derniers commentaires, en complément de cette feuille de route. Les demandes publiques font partie des évolutions à examiner. Vérifier leur état avant d’annoncer qu’un point est terminé.

Demandes ouvertes relevées le 31 octobre 2026; cette liste ne remplace pas une nouvelle consultation :

- [#1 — Filtres d’inventaire Tout / Stock / Production / Terminée](https://github.com/Cyril-E/OPT-station/issues/1).
- [#2 — Photos dans les fiches et modèles, depuis la caméra ou un fichier](https://github.com/Cyril-E/OPT-station/issues/2).
- [#3 — Ordre du menu : Inventaire / Imprimante / Lecture / Écriture / Paramètres](https://github.com/Cyril-E/OPT-station/issues/3).

## Qualification complémentaire de l’installation

- **Installation complète en une commande** : publiée en v0.17.0, avec téléchargement vérifié, préparation Python, sauvegarde/retour arrière, services, plein écran et HTTPS. La réinstallation réelle et le retour arrière sur une station existante sont validés. L’essai complet sur carte SD vierge reste à faire. Voir le [parcours en une commande](33-installation-une-commande.md) ou le [guide manuel](12-installation-station-reelle.md).

## Évolutions à implémenter

- **Connexion ChatGPT de l’assistant IA** : le parcours par clé API est disponible; la connexion OAuth ChatGPT est étudiée et reste à intégrer. Voir le [guide de l’assistant](34-assistant-ia-etiquettes.md).
- **Prusa Connect et consommation** : qualifier les informations et identités réellement exposées par les API avant une synchronisation avec l’inventaire. La préparation actuelle des réglages ne réalise aucune synchronisation.
- **Aperçu QR** : améliorer la taille et la visibilité de l’image existante et qualifier le placement avec une caméra adaptée.
- **Bibliothèque de photos** : enregistrement volontaire des captures et consultation après redémarrage.
- **Interface** : ajustements graphiques ciblés et qualification du tactile selon l’écran utilisé.

## Essais matériels complémentaires

- Notification lors d’une intervention réelle; le déclenchement sur une vraie fin d’impression est validé.
- Identification IA depuis une vraie étiquette photographiée avec la caméra de la station; l’essai API sur une étiquette de test ne qualifie pas ce parcours matériel complet.
- Remplacement physique d’un RFID depuis l’inventaire; le parcours est actuellement vérifié avec un lecteur simulé.
- Exécution nocturne d’une sauvegarde planifiée sur support externe inscriptible; création manuelle sur USB et aperçu de restauration validés.
- Autofocus, QR à courte distance, écran tactile et autres profils matériels.

Les données de bobines ne doivent pas être remplacées par des valeurs supposées. Toute nouvelle intégration doit préserver identité, numéro, dates, notes, consommation connue et protections des tags.
