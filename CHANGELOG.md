# Versions publiques

## v0.24.0 — 1er novembre 2026

- Création ou recréation d’un RFID depuis l’inventaire sur un tag déjà utilisé, avec choix explicite de réutilisation, aperçu Avant/Après et confirmation du remplacement.
- Sauvegarde avant l’écriture, conservation des protections et de la mémoire réservée, relecture complète avant transfert de l’association RFID.
- Ancienne fiche conservée sans association RFID, avec ses notes, son état, son numéro, son historique et sa consommation; reprise journalisée après interruption sans seconde écriture.

La réutilisation physique d’un ancien tag depuis une fiche d’inventaire est confirmée par un essai utilisateur sur Raspberry Pi. Le journal de la station confirme une opération de réutilisation terminée après écriture et relecture.

Vérifications : **869 tests réussis sur Mac**, avec un test réservé à Linux ignoré, et **870 sur Raspberry Pi**, ainsi que les sept moteurs JavaScript. Les essais couvrent le consentement explicite, les bobines actives ou archivées, les deux versions d’inventaire, les écritures concurrentes, les protections, la mémoire réservée, la sauvegarde préalable et la reprise après interruption sans nouvelle écriture. Le parcours complet et l’annulation de l’accord lors d’une relecture sont vérifiés dans le navigateur sur des données isolées; les contrôles de publication ne réécrivent aucun tag réel.

L’archive complète `opt-station-v0.24.0.tar.gz` et son SHA-256 accompagnent cette préversion. Le schéma SQLite reste à **6** et aucune nouvelle dépendance n’est ajoutée. Voir le [guide RFID](docs/29-creation-et-recreation-rfid-inventaire.md).

## v0.23.0 — 1er novembre 2026

- Ajustement du filament restant depuis les fiches de bobines en stock ou en service, avec aperçu de la consommation recalculée et référence réelle ou nominale explicite.
- Correction optionnelle du poids net initial réel connu, contrôle des valeurs et conflits de version, conservation des saisies et notes, sans écriture RFID implicite ni archivage automatique à zéro.
- QR actualisés lors de leur génération et corrections RFID locales conservées à la relecture, incluses dans les sauvegardes. Interface dans les quatre langues. Voir le [guide du restant](docs/37-ajuster-filament-restant.md).

Vérifications : **831 tests réussis sur Mac**, avec un test réservé à Linux ignoré, et **832 sur Raspberry Pi**, ainsi que les sept moteurs JavaScript. Les essais sur données isolées couvrent les bobines QR/RFID en stock ou en service, les références réelles/nominales/inconnues, les quantités fractionnaires ou nulles, les valeurs invalides, les accès réseau, les conflits, les relectures RFID et la sauvegarde/restauration. La saisie, le recalcul, la conservation des notes et le changement de langue sont vérifiés dans le navigateur; le formulaire est contrôlé sur la station en HTTPS sans modifier son inventaire ni écrire de tag.

L’archive complète `opt-station-v0.23.0.tar.gz` et son SHA-256 accompagnent cette préversion. Le schéma SQLite reste à **6** et aucune nouvelle dépendance n’est ajoutée.

## v0.22.0 — 1er novembre 2026

- Issue #4 : espagnol et allemand ajoutés aux langues de l’interface et de l’aide HTTPS, avec les mêmes messages traduits qu’en anglais.
- Changement de langue immédiat, mémorisé par navigateur et synchronisé entre ses onglets, sans perte des saisies. Formats `es-ES` et `de-DE`, pluriels allemands et langue des propositions IA pris en charge.
- Les données de bobines, notes, identifiants, QR et RFID restent inchangés. Aucune nouvelle dépendance ni migration de base.

Vérifications : **797 tests réussis sur Mac**, avec un test réservé à Linux ignoré, et **798 sur Raspberry Pi**, ainsi que les sept moteurs JavaScript. Les deux nouvelles langues couvrent chacune les 1 621 messages existants. Les quatre choix, le rechargement, les pluriels allemands et la conservation des saisies ont été contrôlés dans le navigateur, y compris sur la station en HTTPS.

