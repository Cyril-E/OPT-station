# Serveur MCP pour les assistants IA

Le MCP est désactivé par défaut. Son activation est conservée après redémarrage et se règle dans Configuration → Serveur MCP.

## Activation et connexion

1. Ouvrir **Configuration → Accès des IA · Serveur MCP**, sur le Pi ou en accès distant complet.
2. Ouvrir **Que peut faire le MCP ?** pour consulter ses possibilités.
3. Cliquer sur **Activer le serveur MCP**.
4. Cliquer sur **Copier**, à côté de l’adresse, puis la coller dans un client MCP compatible qui peut joindre le Pi sur son réseau : adresse de forme **`https://<nom-du-pi>/mcp`** après l’installation complète, transport **Streamable HTTP**. Le bouton copie l’adresse seule et fonctionne également depuis l’interface HTTP du réseau local; il n’active pas le serveur.

Le même bouton permet de désactiver le MCP. Le réglage ne demande ni code supplémentaire ni connexion à un compte IA. L’activation d’OPT Station ne configure pas automatiquement le client. Un client exécuté dans le cloud doit disposer de son propre accès au réseau; cette fonction ne rend pas la station accessible depuis Internet.

Le serveur applicatif partage le port `8765` avec l’interface; la passerelle HTTPS de l’installation complète publie le MCP sous `/mcp`, sur le même port HTTPS que le site. Le MCP n’ajoute aucun port, service système ni ouverture sur le routeur. Le client doit approuver le certificat local selon le [guide HTTPS](31-https-local.md). Pour un lancement manuel sans cette passerelle, l’adresse reste de forme `http://<adresse-du-pi>:8765/mcp`. Les clients du réseau qui peuvent le joindre disposent des capacités décrites ci-dessous lorsque le MCP est activé. Le niveau **Accès distant → Désactivé** refuse aussi les requêtes MCP distantes; l’accès depuis le Pi reste possible. Le mode **Inventaire et modèles** autorise les outils MCP si le serveur a été activé depuis un accès local/complet. Son activation ne donne pas l’accès complet aux appareils.

## Outils disponibles

La version **v0.19.0** ajoute `update_spool` et porte le catalogue à **treize outils : six lectures et sept écritures**. La modification des modèles avec `update_spool_model` et des favoris avec `update_favorite` était déjà disponible en v0.18.0.

| Outil | Capacité |
| --- | --- |
| `list_inventory` | Rechercher les bobines, consulter leur état QR/RFID, date d’entrée, ancienneté et poids restant connu. Tri et pagination, jusqu’à 100 fiches par appel. |
| `get_spool` | Lire une bobine par son identifiant ou son numéro B0000, avec sa version, ses notes et leur révision, et les éventuelles corrections RFID en attente. |
| `update_spool` | Depuis v0.19.0 : corriger une fiche de bobine existante, poids et consommation connus, notes et état Stock/Service, sans écrire le RFID. |
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

Les données inconnues restent inconnues, notamment la consommation et le poids restant. Les poids utilisent le gramme. Une répétition de création avec le même nom, les mêmes données et le même type renvoie la fiche déjà créée; un conflit ne remplace pas une fiche différente. Aucun outil de suppression, d’archivage ou de création de bobine de stock n’est exposé. Depuis `v0.19.0`, les fiches existantes sont modifiables avec `update_spool`.

Le MCP ne propose pas d’écriture RFID, de lecture physique de tag, d’impression, de caméra, de commande imprimante, de changement de configuration privée ou d’arrêt/redémarrage. Les clés PrusaLink et caméra ne font pas partie de ses outils. L’actualisation automatique de consommation via Prusa Connect reste un chantier distinct.

## Modifier une bobine de l’inventaire par MCP

Disponible depuis **v0.19.0**. Commencer par `get_spool` avec le numéro B0000 ou l’identifiant de la bobine, puis consulter `get_material_schema`. Appeler `update_spool` avec `identifier`, la `version` obtenue et uniquement les corrections voulues :

- `main` : informations produit et mesures réellement connues, par exemple la tare `empty_container_weight` et le poids net initial mesuré `actual_netto_full_weight`.
- `aux` : données de suivi, notamment `consumed_weight` en grammes. Le restant est recalculé depuis le poids net initial et la consommation; il n’est pas saisi directement. Omettre une valeur inconnue; `null` efface un champ facultatif.
- `notes` et `notes_revision` : texte des notes de la bobine et révision actuelle de ces notes. Un texte vide les efface. Le carnet commun reste en lecture seule.
- `usage_state` : `stock` ou `in_service`. L’archivage, le retrait du stock, les dates, le numéro B, l’identité logique, l’UID et les protections restent inchangés. Seules les notes d’une bobine terminée ou retirée restent modifiables.

