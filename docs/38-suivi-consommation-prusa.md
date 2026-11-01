# Données nécessaires au suivi de consommation Prusa

Une imprimante peut reconnaître la matière et la couleur d’un OpenPrintTag tout en refusant d’y suivre la consommation. La reconnaissance du matériau et le suivi des quantités utilisent des informations différentes.

Le [code de suivi Prusa publié](https://github.com/prusa3d/Prusa-Firmware-Buddy/blob/1ce23f33ed3b94e26aa33a44557d6c4a4be11eb6/src/feature/openprinttag/filament_usage_tracker/filament_usage_tracker.cpp) demande une masse initiale et une longueur initiale. Sa [lecture des quantités](https://github.com/prusa3d/Prusa-Firmware-Buddy/blob/1ce23f33ed3b94e26aa33a44557d6c4a4be11eb6/src/feature/openprinttag/data_utils.cpp) prend la valeur réelle en priorité, puis la nominale. Une longueur absente empêche le calcul de la masse consommée à partir de la longueur extrudée, même si la densité et le diamètre sont renseignés.

## Avant l’écriture

Dans l’aperçu, OPT Station avertit si le poids net initial ou la longueur initiale est absent ou nul pour une bobine FFF. Ce contrôle, disponible depuis v0.24.1, n’empêche pas l’écriture d’un tag utilisé pour un autre usage et ne remplit aucune valeur inconnue.

Les longueurs se trouvent dans **Écriture → Autres données matériau** et sont exprimées en **millimètres** : 330 m correspondent à 330 000 mm. Le poids du contenant vide ne remplace pas la masse de filament initiale.

## Longueur connue ou estimation

Utiliser une longueur annoncée par le fabricant lorsqu’elle est disponible. **Longueur réelle** est réservée à une mesure connue. Une estimation validée par l’utilisateur peut être saisie comme **Longueur nominale**, en conservant son caractère approximatif dans les notes si nécessaire.

Avec une masse initiale connue, un diamètre et une densité connus, une estimation géométrique est possible :

`longueur (mm) = masse (g) × 1 000 / [densité (g/cm³) × π × diamètre (mm)² / 4]`

Par exemple, 1 000 g, un diamètre de 1,75 mm et une densité de 1,26 g/cm³ donnent environ 330 m. Cette estimation ne constitue pas une longueur mesurée et ne change ni la tare ni la consommation déjà enregistrée.

## Tag existant

### Format des nombres sur RFID

OPT Station encode les nombres entiers comme des entiers CBOR exacts, même si la saisie les a fournis sous forme décimale : par exemple, 889,0 g devient l’entier 889. Les valeurs fractionnaires écrites utilisent un flottant de simple précision, conformément aux types numériques de la [spécification](../references/upstream/openprinttag-specification-060e420/docs_src/nfc_data_format.md). Cela évite les flottants de double précision que le [lecteur Prusa publié](https://github.com/prusa3d/Prusa-Firmware-Buddy/blob/1ce23f33ed3b94e26aa33a44557d6c4a4be11eb6/src/module/nfc/openprinttag/openprinttag/opt_reader.cpp) ne sait pas lire comme des nombres.

La simple précision peut produire un léger écart de représentation binaire pour des décimaux tels que 1,26. Une valeur hors de sa plage est refusée; elle n’est pas remplacée par zéro ou l’infini. Une modification partielle applique ce format uniquement aux champs numériques de la modification. Les autres champs, données inconnues et régions non modifiées conservent leur traitement précédent. Aucun tag existant n’est réécrit automatiquement.

Les contrôles du codec comprennent lecture, écriture puis relecture sur un support mémoire isolé avec le code Prusa publié. Ils ne qualifient pas à eux seuls le lecteur radio ou une version de firmware différente du code consulté. La création/recréation d’un tag existant permet d’appliquer le format à l’ensemble de ses données, après sauvegarde et contrôle des quantités.

Sur une CORE One en firmware 8.0.0+17068, le chargement d’un tag réécrit avec ce format et des données initiales complètes est confirmé par un essai utilisateur : l’alerte de refus de suivi disparaît et la consommation déjà enregistrée est correctement affichée. L’écriture sur la station a été sauvegardée et vérifiée par relecture, avec conservation de l’identité et des quantités.

Après une impression réelle, la relecture physique sur le Pi a confirmé l’augmentation du compteur consommé et la diminution correspondante du restant. L’identité et les données matériau étaient inchangées. La lecture NFC normale a ensuite actualisé la fiche d’inventaire, en préservant ses notes, son état et les autres bobines. La station n’a effectué aucune nouvelle écriture RFID pendant cette vérification. Ce résultat valide le cycle imprimante → tag → inventaire à la relecture pour ce profil; il ne constitue pas une synchronisation continue par Prusa Connect.

### Synchronisation avec le tag

Une correction de la fiche d’inventaire reste locale jusqu’à sa synchronisation avec le RFID. Pour compléter une longueur, la modification du tag peut mettre à jour uniquement ce champ, après sauvegarde et avec relecture de contrôle. Il faut ensuite faire relire le tag par l’imprimante.

### Après la correction d’un tag déjà chargé

Le code Prusa cité plus haut conserve une erreur de suivi pour la bobine affectée à l’outil. Retirer son tag du lecteur puis remettre le même tag ne suffit pas nécessairement : son identifiant reste le même, et le suivi peut rester désactivé pour cette session.

Après avoir vérifié la correction par relecture, attendre qu’aucune impression ne soit en cours, laisser le tag en place et redémarrer l’imprimante. Contrôler de nouveau l’alerte et la consommation affichée. Ce comportement est établi par lecture du code publié; sa résolution sur chaque version de firmware et sur le matériel demande un essai réel. Ne pas réécrire le tag ou modifier ses quantités uniquement pour tenter d’effacer l’alerte.

Un affichage « consommé : 0 g » sur l’imprimante ne justifie pas de remettre à zéro une consommation connue dans l’inventaire. Comparer les données du tag et la fiche avant toute correction. Les autres lecteurs, tags et versions de firmware demandent leurs propres essais.
