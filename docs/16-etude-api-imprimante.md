# Étude des API imprimante — Prusa CORE One

Étude du **25 octobre 2026**, pour l’onglet **Imprimante** d’OPT Station. Le profil étudié est une **Prusa CORE One**, firmware **8.0.0+17068**. Les adresses, identifiants et clés seront saisis dans **Configuration**.

## Orientation proposée

Commencer par **PrusaLink, directement sur le réseau local**, pour le suivi du travail et les températures. Ajouter ensuite les commandes compatibles, puis les caméras et les compléments Prusa Connect. Cette organisation permet au suivi local de fonctionner sans connexion au cloud. Prusa distingue bien le service local PrusaLink du service cloud Connect dans son [guide de présentation](https://help.prusa3d.com/article/prusa-connect-and-prusalink-explained_302608).

Les possibilités ci-dessous viennent des sources officielles. **Aucune connexion à l’imprimante et aucune commande physique n’ont été exécutées pendant cette étude.** Le code public Buddy consulté précède le firmware 8 : il donne une base concrète, mais la compatibilité exacte avec `8.0.0+17068` devra être vérifiée par des lectures sur la machine.

| Fonction souhaitée | PrusaLink intégré : base vérifiée dans le code public | Prusa Connect : contrat publié | Proposition pour OPT Station |
| --- | --- | --- | --- |
| État et travail en cours | État, nom du fichier, progression, durées | Imprimantes, télémétrie et travaux | Première étape en local |
| Températures | Buse et plateau, mesures et consignes | Buse et plateau dans le schéma consulté | Première étape; chambre conditionnelle |
| Pause, reprise, arrêt | Routes explicites avec contrôle du travail courant | Commandes explicites | Après validation de la lecture |
| Fichiers | Liste, métadonnées, transfert, lancement et suppression | Stockages et lancement de fichiers | Étape ultérieure, actions explicites |
| Historique et file d’attente cloud | Pas d’historique complet établi par les routes étudiées | Routes dédiées | Complément Connect optionnel |
| Images de l’imprimante | Aucune route caméra dans le gestionnaire Buddy étudié | Caméras et URLs d’images | Connexion caméra distincte |
| Consommation et bobine chargée | Réponse du firmware 8 à examiner | Nouvelles données annoncées par le firmware 8; lecture client à confirmer | Aucune modification automatique du stock à ce stade |

Les bases techniques de cette comparaison sont la [spécification PrusaLink](https://github.com/prusa3d/Prusa-Link-Web/blob/a67f306bc878009be0e27864a01a1837e5c4cf06/spec/openapi.yaml), le [gestionnaire embarqué Buddy](https://github.com/prusa3d/Prusa-Firmware-Buddy/blob/1ce23f33ed3b94e26aa33a44557d6c4a4be11eb6/lib/WUI/link_content/prusa_link_api_v1.cpp) et la [documentation de l’API mobile Connect](https://connect-mobile-api.prusa3d.com/api/docs).

## PrusaLink local : informations et commandes

Le schéma général PrusaLink couvre aussi les installations sur Raspberry Pi destinées à d’anciennes imprimantes. La présence d’une fonction dans ce schéma ne suffit donc pas à la déclarer disponible sur la CORE One. Les routes suivantes sont également présentes dans le code embarqué étudié.

| Requête | Utilité |
| --- | --- |
| `GET /api/version` | Firmware, type de machine et capacités, dont `upload-by-put` |
| `GET /api/v1/info` | Identité et informations techniques, notamment diamètre de buse |
| `GET /api/v1/status` | État, températures, progression, durées, transfert éventuel |
| `GET /api/v1/job` | Travail courant et références du fichier; `204` s’il n’y en a aucun |
| `GET /api/v1/storage` | Stockage disponible, notamment support USB |
| `GET /api/v1/transfer` | Transfert en cours; `204` en son absence |
| `GET /api/v1/files/{storage}/{path}` | Dossier ou métadonnées d’un fichier |
| `PUT /api/v1/job/{id}/pause` | Mettre le travail courant en pause |
| `PUT /api/v1/job/{id}/resume` | Reprendre le travail courant |
| `DELETE /api/v1/job/{id}` | Arrêter le travail courant |
| `PUT /api/v1/files/{storage}/{path}` | Téléverser un fichier |
| `POST /api/v1/files/{storage}/{path}` | Lancer l’impression d’un fichier présent |
| `DELETE /api/v1/files/{storage}/{path}` | Supprimer un fichier ou dossier |

Sources : [routes v1](https://github.com/prusa3d/Prusa-Firmware-Buddy/blob/1ce23f33ed3b94e26aa33a44557d6c4a4be11eb6/lib/WUI/link_content/prusa_link_api_v1.cpp) et [réponses d’identité et de travail](https://github.com/prusa3d/Prusa-Firmware-Buddy/blob/1ce23f33ed3b94e26aa33a44557d6c4a4be11eb6/lib/WUI/link_content/basic_gets.cpp).

Pour l’affichage initial, retenir : état de connexion, état de l’imprimante, fichier et miniature lorsqu’elle est fournie, pourcentage, temps écoulé, temps restant estimé, températures mesurées et demandées de la buse et du plateau, modèle et firmware. La vitesse, le débit, la hauteur Z et les régimes des ventilateurs peuvent former un panneau de détails. Les positions X/Y ne sont pas toujours transmises pendant une impression. Voir le [rendu de la réponse status](https://github.com/prusa3d/Prusa-Firmware-Buddy/blob/1ce23f33ed3b94e26aa33a44557d6c4a4be11eb6/lib/WUI/nhttp/status_renderer.cpp).

La progression v1 est exprimée en pourcentage et les durées en secondes. Une valeur absente reste inconnue; une coupure réseau conserve la dernière mesure avec sa date. Le temps restant et l’heure de fin doivent être présentés comme des estimations. Un éventuel adaptateur aux anciennes routes devra normaliser leurs unités séparément.

Les commandes utilisent l’identifiant du travail : le code renvoie `404` si cet identifiant n’est plus courant et `409` si l’état interdit l’action. Pause et reprise sont limitées aux états attendus. Pour les futurs transferts, conserver explicitement **`Print-After-Upload: ?0`** et **`Overwrite: ?0`** par défaut, puis proposer séparément le lancement ou le remplacement. Voir les [règles d’envoi de la spécification](https://github.com/prusa3d/Prusa-Link-Web/blob/a67f306bc878009be0e27864a01a1837e5c4cf06/spec/openapi.yaml).

Les routes locales de chauffage manuel, déplacement, homing, éclairage, ventilation ou G-code arbitraire ne sont pas établies par le gestionnaire étudié. Le namespace de compatibilité `/api/printer` ne signifie pas que toutes les commandes OctoPrint sont disponibles. Les fonctions `/cameras`, `/update` et `/job/{id}/continue` du schéma général ne seront pas promises sur cette machine sans preuve supplémentaire.

### Authentification locale

Le code public gère **HTTP Digest** et **`X-Api-Key`**. PrusaSlicer prend lui aussi ces deux modes en charge. Prévoir le choix dans Configuration, avec Digest en premier et des identifiants configurables; valider le mode réellement accepté par le firmware 8. Les identifiants PrusaLink sont distincts des accès cloud Connect. Sources : [authentification Buddy](https://github.com/prusa3d/Prusa-Firmware-Buddy/blob/1ce23f33ed3b94e26aa33a44557d6c4a4be11eb6/lib/WUI/nhttp/req_parser.cpp), [client PrusaLink de PrusaSlicer](https://github.com/prusa3d/PrusaSlicer/blob/30ef59195e0f3ee6f270b185bb5f9fb5f349f81f/src/slic3r-shared/src/Slic3r/Biz/PrintHost/PrintHostPrusaLink.cpp).

## Prusa Connect : compléments possibles

Prusa publie une **API mobile Connect**, présentée comme la passerelle de son application. Son [schéma OpenAPI](https://connect-mobile-api.prusa3d.com/api/docs.jsonopenapi), version `0.0.1-dev` lors de l’étude, décrit notamment :

| Groupe de routes | Apport possible |
| --- | --- |
| `GET /api/v1/printers`, `/printers/{uuid}`, `/printers/{uuid}/detail` | Imprimantes, identité, état, télémétrie et droits |
| `GET /api/v1/jobs`, `/jobs/{id}` | Historique et détails des travaux |
| `GET /api/v1/printers/{printerUuid}/queue` | File d’attente |
| `GET /api/v1/storage/printer/{printerUuid}`, `/storage/{teamId}` | Fichiers de l’imprimante et du cloud |
| `PUT /api/v1/printers/{printerUuid}/command/...` | Pause, reprise, arrêt, prêt/non prêt, lancement depuis plusieurs sources |
| `GET /api/v1/cameras`, `/cameras/{cameraToken}` | Caméras, droits et URLs d’images |
| `GET /api/v1/material-data/{spoolId}` | Fiche matière et identifiants de bobine |

Les actions dépendent des droits `canRead`, `canUse` et `canManage`. Le schéma du corps de `/command/control` n’est pas suffisamment détaillé pour implémenter des réglages avancés avec un contrat fiable.

L’authentification publiée utilise un **jeton utilisateur JWT dans `Authorization`**. Le schéma consulté ne décrit pas sa délivrance ni son renouvellement pour une application tierce. Le [client Connect de PrusaSlicer](https://github.com/prusa3d/PrusaSlicer/blob/30ef59195e0f3ee6f270b185bb5f9fb5f349f81f/src/slic3r-shared/src/Slic3r/Biz/PrintHost/PrintHostPrusaConnect.cpp) utilise également un jeton Bearer, ce qui ne suffit pas à établir un parcours d’autorisation réutilisable par OPT Station. Il faut confirmer ce parcours avant de proposer une connexion cloud durable; aucune clé locale PrusaLink ou caméra ne sera supposée interchangeable.

Le [Prusa Connect Printer SDK](https://github.com/prusa3d/Prusa-Connect-SDK-Printer) sert à enregistrer une imprimante et à envoyer sa télémétrie vers Connect. Ce rôle est différent de celui d’OPT Station, qui souhaite consulter et commander une CORE One déjà enregistrée.

### Firmware 8, OpenPrintTag et inventaire

Le [changelog officiel CORE One](https://help.prusa3d.com/changelog/core-one) du 22 octobre annonce les UUID de filament et l’envoi à Connect des informations par outil, du poids consommé, du matériau chargé et du poids de bobine. Cela ouvre une piste de rapprochement avec l’identité OpenPrintTag.

Cependant, le schéma client consulté ne documente pas encore les poids consommés dans la télémétrie; la fiche `MaterialData` contient des caractéristiques et masses initiales, sans consommation courante documentée. **Émission par l’imprimante et disponibilité dans une API cliente restent deux preuves distinctes.** La température de chambre devra également être confirmée dans les réponses accessibles.

Avant toute synchronisation de stock, vérifier l’UUID d’instance de la bobine, les unités, la signification des masses, les réinitialisations et la fraîcheur des données. Ne pas transformer une estimation de consommation du fichier en consommation réelle. Le fonctionnement actuel, fondé sur la relecture NFC, reste la référence tant que ce rapprochement n’est pas validé.

## Caméras de l’imprimante

La caméra QR OV5647 du Pi et une caméra de surveillance de l’imprimante auront des configurations et des usages distincts.

Pour une **Buddy3D compatible**, Prusa documente un flux local **`rtsp://<adresse-camera>/live`**. Vérifier le modèle et le firmware de chaque caméra avant intégration. Une page web ne lit pas directement ce flux RTSP : une passerelle sur le Pi vers un format navigateur serait nécessaire. Les images périodiques constituent une première intégration plus légère. Source : [guide officiel Buddy3D](https://help.prusa3d.com/article/buddy3d-camera_821264).

L’API mobile Connect expose des URLs de snapshots et une route de configuration WebRTC. Cette dernière fournit des paramètres ICE, sans documenter à elle seule tout le protocole de session. Le guide Buddy3D indique encore des limites de lecture dans le navigateur : il faut vérifier les capacités du modèle réel avant de promettre une vidéo WebRTC.

L’ancienne [Camera API Connect est dépréciée](https://connect.prusa3d.com/docs/cameras/). Le nouveau [Camera Service](https://camera-service.prusa3d.com/docs/openapi.yaml) sert à **publier** les informations et images d’une caméra vers Connect (`/v1/camera-info`, `/v1/snapshot`), avec ses propres jeton et empreinte. Il ne fournit pas une route générale de téléchargement des images des caméras déjà associées au compte.

## Configuration et comportement proposés

| Partie de Configuration | Données à prévoir |
| --- | --- |
| Imprimante locale | Activation, nom, adresse IP ou nom réseau, protocole/port, mode d’authentification, utilisateur si nécessaire, secret masqué, bouton **Tester la connexion** |
| Prusa Connect, optionnel | Connexion au compte selon un parcours officiellement confirmé, sélection de l’imprimante et de l’équipe autorisées |
| Caméra de l’imprimante, optionnelle | Source d’image ou flux, adresse propre à la caméra, protocole et authentification éventuelle |

**Tester la connexion** effectuera uniquement des lectures : version, informations, état et travail courant. Il devra distinguer adresse injoignable, mauvais identifiants, accès refusé et route non prise en charge. Aucune pause, chauffe ou impression ne sera déclenchée par ce test.

Les requêtes vers l’imprimante partiront du **serveur du Pi**. Les clés resteront dans ses données privées, hors Git, avec permissions restreintes, et ne seront renvoyées ni aux pages publiques de Configuration ni aux journaux. Une lecture de configuration indiquera seulement si un secret est enregistré. Les sauvegardes qui le contiennent seront privées.

Proposition cohérente avec les niveaux actuels : accès local ou **complet avec code** pour enregistrer les connexions, consulter les images et commander la machine; accès public existant conservé pour l’inventaire, les modèles et les réglages non sensibles. Les réglages de partage réseau restent réservés à l’adresse locale du Pi, comme aujourd’hui.

Un collecteur commun sur le Pi pourra interroger l’état toutes les **5 secondes pendant l’impression**, plus lentement au repos, puis distribuer le même résultat aux navigateurs. Ce rythme est une proposition à ajuster aux essais. Prévoir délais bornés, ralentissement après échec, date de dernière mesure et indication des données périmées. Les informations stables seront relues moins souvent.

Pour les commandes : vérifier le travail et l’état juste avant l’action, demander confirmation pour démarrer ou arrêter une impression et pour supprimer/remplacer un fichier, puis relire l’état. Si la réponse est perdue, vérifier le résultat avant toute nouvelle tentative; éviter de renvoyer automatiquement une action dont l’issue est inconnue.

## Ordre de réalisation recommandé

1. **Configuration et suivi local en lecture seule** : connexion PrusaLink, identité, état, fichier, progression, durées, températures et miniature disponible. Qualifier les réponses réelles de `8.0.0+17068`, au repos et pendant une impression en cours.
2. **Commandes locales** : pause/reprise/arrêt avec droits, états et confirmations; gestion des fichiers dans une étape distincte.
3. **Caméra et compléments cloud** : confirmer le modèle de caméra, intégrer images ou passerelle vidéo, établir l’autorisation Connect, puis étudier historique, file d’attente et données de bobines.

Une première intégration en lecture seule et quatre emplacements de caméras sont réalisés dans **`0.5.0.dev0`**; voir le [guide imprimante et caméras](17-suivi-imprimante-et-cameras.md). Le suivi PrusaLink sur firmware 8 a ensuite été qualifié au repos et en impression. L’autorisation Connect pour un client tiers et les consommations récupérables restent à vérifier. Les adresses caméra et identifiants se règlent dans Configuration.

## Sources et traçabilité

Sources officielles consultées le 25 octobre 2026. Le profil de référence utilise une CORE One en firmware 8.0.0+17068; un autre modèle ou firmware doit être vérifié séparément.

| Référence | Version ou empreinte de la copie étudiée |
| --- | --- |
| [PrusaLink OpenAPI v1](https://github.com/prusa3d/Prusa-Link-Web/blob/a67f306bc878009be0e27864a01a1837e5c4cf06/spec/openapi.yaml) | `1.0.0-draft`; commit `a67f306bc878009be0e27864a01a1837e5c4cf06`; SHA-256 `e0a5f7abc4df5d4043fb1115cdca6b6ca45bbc549060f27896c6290b05aff976` |
| [PrusaLink legacy OpenAPI](https://github.com/prusa3d/Prusa-Link-Web/blob/a67f306bc878009be0e27864a01a1837e5c4cf06/spec/openapi-legacy.yaml) | SHA-256 `9afff257fa9257506bbbb95811be1e6f13399a9d56d2cdc57eaa3ae0f6d991a3` |
| [Firmware Buddy](https://github.com/prusa3d/Prusa-Firmware-Buddy/tree/1ce23f33ed3b94e26aa33a44557d6c4a4be11eb6) | Commit public `1ce23f33ed3b94e26aa33a44557d6c4a4be11eb6` du 27 août 2026, antérieur au firmware cible |
| [API mobile Connect](https://connect-mobile-api.prusa3d.com/api/docs.jsonopenapi) | `0.0.1-dev`; SHA-256 `68551df32125f6443a818d04a46809a28e7f7fa3dbe9adaedfa76ba88cde2102` |
| [Camera Service OpenAPI](https://camera-service.prusa3d.com/docs/openapi.yaml) | Version `1`; SHA-256 `b28c1040a409fc8f41a91291be0363be5c1fdf1b7b9be40f5199aa428d079e02` |
| [Clients PrusaSlicer](https://github.com/prusa3d/PrusaSlicer/tree/30ef59195e0f3ee6f270b185bb5f9fb5f349f81f) | Commit `30ef59195e0f3ee6f270b185bb5f9fb5f349f81f` |

Les copies de travail, résumés de routes et manifestes d’empreintes sont conservés localement dans `var/prusa-api-study/`, exclu de Git. Ce dossier contient uniquement les références publiques utilisées pour l’étude.
