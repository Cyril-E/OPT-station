# Notifications de l’imprimante dans Chrome

Un onglet OPT Station ouvert en arrière-plan suffit; il n’est pas nécessaire de laisser l’onglet interne **Imprimante** sélectionné. La surveillance n’ouvre aucune caméra et n’envoie aucune commande à l’imprimante.

## Activer sur un ordinateur

1. Ouvrir la station à son adresse **HTTPS**, après avoir approuvé son certificat selon le [guide HTTPS](31-https-local.md). Utiliser ensuite toujours cette adresse : les permissions et préférences sont propres au navigateur, à l’appareil et à l’adresse du site.
2. Activer l’accès complet dans **Configuration → Accès distant**, puis renseigner et tester PrusaLink dans **Imprimante et caméras**.
3. Dans **Configuration → Notifications Chrome**, cliquer sur **Autoriser les notifications**, puis accepter la demande de Chrome. OPT Station ne demande jamais cette autorisation à l’ouverture d’une page.
4. Vérifier **Activer les notifications sur ce navigateur**, puis choisir **Impression terminée** et/ou **Intervention requise ou erreur de l’imprimante**. Les choix sont mémorisés pour les prochaines visites; les réglages propres au navigateur ne font pas partie des sauvegardes de la station.
5. Cliquer sur **Envoyer une notification de test**. Elle ne simule aucune impression et ne modifie aucun inventaire. Un clic sur l’alerte ramène à l’onglet **Imprimante**.
6. Garder au moins un onglet OPT Station ouvert. Le suivi reste actif en arrière-plan et pendant l’utilisation des autres onglets internes.

Le navigateur affiche l’état du suivi et signale l’absence de permission, de connexion ou de configuration PrusaLink. Désactiver la case coupe l’abonnement aux alertes de ce navigateur. Les choix s’appliquent aussi aux autres onglets de la même adresse ouverts dans ce navigateur.

## Événements et absence de doublons

- **Fin réussie** : un travail identifié a été observé en impression, puis PrusaLink confirme explicitement sa fin avec des données cohérentes. Le nom du fichier précédemment observé est conservé. Un état Au repos, un arrêt, une erreur, une progression de 100 % ou une perte de connexion ne suffisent pas à confirmer la réussite.
- **Intervention** : transition vers **ATTENTION**, **ERROR** ou **PAUSED**. Une alerte couvre l’épisode, sans répétition à chaque lecture ni au passage d’un de ces états à l’autre. Une reprise puis une nouvelle intervention permet une nouvelle alerte. Le message `status_printer.message` est utilisé lorsqu’il est exposé avec `ok: false`; sinon, une invitation générale à vérifier l’écran de l’imprimante est affichée. Le motif exact dépend du firmware.
- **Ouverture et reconnexion** : l’état courant sert de point de départ silencieux. Une impression déjà terminée ou une intervention déjà présente n’est pas présentée comme un nouvel événement. Après une interruption, les anciens événements ne sont pas rejoués.
- **Plusieurs onglets Chrome** : identifiants communs côté station, verrou de navigateur et historique local borné évitent de répéter la même alerte sur une même adresse. Des appareils ou adresses de site différents ont leurs propres permissions et notifications.

Le flux est ouvert uniquement pour un navigateur ayant activé les alertes, autorisé les notifications et disposant de l’accès complet. Le serveur vérifie ces droits pendant le flux et coupe celui-ci en cas de retrait. Les mesures sont partagées avec le suivi existant et limitées par son cache; les images des caméras ne sont pas consultées. Les événements restent en mémoire, sans nouveau fichier de données ni migration de base. Le MCP reste inchangé.

## Si aucune alerte ne s’affiche

1. Vérifier le certificat, l’autorisation du site dans Chrome et la case d’activation dans OPT Station.
2. Vérifier que Chrome est autorisé à afficher les notifications dans les réglages du système. Le mode Concentration ou Ne pas déranger peut masquer leur affichage.
3. Utiliser le bouton de test. Si le test fonctionne mais pas les événements, vérifier l’état PrusaLink et observer une nouvelle impression ou intervention après l’activation.
4. Si l’économiseur de mémoire de Chrome met le site en veille, ajouter l’adresse de la station à **Toujours laisser ces sites actifs** dans **Paramètres → Performances**.

La fermeture de tous les onglets OPT Station, l’arrêt du navigateur, la veille de l’ordinateur ou la suspension de la page interrompent la réception. Aucun service Web Push n’est nécessaire pour ce périmètre. Après reprise, le suivi se reconnecte et attend les prochains événements.

## Vérification

Les essais couvrent les transitions, l’identité du travail, les réponses PrusaLink incohérentes, les annulations et les pannes; le flux HTTP réel, le retrait d’accès en cours de connexion et son nettoyage; le passage du flux par Caddy en HTTPS; les préférences, permissions, langues, clics, erreurs, cycles de veille et doublons entre onglets avec les API du navigateur contrôlées. La qualification logicielle courante est détaillée dans le [guide de vérification](08-verification-prototype.md). L’affichage d’une notification de test dans Chrome sur macOS et le déclenchement sur une vraie fin d’impression sont validés. Le déclenchement lors d’une intervention réelle reste à qualifier.

Références : [API Notifications](https://notifications.spec.whatwg.org/), [états PrusaLink](https://github.com/prusa3d/Prusa-Link-Web/blob/master/spec/openapi.yaml), [cycle de vie des pages Chrome](https://developer.chrome.com/docs/web-platform/page-lifecycle-api), [notifications dans Chrome](https://support.google.com/chrome/answer/3220216?hl=fr), [performances et sites actifs](https://support.google.com/chrome/answer/12929150?hl=fr).
