# Importer et exporter les modèles et favoris

Disponible dans **v0.10.0**, depuis **Inventaire → Vos favoris et modèles**. Les accès locaux, distants Inventaire et complets peuvent utiliser cette fonction. Les accès distants désactivés la bloquent.

## Exporter

1. Cliquer sur **Exporter des fiches**.
2. Cocher un ou plusieurs modèles ou favoris; **Tout sélectionner** et **Tout désélectionner** facilitent le choix.
3. Cliquer sur **Télécharger les fiches** pour obtenir `opt-station-library.json`.

Ce fichier contient les noms, le type modèle/favori et l’ensemble des champs Main réutilisables, avec leurs types et unités. Il ne contient ni les bobines physiques de l’inventaire, ni leurs consommations, ni leurs numéros B, ni les identifiants des appareils. Les identifiants internes et versions de bibliothèque ne sont pas transférés : une nouvelle fiche reçoit sa propre identité sur la station destinataire.

## Importer

1. Cliquer sur **Importer des fiches** et sélectionner le fichier JSON exporté.
2. Cliquer sur **Analyser le fichier**. Aucun enregistrement n’est encore modifié.
3. Examiner les fiches et, si nécessaire, ouvrir **Voir les données de la fiche**.
4. Pour un nom déjà présent, choisir **Conserver la fiche existante**, **Importer sous un autre nom** ou **Remplacer la fiche existante**. Le choix par défaut conserve l’existante. Un remplacement n’est proposé que pour le même type modèle/favori.
5. Cliquer sur **Confirmer l’import**.

Une nouvelle fiche peut également être ignorée. Une importation ne modifie jamais une bobine déjà créée ou un tag RFID. La bibliothèque s’actualise dans les autres navigateurs et dans les lectures MCP.

## Contrôles

- Format portable `opt-station-library`, version 1; fichier de **1 Mo maximum** et **1 000 fiches maximum**.
- Validation partagée avec la bibliothèque et le MCP : les champs inconnus, valeurs invalides et données propres à une bobine physique sont refusés. Aucun code, URL ou commande du fichier n’est exécuté.
- Les clés JSON répétées et les noms répétés dans le fichier sont refusés pour éviter les ambiguïtés.
- Toutes les créations et modifications sont enregistrées dans une seule transaction. Une erreur ne laisse pas une bibliothèque partiellement importée.
- Si la bibliothèque change dans un autre navigateur ou via MCP après l’aperçu, recommencer l’analyse; aucun remplacement silencieux.
- L’aperçu expire après dix minutes. Une répétition de la même confirmation ne crée pas de doublon.

Les outils MCP restent inchangés : le transfert de fichiers se fait dans l’interface; les douze outils existants conservent leurs capacités.
