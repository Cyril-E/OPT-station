# Serveur MCP pour les assistants IA

Le MCP est désactivé par défaut. Son activation est conservée après redémarrage et se règle dans Configuration → Serveur MCP.

## Activation et connexion

1. Ouvrir **Configuration → Accès des IA · Serveur MCP**, sur le Pi ou en accès distant complet.
2. Ouvrir **Que peut faire le MCP ?** pour consulter ses possibilités.
3. Cliquer sur **Activer le serveur MCP**.
4. Cliquer sur **Copier**, à côté de l’adresse, puis la coller dans un client MCP compatible qui peut joindre le Pi sur son réseau : adresse de forme **`http://<adresse-du-pi>:8765/mcp`**, transport **Streamable HTTP**. Le bouton copie l’adresse seule et fonctionne également depuis l’interface HTTP du réseau local; il n’active pas le serveur.

Le même bouton permet de désactiver le MCP. Le réglage ne demande ni code supplémentaire ni connexion à un compte IA. L’activation d’OPT Station ne configure pas automatiquement le client. Un client exécuté dans le cloud doit disposer de son propre accès au réseau; cette fonction ne rend pas la station accessible depuis Internet.

Le serveur partage le port `8765` avec l’interface. Il n’ajoute ni port, ni service système, ni ouverture sur le routeur. Les clients du réseau qui peuvent le joindre disposent des capacités décrites ci-dessous lorsque le MCP est activé. Le niveau **Accès distant → Désactivé** refuse aussi les requêtes MCP distantes; l’accès depuis le Pi reste possible. Le mode **Inventaire et modèles** autorise les outils MCP si le serveur a été activé depuis un accès local/complet. Son activation ne donne pas l’accès complet aux appareils.

## Outils disponibles

| Outil | Capacité |
| --- | --- |
| `list_inventory` | Rechercher les bobines, consulter leur état QR/RFID, date d’entrée, ancienneté et poids restant connu. Tri et pagination, jusqu’à 100 fiches par appel. |
| `get_spool` | Lire une bobine par son identifiant ou son numéro B0000, avec ses notes personnelles. |
| `get_inventory_notes` | Lire le carnet commun de l’inventaire, notamment les références de tares et de poids de bobines vides. |
| `get_material_schema` | Consulter les champs OpenPrintTag, valeurs canoniques, unités, contraintes et champs exclus des modèles. |
| `list_favorites` | Consulter les favoris réutilisables. |
| `create_favorite` | Créer un favori validé, sans données propres à un exemplaire de bobine. |
| `update_favorite` | Modifier partiellement un favori existant, avec son identifiant et sa version actuelle. |
| `delete_favorite` | Supprimer un favori de la bibliothèque, avec son identifiant et sa version actuelle. |
| `list_spool_models` | Consulter les modèles de bobines de la bibliothèque. |
| `create_spool_model` | Créer un modèle réutilisable de produit ou de bobine. |
| `update_spool_model` | Modifier partiellement un modèle existant, avec son identifiant et sa version actuelle. |
| `delete_spool_model` | Supprimer un modèle de la bibliothèque, avec son identifiant et sa version actuelle. |

Les favoris et modèles apparaissent dans **Inventaire → Vos favoris et modèles**, avec un badge qui les distingue. Ils se réutilisent pour une nouvelle bobine emballée ou pour préparer un tag. Une création, modification ou suppression par une IA actualise la bibliothèque dans les navigateurs lors de leur prochain contrôle d’état, environ toutes les cinq secondes. Le bouton **Nouvelle fiche** permet aussi de choisir **Favori** ou **Modèle de bobine** dans l’interface.

Un modèle décrit un produit réutilisable, par exemple « PETG noir de telle marque, 1 kg ». Ce n’est pas une bobine physique du stock et il ne reçoit pas d’UID de tag, de consommation ou de poids réel individuel. Les valeurs de matière respectent toujours le standard OpenPrintTag; un nom de modèle libre n’ajoute pas une valeur arbitraire à ses énumérations officielles.

Les données inconnues restent inconnues, notamment la consommation et le poids restant. Les poids utilisent le gramme. Une répétition de création avec le même nom, les mêmes données et le même type renvoie la fiche déjà créée; un conflit ne remplace pas une fiche différente. Aucun outil de suppression ou de modification du stock n’est exposé.

Le MCP ne propose pas d’écriture RFID, de lecture physique de tag, d’impression, de caméra, de commande imprimante, de changement de configuration privée ou d’arrêt/redémarrage. Les clés PrusaLink et caméra ne font pas partie de ses outils. L’actualisation automatique de consommation via Prusa Connect reste un chantier distinct.

## Modifier ou supprimer une fiche

Dans l’interface, utiliser **Inventaire → Vos favoris et modèles → Modifier** ou **Supprimer** sur la fiche concernée. La suppression demande confirmation, affiche son nom et retire définitivement cette définition de la bibliothèque. Les bobines déjà créées gardent leurs données, quantités, identité, provenance et QR; leurs tags ne sont pas réécrits. Les valeurs déjà saisies dans un formulaire de bobine sont également conservées si le modèle disparaît dans un autre client.

