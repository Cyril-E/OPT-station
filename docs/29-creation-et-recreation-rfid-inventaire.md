# Créer ou recréer un tag RFID depuis l’inventaire

L’inventaire permet de créer ou de recréer le tag RFID d’une bobine en conservant son identité et ses données.

## Depuis la fiche d’une bobine

1. Ouvrir **Inventaire**, retrouver la bobine par son numéro **Bxxxx**, puis ouvrir son détail.
2. Pour une bobine sous QR, choisir **Créer le tag RFID**. Si elle est déjà associée à un RFID, la fiche indique **« Un tag RFID existe déjà pour cette bobine. »** et propose **Recréer le tag RFID**.
3. Poser un **tag vierge** sur le lecteur, puis choisir **Relire le tag présenté** dans Écriture.
4. Vérifier les données chargées depuis la fiche actuelle, puis préparer l’écriture. En recréation, l’aperçu indique aussi l’ancien identifiant NFC dont l’association sera remplacée.
5. Confirmer l’écriture habituelle. OPT Station écrit, relit le tag et compare l’image complète avant de mettre à jour l’association dans l’inventaire.

La même fiche est conservée : numéro B, identité logique OpenPrintTag, date d’entrée, notes, masses, caractéristiques et consommation connue. Aucune nouvelle bobine ni aucun nouveau numéro ne sont créés. Les valeurs absentes restent absentes. Les notes et le numéro B restent des données d’inventaire et ne sont pas ajoutés au format RFID.

Le bouton reste disponible pour les recréations suivantes. Il est proposé pour une bobine active en stock; une fiche terminée ou retirée ne prépare pas de nouveau tag. L’action matérielle nécessite un accès local ou complet, comme les autres écritures NFC.

## Remplacement d’un tag existant

La recréation s’effectue sur un tag vierge. Un tag contenant déjà des données n’est pas effacé par ce parcours. Les protections, la capacité et la prise en charge du tag de destination sont contrôlées, ainsi que l’absence d’association de son identifiant NFC à une autre bobine.

L’ancien identifiant reste associé jusqu’à la réussite de l’écriture et de la relecture. Après remplacement, la lecture de l’ancien tag dans OPT Station produit un conflit d’identité : elle ne remet pas ses anciennes données ou sa consommation dans la fiche actuelle. L’ancien tag contient toujours physiquement ses données; le retirer de la bobine pour éviter de le confondre avec le nouveau.

La version de la fiche est contrôlée lors de la préparation puis avant l’écriture. Si la bobine a changé, a été retirée ou archivée entre-temps, recharger sa fiche et préparer un nouvel aperçu. Les notes peuvent être modifiées séparément sans être perdues. Des champs RFID inconnus empêchent la recréation pour éviter une copie incomplète.

## Reprendre après une interruption

Une écriture incertaine ne doit pas être répétée automatiquement. Choisir **Lecture → Lire le tag**.

Si l’image du nouveau tag correspond exactement à l’écriture journalisée et que la fiche n’a pas changé, OPT Station affiche **Association à confirmer** et le bouton **Confirmer l’association du tag**. Ce bouton relit et vérifie le tag puis met à jour uniquement l’association d’inventaire; il ne réécrit pas le RFID. Une ancienne opération déjà terminée ne peut pas réassocier un tag remplacé.

Si les données, le tag ou la version de la fiche ne correspondent plus, l’association est refusée et le message d’erreur reste visible. L’ancienne association n’est pas remplacée silencieusement.

## Validation

Les essais logiciels couvrent la création initiale, plusieurs recréations, la conservation de l’identité, du numéro, de la date, des notes et des valeurs Main/Aux, les versions concurrentes, les tags inadaptés, les interruptions et la reprise sans réécriture. Le journal et l’association sont aussi vérifiés après sauvegarde chiffrée et restauration sur une base de test. Le schéma SQLite reste **4** et le serveur MCP conserve ses douze outils sans accès matériel.

Les vérifications logicielles et les limites matérielles de la version courante sont détaillées dans le [guide de vérification](08-verification-prototype.md).

## Installation et conservation des données

Depuis `v0.12.0` ou `0.13.0.dev0`, sauvegarder le dossier de données avant de remplacer les sources, serveur arrêté. Aucun nouveau paquet, réglage ou changement de schéma n’est requis pour cette fonction. Conserver les anciennes sources et la sauvegarde de données pour un retour arrière. Le guide d’[installation de la station réelle](12-installation-station-reelle.md) reste applicable.
