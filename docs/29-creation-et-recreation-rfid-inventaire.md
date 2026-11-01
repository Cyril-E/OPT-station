# Créer ou recréer un tag RFID depuis l’inventaire

L’inventaire permet de créer ou de recréer le tag RFID d’une bobine en conservant son identité et ses données.

## Depuis la fiche d’une bobine

1. Ouvrir **Inventaire**, retrouver la bobine par son numéro **Bxxxx**, puis ouvrir son détail.
2. Pour une bobine sous QR, choisir **Créer le tag RFID**. Si elle est déjà associée à un RFID, la fiche indique **« Un tag RFID existe déjà pour cette bobine. »** et propose **Recréer le tag RFID**.
3. Poser un **tag vierge** ou un **ancien tag réutilisable** sur le lecteur, puis choisir **Relire le tag présenté** dans Écriture. La réutilisation est disponible depuis **v0.24.0**.
4. Si le tag a déjà servi, vérifier l’avertissement et cocher **Réutiliser ce tag et remplacer son contenu**. Si une autre bobine y est associée, son numéro est affiché.
5. Vérifier les données chargées depuis la fiche actuelle, puis cliquer sur **Vérifier les modifications**. L’aperçu montre les colonnes **Avant / Après** et les associations concernées.
6. Confirmer avec **Remplacer le contenu du tag** pour un réemploi, ou avec le bouton d’écriture habituel pour un tag vierge. OPT Station sauvegarde l’ancien contenu, écrit et relit le tag avant de mettre à jour l’inventaire.

La même fiche est conservée : numéro B, identité logique OpenPrintTag, date d’entrée, notes, masses, caractéristiques et consommation connue. Aucune nouvelle bobine ni aucun nouveau numéro ne sont créés. Les valeurs absentes restent absentes. Les notes et le numéro B restent des données d’inventaire et ne sont pas ajoutés au format RFID.

Le bouton reste disponible pour les recréations suivantes. Il est proposé pour une bobine active en stock; une fiche terminée ou retirée ne prépare pas de nouveau tag. L’action matérielle nécessite un accès local ou complet, comme les autres écritures NFC.

## Remplacement d’un tag existant

Un tag contenant déjà des données OpenPrintTag peut être réutilisé après confirmation explicite depuis la fiche d’inventaire. Relire le tag annule cette confirmation et tout ancien aperçu. Sans confirmation, son contenu reste protégé contre le remplacement par ce parcours. Les protections matérielles, la capacité et la prise en charge du tag restent contrôlées; aucun mot de passe ni verrouillage du tag n’est modifié.

Si ce tag était associé à une autre bobine, la réussite de l’écriture et de la relecture transfère son association à la bobine choisie. L’ancienne fiche reste dans l’inventaire ou les archives, sans RFID associé et avec ses données, numéro, date d’entrée, notes, photos, état et consommation conservés. Elle peut générer son QR ou recevoir plus tard un autre RFID. La réutilisation du tag ne marque pas automatiquement son ancienne bobine comme terminée et ne modifie pas le compteur.

L’ancien identifiant reste associé jusqu’à la réussite de l’écriture et de la relecture. Si un autre support RFID remplace l’ancien, la lecture de cet ancien support dans OPT Station produit un conflit d’identité : elle ne remet pas ses anciennes données ou sa consommation dans la fiche actuelle. Ce support contient toujours physiquement ses données; le retirer de la bobine pour éviter de le confondre avec le nouveau, ou le réutiliser explicitement depuis une autre fiche.

Les versions de la fiche choisie et de l’ancienne association sont contrôlées lors de la préparation puis avant l’écriture. Si elles ont changé, recharger la fiche et préparer un nouvel aperçu. Les notes peuvent être modifiées séparément sans être perdues. Des champs RFID inconnus dans la fiche choisie empêchent la recréation pour éviter une copie incomplète.

## Reprendre après une interruption

Une écriture incertaine ne doit pas être répétée automatiquement. Choisir **Lecture → Lire le tag**.

Si l’image du nouveau tag correspond exactement à l’écriture journalisée et que la fiche n’a pas changé, OPT Station affiche **Association à confirmer** et le bouton **Confirmer l’association du tag**. Ce bouton relit et vérifie le tag puis met à jour uniquement l’association d’inventaire; il ne réécrit pas le RFID. Une ancienne opération déjà terminée ne peut pas réassocier un tag remplacé.

Si les données, le tag ou la version de la fiche ne correspondent plus, l’association est refusée et le message d’erreur reste visible. L’ancienne association n’est pas remplacée silencieusement.

## Validation

La réutilisation d’un ancien tag depuis une fiche d’inventaire est confirmée par un essai utilisateur sur Raspberry Pi, avec écriture et relecture de contrôle. Le journal de la station confirme une opération de réutilisation terminée. Les autres profils matériels et les interruptions physiques demandent leurs propres essais.

Les essais logiciels couvrent la création initiale, plusieurs recréations, la réutilisation d’un tag écrit, la conservation des deux fiches, du numéro, de la date, des notes et des valeurs Main/Aux, les versions concurrentes, les tags inadaptés, les interruptions et la reprise sans réécriture. Le journal et l’association sont aussi vérifiés après sauvegarde et restauration sur une base de test. Le schéma SQLite reste **6** et le serveur MCP conserve ses treize outils sans accès matériel.

Les vérifications logicielles et les limites matérielles de la version courante sont détaillées dans le [guide de vérification](08-verification-prototype.md).

## Installation et conservation des données

Depuis `v0.12.0` ou `0.13.0.dev0`, sauvegarder le dossier de données avant de remplacer les sources, serveur arrêté. Aucun nouveau paquet, réglage ou changement de schéma n’est requis pour cette fonction. Conserver les anciennes sources et la sauvegarde de données pour un retour arrière. Le guide d’[installation de la station réelle](12-installation-station-reelle.md) reste applicable.
