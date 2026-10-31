# Numéros de bobines et notes d’inventaire

Chaque bobine possède un numéro unique et des notes; un carnet commun complète l’inventaire.

## Repérer une bobine par son numéro

Chaque bobine reçoit automatiquement un numéro à sa première entrée en stock : **B0000**, **B0001**, **B0002**, etc. Le numéro est visible dans l’inventaire, sa fiche, les lectures d’un tag déjà en stock et les étiquettes générées. La recherche accepte le numéro, sans distinction de majuscules, y compris une saisie courte comme `b42` pour `B0042`. Elle porte sur la vue choisie, stock actif ou archives. Les consultations MCP retournent également `spool_number` et permettent de retrouver une fiche par ce numéro.

Noter simplement **B0042** au feutre sur l’emballage suffit pour retrouver la bobine dans cette station. À l’ouverture, rechercher son numéro, ouvrir sa fiche et cliquer sur **Créer le tag RFID**. Les données sont chargées directement depuis l’inventaire : présenter un tag vierge, le relire, vérifier les données et confirmer l’écriture. La relecture du tag et son association à la fiche restent obligatoires. Aucune impression ni lecture QR n’est nécessaire pour ce parcours. Depuis **v0.13.0**, une bobine déjà associée propose **Recréer le tag RFID** dans la même fiche; voir le [guide de remplacement](29-creation-et-recreation-rfid-inventaire.md).

La séquence est commune aux clients de la station et protégée contre les créations simultanées. Les modèles et favoris ne consomment pas de numéro. Une création échouée ne fait pas avancer le compteur. Une relecture ou un retour au stock conserve le numéro d’origine; les bobines retirées ou terminées gardent leur numéro. Il n’est jamais réattribué. Après B9999, la séquence continue à B10000, sans retour à zéro. Ce compteur est distinct du nombre de bobines consommées.

Les bobines déjà enregistrées reçoivent leurs numéros lors de la migration, dans l’ordre des dates d’entrée connues, puis des identifiants pour les dates inconnues ou égales. Les anciennes dates restent inchangées, y compris celles qui sont inconnues. Le numéro concerne la station; l’UUID d’instance continue d’assurer l’identité logique de la bobine et l’UID reste celui du tag physique.

## Carnet commun et notes par bobine

Dans **Inventaire → Carnet commun de l’inventaire**, saisir des références de tares, poids de bobines vides ou remarques utiles, puis cliquer sur **Enregistrer les notes**. Ce carnet convient par exemple à une liste de tares par marque ou type de contenant.

Dans le détail d’une bobine, la zone **Notes de cette bobine** permet de noter ses particularités. Les notes restent consultables et modifiables une fois la bobine archivée. Elles suivent la fiche lors des lectures, corrections, changements de tag et retours en stock. Une modification de note ne change ni la consommation, ni les données du tag, ni l’état du stock.

Chaque zone accepte jusqu’à **16 000 caractères**, retours à la ligne compris. Indiquer si un poids est mesuré ou seulement indicatif, et distinguer la **tare du contenant vide** du **poids de filament** ou du poids total pesé. Aucune quantité n’est déduite automatiquement d’un texte libre.

Les notes sont conservées sur le Pi après redémarrage et partagées entre les navigateurs autorisés. En cas de modification concurrente, l’enregistrement est refusé et la saisie locale reste visible. Le bouton **Recharger les notes** remplace la saisie par la dernière version enregistrée : copier d’abord les passages à conserver si une fusion manuelle est nécessaire. Une actualisation de l’état de la station ou un changement de langue conserve les brouillons.

## Consultation par les IA

Le MCP comporte désormais **douze outils : six en lecture et six d’écriture de bibliothèque**. Actualiser le catalogue ou reconnecter le client pour découvrir **`get_inventory_notes`**.

- `get_inventory_notes` retourne le carnet commun sous la forme `text`, `revision`, `updated_at`.
- `list_inventory` retourne `spool_number`, `notes`, `notes_revision` et `notes_updated_at` pour chaque fiche. Sa recherche inclut le numéro et les notes de bobine.
- `get_spool` accepte l’identifiant d’inventaire ou le numéro lisible, par exemple `B0042`, et retourne ces mêmes informations.

Les notes restent **en lecture seule via MCP**. Les six outils d’écriture concernent les favoris et modèles; aucun outil n’écrit une note, un tag ou une consommation. Une IA peut utiliser les références connues pour proposer ou compléter un modèle, en respectant le schéma et la version de cette fiche. Le texte des notes est une donnée utilisateur, pas une instruction à exécuter. Une valeur indiquée comme approximative ne devient pas une mesure certifiée.

Le carnet et les notes personnelles sont accessibles dans les modes distant **Inventaire et modèles** et **Complet**; le mode **Désactivé** en refuse l’accès distant. L’écriture RFID nécessite toujours l’accès local ou complet. Le réglage d’activation du MCP est conservé lors de l’installation.

## Données, étiquettes et sauvegarde

La migration transactionnelle SQLite **3 → 4** ajoute le numéro entier unique, les notes et leur révision propre à chaque bobine, le carnet commun et le prochain numéro à attribuer. Le numéro est immuable. L’allocation et l’insertion se font dans une même transaction. Les anciennes données Main/Aux, UUID, UID, états, dates, versions et modèles restent inchangés. Les notes utilisent une révision distincte : une lecture NFC ne provoque pas de faux conflit et une note modifiée pendant une préparation RFID est conservée après association.

Le QR `OPT1` conserve son format et l’ensemble des données RFID. Les nouveaux numéros et notes sont des données d’inventaire; ils ne remplacent aucun champ OpenPrintTag. Le numéro est imprimé en clair sur la nouvelle étiquette, sans empiéter sur le QR. Sur un format étroit, une bande lui est réservée; si le numéro et le QR complet ne tiennent pas de façon lisible, choisir un format plus grand. Les notes ne sont pas imprimées ni ajoutées au RFID ou au QR. Les anciennes étiquettes QR retrouvent leur bobine par l’UUID existant.

Avant une mise à jour, sauvegarder le répertoire de données complet, serveur arrêté. La version courante utilise le schéma **5**; les anciennes bases compatibles sont migrées à l’ouverture. Ne pas ouvrir une base récente avec des sources plus anciennes. Pour revenir à une version sauvegardée, restaurer ensemble ses sources et ses données.

## Qualification

Les vérifications logicielles et les limites matérielles de la version courante sont détaillées dans le [guide de vérification](08-verification-prototype.md).

Recherche par numéro, enregistrement des deux types de notes, conservation des brouillons pendant un changement de langue ou une actualisation, conflit sans écrasement et parcours direct inventaire → RFID sont vérifiés dans une base de démonstration. Le parcours RFID de cette qualification est simulé; aucun tag réel n’est écrit et aucune étiquette n’est imprimée pour ces essais. Les clients MCP officiels moderne et historique lisent le numéro et les deux types de notes. Le contrôle sur le Pi réel reste en lecture seule et conserve stock, bibliothèque, réglages et sauvegardes NFC.