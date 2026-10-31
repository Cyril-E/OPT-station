# Connexion ChatGPT de l’assistant IA

Dans **Paramètres → Assistant IA · Étiquettes**, choisir **Clé API OpenAI** ou **Compte ChatGPT**. Le choix est enregistré sur la station. Les deux accès sont indépendants : une limite ou un refus ChatGPT n’entraîne pas de basculement vers les crédits API.

## Avant de commencer

- Sur le Pi, ouvrir OPT Station dans son navigateur.
- Depuis un autre ordinateur, ouvrir l’adresse **HTTPS** de la station et activer son accès complet dans **Paramètres → Accès distant**. La connexion doit déjà être reconnue comme sécurisée par le navigateur.
- Prévoir de conserver les deux onglets ouverts : **OPT Station** et celui qu’ouvre **OpenAI**.

Le courriel OpenAI confirme que l’application a reçu une autorisation. **Ce courriel ne termine pas la connexion dans OPT Station.** Le compte et les modèles apparaissent seulement après validation du retour décrit ci-dessous.

## Depuis l’écran du Pi

1. Ouvrir **Paramètres → Assistant IA · Étiquettes**.
2. Dans **Accès de l’assistant**, choisir **Compte ChatGPT**.
3. Cliquer sur **Continuer avec ChatGPT**. Si la nouvelle fenêtre est bloquée, cliquer sur **Ouvrir la connexion ChatGPT** dans la connexion en cours.
4. Dans l’onglet OpenAI, se connecter, vérifier le nom **OPT Station** et autoriser l’utilisation du forfait ChatGPT. La disponibilité dépend du compte, de l’espace choisi et de leurs autorisations.
5. Le retour local affiche une confirmation. Revenir dans l’onglet **OPT Station** : le compte et la liste des modèles doivent apparaître automatiquement.
6. Choisir un modèle compatible avec les images, les réponses structurées et, si elle est activée, la recherche Web.
7. Cocher **Activer l’assistant IA**, régler la recherche Web et cliquer sur **Enregistrer l’assistant IA**.
8. Vérifier le message **ChatGPT connecté et assistant prêt.**

## Depuis un Mac ou un PC du réseau

Le parcours OpenAI utilise une adresse de retour **HTTP sur `127.0.0.1`**, avec un port temporaire et le chemin `/auth/callback`. Cette adresse vise l’ordinateur qui ouvre le navigateur.

Depuis un autre ordinateur, cette adresse ne peut pas joindre le navigateur du Pi. Une page **« Ce site est inaccessible »**, **« Impossible de se connecter »** ou une connexion refusée sur `http://127.0.0.1:…` est donc attendue après l’autorisation. **Garder cet onglet ouvert : c’est son adresse qu’il faut copier.** L’onglet OPT Station reste, lui, en HTTPS.

1. Dans OPT Station, ouvrir **Paramètres → Assistant IA · Étiquettes** et choisir **Compte ChatGPT**.
2. Cliquer sur **Continuer avec ChatGPT**, ou sur **Ouvrir la connexion ChatGPT** si la fenêtre a été bloquée.
3. Dans l’onglet OpenAI, se connecter et autoriser **OPT Station**, y compris l’utilisation du forfait si elle est proposée.
4. Quand l’onglet arrive sur la page d’erreur `http://127.0.0.1:…`, sélectionner **toute la barre d’adresse** : **⌘L sur Mac**, **Ctrl+L sur Windows/Linux**.
5. Copier l’adresse sélectionnée : **⌘C sur Mac**, **Ctrl+C sur Windows/Linux**. Copier l’adresse entière, y compris tous les paramètres après `?`.
6. Revenir à l’onglet **OPT Station**, dans la même tentative de connexion.
7. Cliquer dans **Adresse complète de l’onglet de retour OpenAI**, puis coller avec **⌘V sur Mac** ou **Ctrl+V sur Windows/Linux**.
8. Cliquer sur **Terminer la connexion**, puis attendre la vérification. Le champ doit se vider, le compte doit apparaître et la liste des modèles doit se remplir.
9. Choisir un modèle, cocher **Activer l’assistant IA**, régler la recherche Web puis cliquer sur **Enregistrer l’assistant IA**.
10. Vérifier **ChatGPT connecté et assistant prêt.** L’onglet de retour peut alors être fermé.

Exemple **fictif** de la forme d’une adresse de retour; copier sa propre adresse, jamais cet exemple :

```text
http://127.0.0.1:12345/auth/callback?code=CODE_TEMPORAIRE&state=ETAT_DE_LA_TENTATIVE&client_id=CLIENT_ATTRIBUE
```