Une modification est transactionnelle : version ou révision des notes périmée, donnée non valide ou écriture RFID à réconcilier font refuser l’ensemble. Une demande sans changement renvoie `updated:false`; une correction renvoie `updated:true`, la fiche `item` et `rfid_written:false`. L’inventaire des navigateurs se rafraîchit au prochain contrôle d’état. Le MCP attend la fin d’une opération NFC en cours avant de modifier une fiche.

**QR et RFID restent des supports distincts de la fiche.** Pour une bobine QR, les nouvelles données sont disponibles dans son prochain QR; une ancienne étiquette imprimée conserve son ancien contenu. Pour une bobine RFID, la fiche affiche **RFID à actualiser** et le MCP renvoie `rfid_sync_pending`, `rfid_pending_fields` et `last_rfid_data`. Les corrections locales sont conservées après redémarrage et lors des relectures, y compris si l’imprimante change sa consommation. Une correction disparaît de la liste d’attente lorsque sa valeur est retrouvée dans une lecture du tag. La lecture physique continue à montrer les valeurs du tag, avec un avertissement si la fiche diffère.

Pour reporter les corrections sur le RFID, utiliser le parcours explicite **Recréer le tag RFID** dans la fiche. L’écriture et sa relecture restent dans OPT Station. Pour abandonner les corrections locales, appeler `update_spool` avec `reset_tag_overrides:true` et la version actuelle : les dernières données RFID déjà observées sont alors reprises, sans nouvelle lecture matérielle; elles peuvent donc être anciennes. Lire et comparer `last_rfid_data` avant de faire ce choix. Ce paramètre ne réactive pas une bobine archivée et ne réécrit pas le tag.

Les corrections et les dernières valeurs du tag sont incluses dans les sauvegardes d’inventaire. Le schéma SQLite reste à 5. Lors d’un retour à une version antérieure, restaurer ensemble les sources et les données sauvegardées avant la mise à jour afin de préserver les règles de réconciliation.

## Modifier ou supprimer une fiche

Dans l’interface, utiliser **Inventaire → Vos favoris et modèles → Modifier** ou **Supprimer** sur la fiche concernée. La suppression demande confirmation, affiche son nom et retire définitivement cette définition de la bibliothèque. Les bobines déjà créées gardent leurs données, quantités, identité, provenance et QR; leurs tags ne sont pas réécrits. Les valeurs déjà saisies dans un formulaire de bobine sont également conservées si le modèle disparaît dans un autre client.

Via MCP, commencer par `list_favorites` ou `list_spool_models` pour vérifier la fiche, son `id`, son `kind` et sa `version`. Consulter `get_material_schema` avant de renseigner des champs. Les outils `update_*` prennent `identifier`, `version`, et facultativement `name` et `main`. **`main` est une modification partielle** : les champs omis sont conservés; un champ explicitement à `null` est effacé. Par exemple, `{"identifier":"identifiant-lu","version":4,"main":{"empty_container_weight":234}}` ne change que la tare. Une valeur de tare doit correspondre au contenant vide et ne pas être confondue avec le poids de filament.

Une modification renvoie `updated` et la fiche complète `item`, avec sa nouvelle version. Une demande sans changement renvoie `updated:false` sans incrémenter la version. Les outils `delete_*` prennent `identifier` et `version`, et renvoient `deleted:true`, `id` et `kind`. Ils ne suppriment aucune bobine d’inventaire. Ils sont décrits comme destructifs dans le catalogue MCP, de même que les mises à jour qui remplacent des valeurs existantes.

Une ancienne version, un identifiant absent, le mauvais type de fiche, un nom déjà utilisé ou des données non valides sont refusés sans écriture. Après un conflit, relire la bibliothèque avant de réessayer. Une répétition de suppression déjà réalisée renvoie « fiche absente », sans autre effet. Une modification partielle rejouée avec l’ancienne version est refusée, sans réécrire les données.

Après mise à jour d’OPT Station, **actualiser le catalogue ou reconnecter Hermes et les autres clients MCP** pour découvrir le catalogue à jour, notamment `update_spool`. Le carnet commun et les notes de chaque bobine sont désormais consultables en lecture par MCP dans **v0.10.0**; voir le [guide des numéros et notes](24-numeros-et-notes-inventaire.md#consultation-par-les-ia). Les notes restent des données utilisateur, sans exécution d’instructions ni modification automatique du RFID.

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

**Compatibilité client :** la connexion et la découverte du catalogue initial de sept outils ont été vérifiées avec **Hermes**. Ce contrôle ne qualifie pas l’exécution de chaque outil dans ce client. L’édition des fiches a ensuite été confirmée par un essai utilisateur. Le catalogue v0.19.0 comprend treize outils. Actualiser le catalogue ou reconnecter le client pour découvrir `update_spool`.