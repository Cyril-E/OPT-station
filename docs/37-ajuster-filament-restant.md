# Ajuster le filament restant dans l’inventaire

Disponible depuis **[v0.23.0](https://github.com/Cyril-E/OPT-station/releases/tag/v0.23.0)**.

1. Dans **Inventaire**, ouvrir la fiche d’une bobine **En stock** ou **En service**.
2. Cliquer sur **Ajuster le filament restant**.
3. Saisir **Filament restant (g)** : le poids du filament seul, sans la bobine vide.
4. Consulter le poids net initial de référence et la consommation qui sera enregistrée.
5. Cliquer sur **Enregistrer le restant**. La fiche, la liste et les totaux de l’inventaire sont actualisés.

Le calcul est : **consommation = poids net initial − filament restant**. Par exemple, une référence initiale de 1 000 g et un restant de 350 g donnent 650 g consommés. La tare n’est pas soustraite : le champ demande déjà le filament seul.

## Choisir la référence

Le poids net initial réel est utilisé en priorité. À défaut, le poids nominal sert de référence et la quantité reste signalée comme estimée. Le poids nominal n’est jamais transformé automatiquement en poids mesuré.

Si le poids initial réel est connu, il peut être renseigné ou corrigé dans le même formulaire. Un champ vide conserve la référence actuelle. Si aucun poids initial n’est connu, il faut fournir ce poids pour recalculer la consommation. Le formulaire ne déduit pas le poids initial d’une quantité restante.

Une quantité négative, non numérique ou supérieure à la référence est refusée. Une quantité nulle est autorisée, mais l’archivage et le compteur restent liés au bouton **Marquer comme terminée**. Les fiches retirées ou archivées ne proposent pas le réglage.

## QR, RFID et modifications simultanées

La correction concerne l’inventaire. Elle conserve le numéro, l’identité, la date d’entrée, l’utilisation, les notes et la tare. Les sauvegardes incluent les nouvelles valeurs.

Pour une bobine QR, les prochaines étiquettes contiennent les valeurs corrigées; réimprimer le QR si une ancienne étiquette doit être remplacée. Pour une bobine RFID, les corrections restent locales et une indication **RFID à actualiser** apparaît. Une ancienne relecture ne les remplace pas silencieusement. Utiliser la création/recréation du tag depuis la fiche pour les écrire physiquement.

Si la fiche a changé sur un autre écran ou via MCP, l’enregistrement est refusé et la saisie est conservée. **Recharger la quantité** abandonne explicitement ce brouillon et récupère la référence et le restant actuels. Les notes non enregistrées de la fiche sont conservées lors de l’ajustement de quantité.

Le parcours est disponible en français, anglais, espagnol et allemand. Il respecte le niveau d’accès à l’inventaire, les blocages de maintenance et les commandes d’alimentation en cours.
