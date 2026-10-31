# Bobines terminées, archives et compteur

Fonction du développement **0.9.0.dev0**, depuis l’onglet **Inventaire**. Elle complète le stock QR/RFID et conserve les fiches des bobines utilisées.

## Terminer une bobine

Dans la liste du stock ou dans le détail d’une fiche, cliquer sur **Marquer comme terminée**. La station :

- Sort la bobine du stock actif et de son total de matière restante.
- Enregistre la date de fin et conserve sa fiche dans **Terminées · archives**.
- Ajoute une seule bobine au compteur **BOBINES CONSOMMÉES**.

La fin de bobine est une déclaration explicite. Un restant à zéro ne déclenche pas automatiquement cette action. Il n’est pas nécessaire de poser le tag sur le lecteur et aucune lecture, écriture NFC ou impression n’est déclenchée.

Les dernières données connues restent intactes : identité de la bobine, UID éventuel, dates d’entrée et de lecture, matière, consommation et poids restant. La quantité consommée n’est pas forcée au poids initial et une valeur inconnue reste inconnue. La vue d’archives indique donc **DERNIER RESTANT CONNU**, avec la date **TERMINÉE LE** séparée.

Le bouton **Retirer** reste un simple retrait de stock, sans passage à l’état terminé et sans ajout au compteur. Une bobine retirée peut toujours revenir en stock; une bobine terminée reste archivée. Cette version ne propose pas d’annulation de fin de bobine.

## Consulter les archives

Dans **Inventaire**, choisir **Terminées · archives**. Les fiches sont présentées de la fin la plus récente à la plus ancienne. La recherche et l’ouverture du détail restent disponibles, avec toutes les données conservées. **En stock** revient à la liste active.

Le compteur concerne toutes les bobines terminées, indépendamment de la recherche ou de la vue sélectionnée. Il est conservé après redémarrage et actualisé dans les autres navigateurs à leur prochain contrôle d’état, environ toutes les cinq secondes. Les anciennes bobines retirées ou indiquant zéro gramme ne sont pas comptées rétroactivement.

Une demande répétée ou simultanée renvoie la même archive, sans changer sa date ni incrémenter à nouveau le compteur. Relire un tag ou scanner un ancien QR ne réactive pas une bobine terminée; les parcours de remise en stock et d’association RFID restent fermés pour cette fiche.

## Accès et MCP

L’action utilise les mêmes droits que la gestion d’inventaire : accès local, mode réseau **Inventaire et modèles** ou **Accès complet**. En mode réseau Désactivé, elle reste locale. Le contrôle de version refuse une fiche modifiée depuis son affichage; une écriture NFC en cours termine avant cette vérification.

L’API ajoute `POST /api/inventory/{id}/complete`, avec `{"version": <version affichée>}`. Les fiches exposent `completed_at`, nul tant qu’elles ne sont pas terminées. L’état de la station expose `completed_spools_count`, masqué pour un client distant dont le partage est désactivé. `GET /api/inventory?include_removed=true` inclut les archives.

Depuis **v0.10.0**, le MCP comporte **douze outils : six en lecture, six d’écriture de bibliothèque**. Les numéros et notes restent consultables sur les archives. `list_inventory` retourne aussi `completed_count`; son option `include_removed=true` inclut les archives. Aucun outil de fin de bobine ou de modification du stock n’est ajouté aux IA.

## Migration et sauvegarde

**Sauvegarder le dossier de données complet, serveur arrêté, avant la mise à jour.** Le schéma SQLite passe de **2 à 3**, en ajoutant uniquement `completed_at`. Les stocks, fiches retirées, favoris/modèles, historiques NFC, travaux d’impression et réglages des appareils sont conservés. La migration est transactionnelle et ne déduit pas de fin de bobine à partir d’une ancienne quantité.

Avant une mise à jour, sauvegarder le répertoire de données complet, serveur arrêté. La version courante utilise le schéma **5**; les anciennes bases compatibles sont migrées à l’ouverture. Ne pas ouvrir une base récente avec des sources plus anciennes. Pour revenir à une version sauvegardée, restaurer ensemble ses sources et ses données.

## Vérifications

Les tests couvrent la conservation des données inconnues, la distinction retrait/fin de bobine, les demandes simultanées et répétées, la persistance après réouverture, les relectures et anciens QR, les accès réseau et les interruptions de migration. Le parcours navigateur est vérifié en français et en anglais avec une bobine fictive, dans une base séparée du stock réel.

Les vérifications logicielles et les limites matérielles de la version courante sont détaillées dans le [guide de vérification](08-verification-prototype.md).