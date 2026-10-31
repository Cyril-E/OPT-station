# Créer un modèle depuis un tag RFID ou un QR

Un modèle est une fiche réutilisable de la bibliothèque, distincte d’une bobine individuelle. Il peut être préparé depuis une lecture RFID ou un QR.

## Depuis l’inventaire

Dans **Inventaire → détail d’une bobine → Créer un modèle**, préparer une fiche à partir des données enregistrées, sans lire le tag ni scanner le QR. Vérifier et nommer le modèle avant enregistrement; les champs individuels et les notes sont écartés. Disponible depuis **v0.14.0**, également pour les archives et en accès distant Inventaire. Voir le [guide de la fiche d’inventaire](30-utilisation-et-modeles-inventaire.md).

## Depuis un tag RFID

Dans **Inventaire → Vos favoris et modèles**, choisir **Depuis un tag ou un QR**, poser le tag OpenPrintTag sur le lecteur puis cliquer sur **Lire le tag RFID**. Après une lecture dans l’onglet **Lecture**, le bouton **Créer un modèle** donne également accès à ce parcours; garder le tag posé, car son identité et sa version sont contrôlées pour éviter de reprendre les données d’une autre bobine.

La lecture utilisée pour cet aperçu ne crée pas de bobine et n’actualise pas l’inventaire. Elle n’écrit pas sur le RFID et accepte un tag lisible dont les données sont protégées. Un tag absent, vierge, illisible ou changé produit une indication dans la fenêtre. Les champs inconnus du tag ne sont pas copiés; leur présence est signalée.

## Depuis un QR ou un code produit

Dans la même fenêtre, coller le texte dans **QR ou code produit**, puis choisir **Analyser le code**, ou utiliser **Scanner avec la caméra** et **Utiliser ce code**.

- **QR OPT Station** : lecture autonome des données, sans Internet. Une ancienne étiquette ou une bobine archivée peut fournir des caractéristiques réutilisables; cela ne remet pas la bobine en stock et ne réinitialise pas sa consommation.
- **QR Prusament** : récupération des valeurs de la fiche officielle via Internet, avec les limites décrites dans le [guide fabricant](19-stock-qr-et-etiquettes.md#lire-un-qr-fabricant-prusament). Une tare non renseignée reste vide.
- **QR produit Prusa** : depuis `0.13.1.dev0`, liens `prusa3d.com/product/prusament-…`, avec ou sans `https://`. Les caractéristiques réutilisables de la variante sélectionnée sont proposées; les mesures individuelles absentes restent inconnues. Voir le [guide des fiches produit](19-stock-qr-et-etiquettes.md#qr-de-fiche-produit-prusa).
- **GTIN** : recherche dans le catalogue local. S’il y a plusieurs références, sélectionner celle qui correspond au produit; aucune n’est choisie automatiquement.
- **Autres contenus** : message explicite et absence de fiche supposée. Utiliser la création manuelle si le format n’est pas pris en charge.

## Vérifier et enregistrer

La fenêtre **Nouveau modèle** propose un nom et le type **Modèle de bobine**. Vérifier les champs, modifier les valeurs connues et le nom, puis choisir **Enregistrer la fiche**. **Annuler** ferme l’aperçu sans modifier la bibliothèque. L’enregistrement d’un nom déjà utilisé est refusé sans remplacer la fiche existante; changer le nom avant de réessayer. La fiche apparaît ensuite dans la bibliothèque, dans les exports et dans les outils MCP de consultation des modèles.

Les données conservées suivent les règles communes des modèles : marque, famille et type de matériau, nom, couleur, poids net nominal, tare connue, diamètre, températures, identifiants de produit et autres caractéristiques réutilisables. Les informations absentes restent inconnues. La masse réelle d’une bobine n’est jamais convertie en masse nominale par supposition.

Sont écartés : UID et UUID de la bobine, identifiant de son exemplaire chez le fabricant, poids et longueur réels, dates de fabrication/expiration, protection déclarée, consommation, emplacement, groupe de travail, notes et autres données individuelles de suivi. La bobine d’origine, le tag et les éventuelles fiches existantes conservent leurs données. L’aperçu ne crée ni nouvelle bobine ni nouveau numéro B.

## Accès et compatibilité

Les utilisateurs en accès **Inventaire** peuvent analyser un QR saisi et créer un modèle. La lecture du RFID et la caméra demandent l’accès **local ou complet**, comme les autres commandes matérielles. Les demandes sont refusées pendant un arrêt, un redémarrage ou une restauration exclusive.

La création réutilise l’enregistrement existant de la bibliothèque et ses contrôles de nom, de type et de valeurs. La base utilise le **schéma 5** pour séparer l’utilisation de l’identification QR/RFID et le serveur MCP conserve **douze outils**, sans commande supplémentaire de lecture physique. Aucun changement de configuration n’est nécessaire après mise à jour; les ressources de l’interface sont versionnées pour un rechargement cohérent.

## Validation en usage réel

**Validation matérielle :** la création d’un modèle depuis un tag RFID puis depuis un QR code a été vérifiée sur Raspberry Pi avec **v0.12.0**. Ces essais complètent les tests automatisés et les vérifications d’aperçu avant publication.