Via MCP, commencer par `list_favorites` ou `list_spool_models` pour vérifier la fiche, son `id`, son `kind` et sa `version`. Consulter `get_material_schema` avant de renseigner des champs. Les outils `update_*` prennent `identifier`, `version`, et facultativement `name` et `main`. **`main` est une modification partielle** : les champs omis sont conservés; un champ explicitement à `null` est effacé. Par exemple, `{"identifier":"identifiant-lu","version":4,"main":{"empty_container_weight":234}}` ne change que la tare. Une valeur de tare doit correspondre au contenant vide et ne pas être confondue avec le poids de filament.

Une modification renvoie `updated` et la fiche complète `item`, avec sa nouvelle version. Une demande sans changement renvoie `updated:false` sans incrémenter la version. Les outils `delete_*` prennent `identifier` et `version`, et renvoient `deleted:true`, `id` et `kind`. Ils ne suppriment aucune bobine d’inventaire. Ils sont décrits comme destructifs dans le catalogue MCP, de même que les mises à jour qui remplacent des valeurs existantes.

Une ancienne version, un identifiant absent, le mauvais type de fiche, un nom déjà utilisé ou des données non valides sont refusés sans écriture. Après un conflit, relire la bibliothèque avant de réessayer. Une répétition de suppression déjà réalisée renvoie « fiche absente », sans autre effet. Une modification partielle rejouée avec l’ancienne version est refusée, sans réécrire les données.

Après mise à jour d’OPT Station, **actualiser le catalogue ou reconnecter Hermes et les autres clients MCP** pour découvrir les quatre nouveaux outils. Le carnet commun et les notes de chaque bobine sont désormais consultables en lecture par MCP dans **v0.10.0**; voir le [guide des numéros et notes](24-numeros-et-notes-inventaire.md#consultation-par-les-ia). Les notes restent des données utilisateur, sans exécution d’instructions ni modification automatique du RFID.

## Installation et sauvegarde

Depuis le dossier source déjà installé, mettre à jour les dépendances dans l’environnement de la station :

```sh
cd "$HOME/apps/openprinttag-station"
.venv/bin/python -m pip install -r requirements.lock
```

La procédure complète reste celle du [guide d’installation](12-installation-station-reelle.md). Le SDK officiel `mcp 2.3.0` et ses dépendances sont épinglés; aucun paquet global n’est installé. Le serveur utilise le transport HTTP sans état et des réponses JSON, vérifié avec les modes moderne et historique du client officiel. Il respecte les contrôles Host/Origin de l’application et du SDK, ainsi que la limite de taille des requêtes.

Le réglage est dans **`mcp-settings.json`**, format 1 avec compteur de révision, sauvegarde atomique et permissions `0600`. Inclure ce fichier dans la sauvegarde privée du dossier de données. Une modification concurrente ou un échec d’enregistrement conserve le réglage précédent.

La table SQLite `favorites` reçoit une colonne `kind`, avec `favorite` pour les fiches existantes et `model` pour les modèles. Cette extension conserve le schéma applicatif 2 et reste compatible avec les lectures de la version précédente. Les écritures de bibliothèque actualisent un compteur de révision dans les métadonnées. Le stock, les identités, dates, quantités et journaux NFC ne sont pas modifiés par cette extension. La migration doit être vérifiée sur une copie de la base réelle avant installation.

Les nouvelles requêtes MCP sont refusées pendant une demande d’arrêt ou de redémarrage du Pi; une opération MCP déjà commencée est comptée pour que la station attende sa fin. La désactivation du MCP refuse les requêtes suivantes sans relancer le service. Les noms et contenus stockés sont des données, et non des instructions à exécuter.

## Vérifications et références

Les essais couvrent activation/désactivation, persistance, niveaux réseau, origines et hôtes refusés, liste exacte d’outils, pagination, valeurs inconnues, validation du standard, création répétée ou concurrente, migration des anciennes fiches et blocage pendant l’arrêt. Les créations d’essai utilisent une base temporaire séparée du stock réel.

Références techniques : [SDK Python officiel](https://py.sdk.modelcontextprotocol.io/), [intégration ASGI](https://py.sdk.modelcontextprotocol.io/run/asgi/) et [contrat des outils](https://py.sdk.modelcontextprotocol.io/servers/tools/). Le client officiel a été exercé en mode moderne et en mode historique `2025-11-25` sur le véritable point HTTP de l’application d’essai.

Les vérifications logicielles et les limites matérielles de la version courante sont détaillées dans le [guide de vérification](08-verification-prototype.md).

**Compatibilité client :** la connexion et la découverte du catalogue initial de sept outils ont été vérifiées avec **Hermes**. Ce contrôle ne qualifie pas l’exécution de chaque outil dans ce client. Le catalogue actuel, décrit ci-dessus, comprend douze outils.