# Assistant IA pour les étiquettes

Fonction de la version **v0.18.0**, accessible en mode local ou en accès réseau complet. Elle identifie une étiquette depuis une photo et présente des propositions à vérifier. Elle ne crée pas de bobine et n’écrit pas de tag.

## Configuration

Dans **Configuration → Assistant IA · Étiquettes**, renseigner une clé API OpenAI, choisir le modèle, cocher **Activer l’assistant IA** puis enregistrer. Le modèle initial, **gpt-5.4-mini**, accepte images, réponses structurées et recherche Web selon sa [documentation officielle](https://developers.openai.com/api/docs/models/gpt-5.4-mini).

**Compléter avec une recherche Web** recherche la fiche fabricant du produit identifié. Sans cette option, seules les informations de la photo sont proposées. Un champ de clé vide conserve la clé existante. La case d’effacement la supprime; désactiver aussi l’assistant pour enregistrer une configuration sans clé.

Les réglages sont dans `ai-settings.json` du répertoire de données, avec droits `0600`. Le navigateur reçoit uniquement la présence de la clé. Les sauvegardes de configuration incluent ces réglages et la clé, avec ou sans mot de passe selon la protection choisie. La restauration recharge l’assistant.

L’installateur utilise les dépendances épinglées existantes et laisse l’assistant désactivé à la première installation. Aucun compte ni clé n’est distribué. `.env.local` peut conserver une clé locale de développement; ce fichier est exclu de Git et n’est pas chargé automatiquement par la station. En utilisation normale, renseigner la clé dans Configuration.

Les [appels API sont facturés séparément de l’abonnement ChatGPT](https://help.openai.com/en/articles/9039756-managing-billing-for-chatgpt-and-the-api-platform), selon les crédits et limites du projet. La recherche Web peut ajouter des appels d’outil. Le logiciel ne lance aucune analyse automatiquement.

## Lire une étiquette

1. Dans **Lecture** ou **Écriture**, choisir **Identifier une étiquette avec l’IA**.
2. Prendre une photo avec le Pi, ou choisir un fichier JPEG, PNG ou WebP de moins de 4 Mo. La capture couleur est distincte du scan QR.
3. Vérifier netteté et cadrage. Une prise de photo seule n’envoie rien à OpenAI.
4. Cliquer sur **Analyser l’étiquette** pour envoyer cette image et effectuer la recherche facultative.
5. Vérifier les propositions, leur origine — étiquette ou Web —, les extraits justificatifs et les sources.
6. Choisir **Préremplir une nouvelle fiche** pour ouvrir Écriture. Cette action remplace sa saisie en cours. L’enregistrement et l’écriture RFID restent des actions séparées.

La fermeture de la fenêtre ou la perte d’accès empêche d’appliquer une réponse arrivée plus tard. Une requête déjà envoyée peut néanmoins se terminer côté fournisseur. Les captures sont temporaires et sont supprimées par le cycle habituel de la caméra; cette fonction n’ajoute pas de bibliothèque de photos.

## Données et limites

Les propositions concernent les données produit : famille/type de filament, marque, nom/référence, poids net nominal, diamètre, couleur explicitement documentée, densité, plages de températures et origine de fabrication explicitement connue. Les champs inconnus restent absents. La tare, le poids net réellement mesuré, la consommation, le restant et les identités individuelles ne sont pas déduits. Un nom de couleur ne devient pas une couleur hexadécimale estimée depuis la photo.

Une photo floue, une bobine réutilisée ou une référence ambiguë peut conduire à une identification incomplète ou incorrecte. Les propositions utilisent les règles de validation OpenPrintTag. Les contradictions, plages incohérentes et faits Web sans source consultée sont écartés. Les contenus distants restent des données, sans exécution d’instructions ou de HTML.

Le client utilise [Responses](https://developers.openai.com/api/reference/resources/responses/methods/create), les [images](https://developers.openai.com/api/docs/guides/images-vision), la [recherche Web](https://developers.openai.com/api/docs/guides/tools-web-search) et les [réponses structurées](https://developers.openai.com/api/docs/guides/structured-outputs). Les appels sont bornés, avec `store: false`. Une unique remise en forme, sans nouvelle photo ni recherche, peut suivre une réponse mal formée. Un second échec laisse la fiche intacte; il n’y a pas de changement silencieux de modèle.

## Connexion ChatGPT étudiée

OpenAI documente [Sign in with ChatGPT pour les applications libres et locales](https://developers.openai.com/siwc/token-sharing-open-source). Ce parcours demande une autorisation OAuth distincte, un identifiant d’hôte persistant, PKCE, la validation des jetons/permissions et leur renouvellement. Le [retour d’authentification utilise une adresse de boucle locale](https://developers.openai.com/siwc/token-sharing-open-source/sign-in); l’usage depuis un autre ordinateur que le Pi demande donc un parcours adapté.

Cette première version utilise la **clé API**. La connexion ChatGPT et le partage éventuel de l’usage d’un abonnement restent une intégration séparée à réaliser et qualifier. Les identifiants d’autres logiciels ne sont pas réutilisés.

## Vérification

Les tests contrôlent permissions, limites d’image, clé masquée, conflits, inconnues, données interdites, preuves Web, réponses invalides, remise en forme bornée, sauvegarde/restauration et absence d’écriture de stock ou de tag. Le moteur d’interface se vérifie avec `node tests/interface_assistant.cjs`.

Un essai API sur une étiquette de test ne qualifie pas tous les montages de caméra. Vérifier une photo réelle puis relire les propositions avant utilisation.