Le port et les paramètres peuvent varier. Conserver exactement l’adresse produite, sans remplacer `127.0.0.1` par l’adresse du Pi. **Ne copier ni le lien du courriel, ni l’adresse de la page de connexion OpenAI, ni seulement la valeur du code.** Le retour complet contient un code temporaire destiné uniquement au formulaire OPT Station; ne pas le publier dans une issue, un message ou une capture.

## Si les modèles n’apparaissent pas

| Ce qui est affiché | Étape à effectuer |
| --- | --- |
| Connexion en attente, aucun compte enregistré, champ de retour vide | Copier l’adresse de l’onglet `http://127.0.0.1:…`, la coller dans le formulaire et cliquer sur **Terminer la connexion**. |
| Compte connecté, utilisation du forfait non autorisée | Cliquer sur **Continuer avec ChatGPT** pour accorder cette autorisation au compte choisi. |
| Compte connecté et autorisé, mais catalogue vide | Cliquer sur **Actualiser les modèles ChatGPT**; conserver le message d’erreur éventuel. |
| Modèles visibles, mais assistant non enregistré | Choisir un modèle puis cliquer sur **Enregistrer l’assistant IA**. |
| Tentative expirée ou onglet de retour fermé | Cliquer sur **Annuler la connexion**, puis **Continuer avec ChatGPT** et suivre une nouvelle tentative complète. |

La tentative expire après **dix minutes**. Un redémarrage de la station nécessite aussi une nouvelle tentative. Il n’est pas nécessaire de déconnecter un compte déjà fonctionnel pour relire la procédure : le volet **Connexion ChatGPT : procédure pas à pas** reste accessible dans les paramètres.

Un rechargement ou une réouverture des paramètres retrouve la connexion en cours et ses commandes de retour/annulation, tant que la station n’a pas redémarré et que la tentative n’a pas expiré. Une interruption réseau temporaire ne l’annule pas. Aucun code de retour ni jeton n’est enregistré dans le stockage du navigateur.

## Comptes et accès

Le compte connecté apparaît dans le sélecteur. **Ajouter un compte** crée une connexion distincte; plusieurs inscriptions avec la même adresse électronique restent séparées. **Déconnecter ce compte** arrête son utilisation, tente de révoquer sa session et efface les jetons locaux. Si la révocation distante n’a pas pu être confirmée, l’interface l’indique et propose les réglages ChatGPT pour vérifier l’accès.

Le choix entre clé API et compte ChatGPT devient effectif après **Enregistrer l’assistant IA**. Un compte déjà connecté peut être utilisé sans refaire cette procédure à chaque analyse.

## Session, données et sauvegardes

- L’application utilise son propre enregistrement OpenAI **OPT Station**, un identifiant stable de station, PKCE et la vérification de l’identité signée. Elle n’utilise pas les identifiants d’un autre logiciel.
- Les jetons sont conservés dans `chatgpt-credentials.json`, dans le répertoire de données de la station, avec permissions `0600` et écritures atomiques. Ils ne sont pas renvoyés au navigateur. Les renouvellements sont sérialisés et conservent le dernier jeton de renouvellement reçu.
- Le fichier de connexion et l’identifiant propre à la station **ne sont pas inclus dans les fichiers `.optbak`**. Une restauration de configuration conserve la connexion déjà présente sur cette station. Sur une autre installation, reconnecter le compte ChatGPT. Les réglages de choix de l’accès et du modèle sont inclus dans la configuration sauvegardée.
- La clé API existante reste enregistrée tant qu’elle n’est pas effacée explicitement. Revenir à **Clé API OpenAI** puis enregistrer choisit cet accès.
- L’analyse envoie la photo uniquement après **Analyser l’étiquette**. L’utilisation, les autorisations et les limites du compte sont consultables dans **Utilisation et limites dans ChatGPT**.
- Les propositions, sources et champs inconnus conservent les mêmes règles qu’avec la clé API. L’analyse ne modifie ni l’inventaire ni le RFID.

## Contrat utilisé et vérification

Sources officielles : [inscription et connexion](https://developers.openai.com/siwc/token-sharing-open-source/sign-in), [comptes et sessions](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions), [modèles et inférence](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference), [limites du parcours](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

Les requêtes ChatGPT utilisent l’API Responses publique, `store: false` et `stream: true`. Les paramètres non pris en charge, dont `max_output_tokens` et `max_tool_calls`, sont retirés. Un résultat n’est accepté qu’après `response.completed`; un flux interrompu ou une limite d’abonnement reste une erreur. Le modèle provient du catalogue du compte, sans remplacement silencieux.

Les essais automatisés utilisent des comptes et jetons fictifs, des identités signées par une clé de test et des réponses contrôlées. La connexion réelle exige l’autorisation du propriétaire du compte dans le parcours OpenAI.
