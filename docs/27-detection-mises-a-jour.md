# Détection des nouvelles versions GitHub

Dans Configuration → Mises à jour d’OPT Station, la station peut consulter les versions publiées et indiquer si une mise à jour existe. Elle ne télécharge ni n’installe cette mise à jour.

## Activation

1. Ouvrir Configuration sur le Pi ou depuis le réseau avec l’accès complet.
2. Vérifier le dépôt : **Cyril-E/OPT-station**, sous la forme `propriétaire/dépôt`.
3. Pour le dépôt public OPT Station, aucun jeton n’est nécessaire. Pour une autre distribution privée, saisir un jeton GitHub à permissions fines limité au dépôt concerné, avec **Contents : Read-only**. Voir la [documentation officielle de l’API GitHub](https://docs.github.com/en/rest/releases/releases#list-releases).
4. Choisir l’intervalle de vérification, de 1 à 168 heures; valeur initiale : **6 heures**.
5. Garder **Inclure les préversions** coché pour les publications actuelles d’OPT Station.
6. Cocher **Rechercher automatiquement les nouvelles versions**, puis enregistrer. La première vérification se lance en arrière-plan.

La recherche est désactivée par défaut tant que l’accès au dépôt n’est pas configuré. **Vérifier maintenant** permet ensuite de demander un contrôle sans attendre l’échéance. Le bouton reste indisponible pendant une vérification, avant enregistrement des réglages modifiés, pendant une demande d’alimentation ou pendant le délai de reprise imposé par GitHub.

Le bouton **Comment fonctionne la vérification ?** explique le fonctionnement et fournit le lien vers la création d’un jeton. Créer celui-ci sur GitHub, puis le saisir uniquement dans le formulaire d’OPT Station; ne pas l’envoyer dans une conversation. Le champ vide conserve le secret existant. La case d’effacement le retire; un changement de dépôt sans nouveau jeton efface aussi le précédent.

## Affichage

Lorsqu’une mise à jour est connue, un bandeau affiche la version publiée et la version installée, avec un lien vers la release GitHub. Un indicateur reste également dans la barre latérale et mène à Configuration. Les utilisateurs du réseau en accès Inventaire peuvent voir cette indication; la modification des réglages et le lancement d’un contrôle nécessitent l’accès local ou complet.

Configuration affiche : version installée, dernière version compatible, état de la vérification, date du dernier contrôle réussi et prochaine échéance. Si le Pi utilise un développement plus récent que la publication courante, il l’indique et ne propose pas une ancienne version comme mise à jour.

Les noms de version sont comparés avec leur ordre numérique et leurs suffixes de préversion, jamais comme du texte : `0.10.0` est supérieur à `0.9.0`. Les brouillons, les tags sans release et les noms de tags non interprétables comme versions sont écartés. Une option exclut les préversions GitHub ainsi que les suffixes alpha/bêta/rc/dev. La version retenue est la plus élevée dans toutes les pages compatibles, indépendamment de leur date de publication.

Une réponse vide ou sans version compatible produit **Aucune version compatible**, pas **À jour**. En cas d’erreur réseau ou GitHub, le dernier résultat connu reste affiché avec la date du contrôle réussi et l’erreur actuelle. Un échec ne devient jamais une preuve d’absence de mise à jour.

## Réseau, quotas et confidentialité

Le Pi effectue uniquement des requêtes de lecture HTTPS vers `api.github.com`. Les pages suivantes proviennent des liens de pagination retournés par GitHub et sont vérifiées avant utilisation. Les liens de release affichés sont limités au dépôt sur `github.com`; les noms et contenus distants restent des données non exécutées.

La station conserve les ETags de chaque page et réutilise les réponses inchangées, conformément aux [recommandations GitHub sur les requêtes conditionnelles](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api#use-conditional-requests). Un seul contrôle tourne pour tous les navigateurs. Le Pi conserve son échéance après redémarrage et rattrape une vérification due.

Les limites HTTP 403/429 respectent `Retry-After` et `X-RateLimit-Reset`. Une panne provoque un délai de reprise progressif de quinze minutes jusqu’à six heures; le contrôle manuel ne contourne pas ce délai. Après une réussite, un délai minimum d’une minute sépare deux contrôles. Les redirections sont refusées : si le dépôt change de nom ou d’adresse, modifier sa référence dans Configuration plutôt que transmettre le secret à une autre destination.

Un contrôle est limité à dix pages de cent releases, 2 Mo par page et un budget de trente secondes. Une liste incomplète, une réponse invalide ou une redirection produit une erreur explicite; elle n’est pas présentée comme un résultat à jour. Ces limites ne concernent pas le téléchargement de l’application, qui n’est pas réalisé par cette fonction.

Les réglages sont enregistrés dans **`updates-settings.json`**, avec droits `0600`. Le jeton n’est jamais renvoyé au navigateur, ajouté à un lien ou affiché dans les erreurs. L’état et les métadonnées nécessaires au cache sont dans **`updates-state.json`**, sans secret. Les changements de dépôt, de canal ou de secret invalident les résultats précédents; un contrôle lancé avec d’anciens réglages ne peut pas les remplacer.

Les sauvegardes chiffrées de configuration incluent les réglages GitHub et le jeton. Leur validation et leur restauration utilisent les mêmes règles que le formulaire. Après restauration, la station recharge ces réglages et invalide l’ancien état de vérification. La base courante utilise le **schéma 5**. Conserver les données et les sources sauvegardées avant toute mise à jour.

## Périmètre et vérification

L’inventaire, les notes, les modèles, les étiquettes, le lecteur, les caméras et l’imprimante restent indépendants. Aucun outil MCP, tâche cron, service système supplémentaire ou accès en écriture à GitHub n’est ajouté. Le MCP conserve douze outils.

Les vérifications logicielles et les limites matérielles de la version courante sont détaillées dans le [guide de vérification](08-verification-prototype.md).