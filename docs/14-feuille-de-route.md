# Fonctions et évolutions techniques

La dernière version publiée est **[v0.24.1](https://github.com/Cyril-E/OPT-station/releases/tag/v0.24.1)**. Consulter les [notes de version](../CHANGELOG.md) et les [profils vérifiés](08-verification-prototype.md) pour les résultats et limites.

## Fonctions disponibles

- Lecture et écriture OpenPrintTag NFC-V/SLIX2 : aperçu, sauvegarde avant écriture et contrôle par relecture.
- Inventaire avec numéros uniques, états Stock/Service/Terminée, compteur, notes et date d’entrée.
- Ajustement du filament restant depuis les fiches en stock ou en service, avec aperçu du recalcul de consommation et référence de poids explicite.
- QR complets pour les bobines emballées, étiquettes NIIMBOT et création/recréation du RFID depuis une fiche.
- Modèles et favoris, création depuis RFID/QR/inventaire, modification, suppression et import/export.
- Configuration du matériel, langues française/anglaise/espagnole/allemande, thèmes et niveaux d’accès réseau persistants.
- PrusaLink en lecture seule et jusqu’à quatre caméras d’imprimante.
- HTTPS local, aide pour approuver le certificat, démarrage en plein écran et commandes d’alimentation du Pi.
- Notifications Chrome de fin d’impression et d’intervention avec un onglet ouvert en arrière-plan.
- Treize outils MCP pour consulter le stock et le schéma, modifier les fiches de bobines existantes et gérer la bibliothèque, sans accès aux commandes matérielles.
- Sauvegardes manuelles/planifiées avec protection par mot de passe facultative et indication des nouvelles versions GitHub avec leurs nouveautés, sans installation automatique de mise à jour.
- Assistant IA par clé API ou compte ChatGPT : photo, recherche Web facultative et propositions avec sources à vérifier avant remplissage d’une fiche. Voir le [guide de l’assistant](34-assistant-ia-etiquettes.md) et la [connexion ChatGPT](36-connexion-chatgpt.md).
- Sommaire de Configuration : accès direct aux douze rubriques, menu latéral sur grand écran et repliable sur les petits écrans, sans perte des saisies.

## Suivi des demandes GitHub

À chaque bilan, consulter les [issues ouvertes du projet](https://github.com/Cyril-E/OPT-station/issues?q=is%3Aissue%20is%3Aopen) et leurs derniers commentaires, en complément de cette feuille de route. Les demandes publiques font partie des évolutions à examiner. Vérifier leur état avant d’annoncer qu’un point est terminé.

Demandes suivies le 1er novembre 2026; cette liste ne remplace pas une nouvelle consultation :

- [#1 — Filtres d’inventaire Tout / Stock / Production / Terminée, et sélections par marque et matière présentes dans le stock](https://github.com/Cyril-E/OPT-station/issues/1).
- [#2 — Photos dans les fiches et modèles, depuis la caméra ou un fichier](https://github.com/Cyril-E/OPT-station/issues/2).
- [#3 — Ordre du menu : Inventaire / Imprimante / Lecture / Écriture / Paramètres](https://github.com/Cyril-E/OPT-station/issues/3).

## Demandes intégrées en v0.20.0

Les demandes #1 et #2 sont implémentées dans **v0.20.0** : vues Tout/Stock/Production/Terminées, sélections multiples de marques et matières, photos jointes aux bobines et aux modèles/favoris, capture ou import, sauvegarde/restauration. Voir le [guide des filtres et photos](35-filtres-et-photos.md). Les issues #1 et #2 ont été fermées après leur livraison et vérification. L’issue #3 est traitée dans **v0.21.0** et a été fermée après contrôle du menu. La demande [#4 — Espagnol et allemand](https://github.com/Cyril-E/OPT-station/issues/4) est intégrée dans **v0.22.0**, après contrôle des quatre langues et de la mémorisation sur le Pi en HTTPS. L’issue est fermée après publication de cette version.

## Ajouts en v0.21.0

La version **v0.21.0** réorganise le menu en Inventaire / Imprimante / Lecture / Écriture / Paramètres, ouvre l’inventaire par défaut et ajoute la [connexion ChatGPT de l’assistant](36-connexion-chatgpt.md), avec choix d’accès explicite, catalogue du compte, retour depuis un autre ordinateur et renouvellement de session. La connexion réelle, l’autorisation du forfait, le catalogue, l’enregistrement du modèle et l’ouverture sur l’inventaire sont vérifiés sur Raspberry Pi. L’analyse d’une étiquette avec l’accès ChatGPT reste à qualifier.

## Ajouts en v0.22.0

- **Issue #4 — Espagnol et allemand** : choix Français / English / Español / Deutsch dans Paramètres et l’aide HTTPS, messages et accessibilité traduits, formats de nombres et dates, explications de l’assistant IA dans la langue choisie. Préférence par navigateur sans rechargement et sans modification des données. Les quatre langues et la conservation des saisies sont vérifiées sur Raspberry Pi et dans un navigateur de test.

## Ajouts en v0.23.0

- **Filament restant** : réglage depuis une fiche en stock ou en service, référence réelle ou nominale explicite, consommation recalculée, conflits et inconnues contrôlés, corrections RFID locales et QR actualisés. Essais sur données isolées et contrôle du formulaire sur une station en HTTPS réalisés sans écriture RFID ni changement de son stock; voir le [guide](37-ajuster-filament-restant.md).

## Ajouts en v0.24.0

- **Réutilisation d’un ancien RFID** : création/recréation depuis une fiche avec confirmation de remplacement, transfert après écriture et relecture, ancienne fiche conservée et reprise sans réécriture après interruption. Réutilisation physique confirmée par un essai utilisateur sur Raspberry Pi; les interruptions restent qualifiées par des essais contrôlés. Voir le [guide RFID](29-creation-et-recreation-rfid-inventaire.md).

## Ajouts en v0.24.1

- Avertissement avant écriture pour les données initiales requises par Prusa, sans remplir automatiquement une mesure inconnue. Voir le [guide](38-suivi-consommation-prusa.md).
- Correction du format des nombres RFID : entiers exacts ou décimaux en simple précision pour les champs écrits, sans migration automatique des tags existants. Sur CORE One, firmware 8.0.0+17068 : chargement sans alerte confirmé par un essai utilisateur, puis augmentation de la consommation après impression réelle vérifiée par relecture physique et actualisation de l’inventaire par NFC.
- Schéma et consignes MCP : exigences Prusa, unités, estimation nominale avec autorisation et conservation des données connues, sans nouvel outil matériel.

## Qualification complémentaire de l’installation

- **Installation complète en une commande** : publiée en v0.17.0, avec téléchargement vérifié, préparation Python, sauvegarde/retour arrière, services, plein écran et HTTPS. La réinstallation réelle et le retour arrière sur une station existante sont validés. L’essai complet sur carte SD vierge reste à faire. Voir le [parcours en une commande](33-installation-une-commande.md) ou le [guide manuel](12-installation-station-reelle.md).

## Ajouts en v0.25.0

- **Prusa Connect et consommation** : collecteur optionnel sur le Pi, réception des compteurs absolus par UUID d’instance, contrôle du poids initial, corrections manuelles prioritaires et conservation de la précision RFID face aux arrondis cloud. Connexion réelle, renouvellement, lectures au repos et actualisations successives pendant une impression vérifiés. Le collecteur travaille même lorsque l’interface est fermée.
- **Envoi vers l’entrepôt** : aperçu depuis une fiche, correction des poids, enregistrement du matériau, contrôle des doublons et relecture dans le catalogue qui alimente l’interface Connect. Transfert réel d’un lot de bobines actives et réparation de fiches invisibles validés, avec conservation des fiches déjà présentes, des données connues et des notes, sans écriture RFID. Voir le [guide Connect](39-prusa-connect-et-entrepot.md).
- **Limites à qualifier séparément** : l’actualisation automatique depuis un lot d’entrepôt distinct reste à vérifier. Les quantités déjà connues suivent un flux Connect → OPT Station ; l’envoi de fiches vers Connect reste explicite. Une synchronisation continue des fiches dans les deux sens est une évolution distincte.

## Pistes reportées après les retours de validation

- **Aperçu QR** : améliorer la taille et la visibilité de l’image existante et qualifier le placement avec une caméra adaptée.
- **Bibliothèque générale de photos** : onglet autonome reporté; les pièces jointes des fiches sont disponibles depuis v0.20.0.
- **Interface** : ajustements graphiques ciblés et qualification du tactile selon l’écran utilisé.

## Validations récentes

- Tag RFID réécrit depuis la station : chargement accepté sans alerte sur CORE One et consommation existante correctement affichée, après correction de l’encodage numérique et avec une longueur initiale renseignée. Après une impression réelle, augmentation du compteur et baisse du restant vérifiées sur le tag, puis inventaire actualisé à la relecture NFC. Identité, données matériau, notes et état conservés; les autres bobines sont inchangées. Le chargement sur l’imprimante est confirmé par un essai utilisateur; l’écriture, la sauvegarde et les relectures sont vérifiées sur la station.

- Notifications Chrome : réception lors d’une demande d’intervention réelle confirmée par un essai utilisateur, en complément de la fin d’impression déjà validée.

- Réutilisation physique d’un ancien tag RFID depuis l’inventaire confirmée par un essai utilisateur. Une opération terminée après écriture et relecture est également présente dans le journal de la station.

- Édition des fiches de bobines et de modèles par MCP confirmée par un essai utilisateur. Les contrôles automatisés sur données isolées couvrent aussi les conflits, la sauvegarde/restauration et les relectures RFID; les appels de contrôle sur le stock réel restent sans changement de valeurs.

- Sauvegarde nocturne planifiée sur support externe : exécution réussie signalée par la station le 1er novembre 2026, en complément de la création manuelle USB et de l’aperçu de restauration déjà validés.

## Essais matériels complémentaires

- Identification IA depuis une vraie étiquette photographiée avec la caméra de la station; l’essai API sur une étiquette de test ne qualifie pas ce parcours matériel complet.
- Autofocus, QR à courte distance, écran tactile et autres profils matériels.

Les données de bobines ne doivent pas être remplacées par des valeurs supposées. Toute nouvelle intégration doit préserver identité, numéro, dates, notes, consommation connue et protections des tags.
