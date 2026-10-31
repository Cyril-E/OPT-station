# Utilisation et modèles depuis l’inventaire

Le détail d’une bobine permet de modifier son état Stock/Service et de préparer un modèle depuis ses caractéristiques.

## En stock ou en service, avec ou sans RFID

Dans **Inventaire → détail d’une bobine**, utiliser **Remettre en stock** ou **Passer en service**. Une bobine reçue avec un tag RFID peut ainsi rester en réserve, puis être mise en service au moment voulu. Le changement est réversible tant que la bobine est active.

Deux informations distinctes sont affichées dans la liste et la fiche :

- **Utilisation : En stock / En service**, conservée après redémarrage et nouvelle lecture.
- **Identification : QR / RFID**, conservée lors du changement d’utilisation.

Le numéro B, l’identité, le tag, les quantités, la date d’entrée, les notes et l’historique restent identiques. Le bouton modifie uniquement le statut dans OPT Station; aucune lecture ou écriture NFC n’est nécessaire. Une bobine terminée reste archivée et comptabilisée; ce bouton ne la réactive pas.

Les nouvelles réceptions QR démarrent **En stock**; l’ajout d’un RFID démarre **En service**. La première création du RFID d’une bobine QR la passe en service, comme auparavant. Recréer le RFID d’une bobine déjà équipée conserve son choix d’utilisation, y compris **En stock**. Un nouvel ajout ou une relecture d’un RFID connu ne remet pas ce choix à zéro.

La vue **Actives** regroupe le stock et les bobines en service; le compteur des bobines actives garde le même périmètre. Le compteur des bobines consommées ne change pas lors d’une bascule.

## Créer un modèle depuis une fiche

Ouvrir **Inventaire → détail → Créer un modèle**. La fiche de bibliothèque est préremplie avec les caractéristiques réutilisables : marque, matière, couleur, poids nominal, tare connue, diamètre, températures et autres données de produit. Modifier le nom ou les valeurs souhaitées, puis cliquer sur **Enregistrer la fiche**. Annuler ne crée rien.

La préparation utilise la dernière fiche enregistrée dans l’inventaire, sans présenter le tag ni scanner le QR. Elle fonctionne aussi depuis une archive. Elle ne copie pas le numéro B, l’identité individuelle, le poids réel, les dates propres à cette bobine, la consommation ou les notes. Les valeurs inconnues restent absentes. Un nom déjà utilisé est refusé sans remplacer un autre modèle.

Les deux fonctions sont accessibles en mode distant **Inventaire et modèles**, ainsi qu’en accès local ou complet. Les contrôles de version empêchent une fiche ouverte avant une modification d’écraser la nouvelle version. Les brouillons de notes sont conservés pendant la bascule.

## Données, sauvegardes et MCP

La base migre automatiquement du schéma **4 vers 5** au lancement. Les fiches existantes gardent leur affichage précédent : QR en stock, RFID en service; le changement peut ensuite être effectué individuellement. Les autres champs restent identiques.

Les identités dérivées de l’UID des tags d’origine sont conservées, même si le champ d’identité n’est pas présent dans les données Main. Les sauvegardes nouvelles conservent `usage_state`; la restauration des anciennes sauvegardes de schéma 4 reste disponible et initialise ce statut selon la même règle. Sauvegarder le dossier de données avant installation. Pour revenir à un ancien logiciel ne prenant pas en charge le schéma 5, utiliser les anciennes sources avec la base sauvegardée correspondante; conserver séparément les données ajoutées depuis.

Les outils MCP existants exposent `usage_state` (`stock` ou `in_service`) séparément de `label_state` (`qr` ou `rfid`). Le champ historique `in_stock` signifie que la fiche est active dans l’inventaire. Le MCP garde douze outils et n’ajoute aucune commande matérielle ni modification du statut d’utilisation.

## Vérification

Les essais couvrent les bascules dans les deux sens, la persistance après relecture et redémarrage du stockage, la concurrence, les archives, les notes, la création de modèles vérifiés et la restauration des sauvegardes de schéma 4 et 5. Les parcours français et anglais sont exercés en navigateur sur des données de démonstration. La migration, les sauvegardes et les nouveaux parcours sont également qualifiés sur une copie privée des données du Pi avant installation; aucun tag physique n’est écrit pour ces essais.