L’archive complète `opt-station-v0.22.0.tar.gz` et son SHA-256 accompagnent cette préversion. Le schéma SQLite reste à **6** et aucune nouvelle dépendance n’est ajoutée.

## v0.21.0 — 31 octobre 2026

- Menu réorganisé : Inventaire, Imprimante, Lecture, Écriture, Paramètres; navigation clavier conservée.
- L’inventaire s’ouvre par défaut au chargement et après actualisation de la page.
- Assistant IA : choix explicite entre clé API et connexion ChatGPT, comptes séparés, catalogue de modèles, retour local ou manuel depuis un autre ordinateur, renouvellement et déconnexion.
- Conservation de la clé API et absence de basculement automatique de facturation. Les connexions ChatGPT restent propres à la station et hors des fichiers de sauvegarde portables.
- Reprise d’une connexion ChatGPT en cours après rechargement et maintien du retour pendant les interruptions réseau temporaires.
- Procédure ChatGPT numérotée dans l’interface française/anglaise et la documentation : retour automatique sur le Pi, copie de l’adresse complète sur Mac/PC, distinction avec le courriel OpenAI et vérification du modèle enregistré.

Connexion réelle, autorisation d’utiliser le forfait, récupération du catalogue de modèles et enregistrement du choix vérifiés sur Raspberry Pi. Le menu et l’ouverture par défaut sur Inventaire sont validés. L’analyse d’une étiquette avec l’accès ChatGPT reste à qualifier. Voir le [guide ChatGPT](docs/36-connexion-chatgpt.md).

Vérifications : **789 tests réussis sur Mac**, avec un test réservé à Linux ignoré, et **790 sur Raspberry Pi**, ainsi que les sept moteurs JavaScript. Les tests ChatGPT utilisent des identités signées et réponses contrôlées pour vérifier le retour, la reprise après rechargement, les permissions, le renouvellement, la déconnexion et l’absence de basculement vers les crédits API. Aucune écriture RFID n’est réalisée pour qualifier cette version.

L’archive complète `opt-station-v0.21.0.tar.gz` et son SHA-256 accompagnent cette préversion. Le schéma SQLite reste à **6** et aucune nouvelle dépendance n’est ajoutée. Les sauvegardes portables conservent les réglages et la clé API; les connexions ChatGPT restent propres à leur station et nécessitent une nouvelle autorisation sur une autre installation.

## v0.20.0 — 31 octobre 2026

- Inventaire : vues Tout, Stock, Production et Terminées; choix multiples de marques et matières présents dans les fiches, combinables avec la recherche.
- Photos sur les bobines et les modèles/favoris, import depuis le navigateur ou capture par la caméra du Pi, aperçu avant ajout, vignettes et suppression confirmée.
- Photos incluses dans les sauvegardes d’inventaire; restauration des anciens schémas conservée. Schéma SQLite 6 et limites de sauvegarde 128 Mo / 256 Mo décompressés.

Vérifications : **766 tests réussis sur Mac**, avec un test réservé à Linux ignoré, et **767 sur Raspberry Pi**, ainsi que les six moteurs JavaScript. Les essais couvrent les filtres combinés, l’ajout explicite des photos, les limites de taille et de nombre, les droits réseau, la conservation des fiches, les conflits et la sauvegarde/restauration. L’import depuis le navigateur et l’affichage français/anglais ont été contrôlés sur des données isolées; la capture par la caméra réelle du Pi est vérifiée sans ajout au stock ni écriture RFID.

L’archive complète `opt-station-v0.20.0.tar.gz` et son SHA-256 accompagnent cette préversion. La migration vers le schéma SQLite **6** conserve les fiches existantes. Les photos sont incluses dans les sauvegardes Inventaire et Complète; les anciens schémas 4/5 restent restaurables. Les fichiers JSON d’import/export de modèles n’incluent pas les photos. Avant un retour à une version antérieure, restaurer ensemble les sources et les données sauvegardées avant migration. Voir le [guide des filtres et photos](docs/35-filtres-et-photos.md).

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
