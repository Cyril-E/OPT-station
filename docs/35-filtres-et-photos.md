# Filtres d’inventaire et photos des fiches

## Filtrer les bobines

Dans **Inventaire → Vos bobines**, choisir **Tout**, **Stock**, **Production** ou **Terminées**. Tout réunit les bobines actives et terminées; les bobines simplement retirées ne réapparaissent pas. Stock et Production correspondent à l’utilisation de la fiche, indépendamment de son identification par QR ou RFID.

Ouvrir **Marques** ou **Matières**, puis cocher une ou plusieurs valeurs. Les choix proviennent des bobines de l’inventaire, archives comprises. Plusieurs choix dans une même rubrique s’additionnent; les deux rubriques, l’état et la recherche se combinent. Une valeur non renseignée peut aussi être sélectionnée. **Effacer les filtres** efface la recherche et les sélections de marque/matière, en conservant la vue choisie. Les filtres restent actifs pendant les actualisations et les changements de langue du même onglet.

## Joindre une photo

1. Ouvrir le détail d’une bobine puis **Photos**, ou cliquer sur **Photos** dans une carte de favori/modèle.
2. Choisir **Importer une photo** depuis l’appareil utilisé, ou **Prendre une photo** avec la caméra du Pi.
3. Vérifier l’aperçu puis cliquer sur **Joindre à la fiche**. Fermer ou annuler l’aperçu ne l’enregistre pas.
4. Cliquer sur une vignette pour ouvrir la photo; **Supprimer** demande une confirmation avant de retirer cette photo.

Enregistrer d’abord la fiche pour lui joindre des photos. Chaque fiche possède ses propres pièces jointes : créer une bobine à partir d’un modèle ou créer un modèle à partir d’une bobine ne copie pas automatiquement les photos. Une fiche terminée conserve les siennes. Supprimer un modèle retire ses photos et ne touche pas aux bobines créées à partir de lui.

L’import et la consultation sont accessibles avec l’accès distant Inventaire. La capture par la caméra exige l’accès local ou complet et une caméra disponible. Les fonctions distantes désactivées bloquent aussi l’accès aux photos. Le bouton d’actualisation recharge les photos ajoutées depuis un autre appareil.

## Formats, stockage et sauvegardes

- Jusqu’à **8 photos par fiche**, import JPEG, PNG ou WebP non animé, **4 Mo** et **20 mégapixels** maximum par image.
- Conversion JPEG, orientation corrigée, côté le plus long limité à **1 600 pixels**. Les métadonnées EXIF sont supprimées et une vignette est produite.
- Photos conservées dans la base SQLite de la station, y compris après redémarrage. Les ajouts sont indépendants des formulaires d’édition et ne modifient pas les poids, notes, consommation, numéros ni identités.
- Aucun appel IA, aucune écriture RFID et aucun ajout au QR. Les photos ne sont pas incluses dans l’échange JSON des modèles : utiliser une sauvegarde Inventaire ou Complète pour les conserver.
- Sauvegardes Inventaire/Complète avec photos; Configuration conserve les photos déjà présentes. Les fichiers sans photos des anciens schémas 4/5 restent restaurables. Une restauration d’un ancien inventaire remplace aussi les photos actuelles par l’état du fichier.
- Schéma SQLite **6**. Avant un retour à une version utilisant le schéma 5, restaurer ensemble les sources et les données sauvegardées avant migration.

Les limites des sauvegardes sont désormais de **128 Mo pour le fichier** et **256 Mo décompressés**, avec refus explicite au-delà. La limite s’applique à toutes les données choisies, photos comprises; aucune copie partielle n’est considérée comme valide.
