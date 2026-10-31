# Sauvegardes et restauration

Fonctions disponibles depuis **v0.10.0**, avec mot de passe facultatif à partir de **v0.17.1**, dans **Configuration → Sauvegardes et restauration**, utilisables sur le Pi et à distance avec l’accès complet. L’accès distant Inventaire n’autorise pas la lecture des réglages privés ni ces opérations.

## Télécharger une sauvegarde

1. Choisir **Configuration et inventaire**, **Inventaire et bibliothèque** ou **Configuration uniquement**.
2. Laisser **Protéger la sauvegarde par mot de passe** décoché pour télécharger sans mot de passe. Pour protéger le fichier, cocher cette case, saisir un mot de passe de 10 à 256 caractères et le confirmer.
3. Cliquer sur **Télécharger la sauvegarde**.
4. Conserver le fichier `.optbak`. Si une protection a été choisie, garder également son mot de passe.

Par défaut, la sauvegarde manuelle est **sans mot de passe**. Son contenu JSON est compressé et accompagné d’un contrôle d’intégrité SHA-256. Si la protection est activée, le fichier utilise **AES-256-GCM** et une clé dérivée du mot de passe par **scrypt**. Ce mot de passe manuel n’est pas enregistré sur le Pi. La restauration reconnaît automatiquement les deux formats; les anciennes sauvegardes chiffrées restent compatibles et demandent leur mot de passe d’origine.

Le fichier complet conserve :

- Inventaire actif et retiré, archives et compteur de bobines consommées.
- Identités, numéros B, séquence du prochain numéro, dates, données Main/Aux et historiques.
- Favoris et modèles avec leurs versions, carnet commun et notes par bobine.
- Sauvegardes NFC antérieures à l’écriture, binaires et métadonnées.
- Réglages persistants des accès distants, du MCP, de PrusaLink et des caméras, de l’imprimante d’étiquettes et de la planification des sauvegardes. Depuis `v0.11.0`, inclut aussi la détection GitHub et son jeton privé.

Les sauvegardes de configuration comprennent les identifiants PrusaLink et caméra. La clé privée utilisée pour les sauvegardes automatiques n’est jamais exportée. Les préférences de langue et de thème propres à un navigateur, Raspberry Pi OS, les fichiers système, le Wi-Fi, SSH, les services et les logiciels installés ne font pas partie de cette sauvegarde applicative. Les données de simulation et les données matérielles restent distinctes.

La limite est de **32 Mo pour le fichier** et **64 Mo pour son contenu décompressé**. Un dépassement produit une erreur explicite; aucune sauvegarde partielle n’est annoncée comme réussie.

## Restaurer un fichier

1. Choisir le fichier `.optbak`. Laisser le champ du mot de passe vide pour un fichier sans protection; sinon, saisir son mot de passe.
2. Cliquer sur **Vérifier avant restauration**. La station vérifie l’intégrité ou le chiffrement selon le fichier, le format, le mode matériel/simulation, le schéma, les données et les réglages, dans une base temporaire séparée.
3. Lire la date, la version et le résumé : nombre de bobines, d’archives et de fiches, et configuration concernée.
4. Cocher la confirmation du remplacement puis cliquer sur **Restaurer les données**.
5. Après le rechargement, vérifier le stock, les appareils et le niveau d’accès distant si la configuration était incluse.

Seule la partie choisie lors de la création du fichier est remplacée. Les données créées ensuite disparaissent de cette partie restaurée. Les notes et les consommations prennent les valeurs du fichier. Les numéros encore présents sont conservés; le compteur du prochain numéro ne redescend jamais sous celui déjà atteint par la station. Les versions sont renouvelées pour refuser les anciens formulaires ouverts dans d’autres navigateurs.

L’aperçu expire après dix minutes. Une modification de l’inventaire ou des réglages après l’aperçu oblige à le reprendre. La restauration attend la fin des opérations et demande l’arrêt d’un scan QR actif. Aucune lecture/écriture NFC, impression d’étiquette ou commande d’alimentation n’est déclenchée par la restauration.

Les sauvegardes planifiées sont **désactivées après une restauration de configuration**, jusqu’à vérification du support et réactivation explicite. Le mode réseau et l’activation MCP du fichier sont restaurés : leur effet figure dans la confirmation. Une restauration Inventaire conserve les réglages actuels.

Les fichiers contiennent des lignes de données JSON validées, jamais du SQL ni un schéma exécutable provenant du fichier. La structure SQLite vient toujours du logiciel installé. Les nouvelles sauvegardes utilisent le schéma d’inventaire **5**, avec le statut En stock / En service. La restauration des anciennes sauvegardes de schéma **4** reste prise en charge; leur statut est initialisé selon l’identification QR/RFID. Les autres schémas sont refusés explicitement.

## Revenir sur une restauration

Avant tout remplacement, la station crée un **point de retour local privé**, dans `restore-points/<identifiant>/` sous son dossier de données. Il contient la base SQLite cohérente et les réglages précédents, avec droits privés sur le Pi. Ces copies locales ne sont pas des fichiers de partage chiffrés : ne pas les transmettre.

Ouvrir **Points de retour locaux**, choisir la date, puis **Vérifier le point de retour**. Le résumé et la confirmation habituels permettent de restaurer l’état précédent sans recycler les numéros déjà attribués. Les vingt points les plus récents sont proposés; aucun point n’est supprimé automatiquement.

En cas d’échec pendant la restauration, la station rétablit le point précédent. Si le processus est interrompu pendant le remplacement de plusieurs fichiers, son journal de restauration permet de rétablir l’état précédent **avant de rouvrir l’application au démarrage**. Les sauvegardes NFC déjà présentes sont conservées; un fichier du même nom avec un contenu différent bloque le remplacement.

Cette fonction ne remplace pas une sauvegarde externe : la perte du disque du Pi ferait aussi perdre ses points de retour.

## Sauvegardes automatiques

1. Brancher un disque externe inscriptible, ou monter un partage réseau sur le Pi.
2. Dans **Sauvegardes automatiques planifiées**, choisir le support et un sous-dossier, par exemple `opt-station-backups`.
3. Choisir une fréquence quotidienne ou hebdomadaire, le jour si nécessaire, l’heure et le fuseau horaire. Valeurs initiales : **02:00, Europe/Paris, 14 copies conservées**.
4. Choisir de protéger ou non les sauvegardes avec **Protéger les sauvegardes planifiées par mot de passe**, puis activer la planification. Sans protection, aucun mot de passe ni clé enregistrée n’est nécessaire.
5. Cliquer sur **Enregistrer la planification**, puis **Sauvegarder maintenant sur le support** pour vérifier la destination.

Si la protection est activée, une clé dérivée, et non le mot de passe en clair, est conservée dans `backup-key.json`, avec droits `0600`, pour le chiffrement sans intervention. Elle n’est pas renvoyée au navigateur ni incluse dans les sauvegardes. Un changement de mot de passe ne change pas celui des anciens fichiers. Désactiver la protection supprime la clé automatique enregistrée, sans modifier les fichiers déjà créés. Les planifications existantes conservent leur protection tant que ce choix n’est pas changé; les nouvelles planifications proposent par défaut des fichiers sans mot de passe.

Les sauvegardes automatiques prennent toujours **configuration et inventaire**. Le bouton de copie immédiate utilise les réglages enregistrés; enregistrer d’abord les modifications du formulaire. La date du prochain passage, le dernier essai et son résultat sont affichés. Après un arrêt du Pi ou une destination temporairement indisponible, la station effectue au plus un rattrapage pour la dernière échéance; les échecs sont retentés au plus toutes les quinze minutes. Un changement d’heure ne provoque pas deux copies pour la même échéance.

La copie utilise un fichier temporaire, une publication atomique et une vérification du contenu enregistré avant d’annoncer la réussite. La rétention ne supprime que les sauvegardes automatiques appartenant à cette station et à ce mode, après une nouvelle copie réussie. Elle ne touche pas aux autres fichiers du support.

La station relève les supports montés dans la table du système et vérifie leur identité, leurs droits et l’espace libre. Un support absent, remplacé, en lecture seule ou un dossier traversant un lien symbolique est refusé. Les écritures restent attachées au support ouvert pour éviter tout repli sur le disque système s’il disparaît pendant la copie. L’application ne formate aucun disque, ne monte aucun partage et ne demande aucun identifiant réseau : le montage relève de l’administration du Pi.

La destination doit être inscriptible et déjà montée; un support d’installation en lecture seule est refusé. Le moteur est qualifié sur des destinations temporaires représentant les montages. La création manuelle sur USB, le contrôle d’intégrité et l’aperçu de restauration sont validés, sans restauration du stock réel. L’exécution nocturne planifiée sur un support externe reste à qualifier; activer la planification seulement après vérification de la destination.

## Installation et qualification

Ces fonctions utilisent la dépendance `cryptography`, déjà épinglée à `50.0.2` dans `requirements.lock`. Sur une installation existante, sauvegarder les données serveur arrêté, installer les nouvelles sources et exécuter dans leur dossier :

```sh
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --only-binary=:all: -r requirements.lock -r requirements-camera.lock
```

Conserver les autres commandes d’installation du [guide de station réelle](12-installation-station-reelle.md). Aucune nouvelle autorisation système ou tâche cron n’est nécessaire : le planificateur tourne avec le service existant et s’arrête avec lui. Depuis `v0.9.0`, le schéma SQLite passe de **3 à 4** pour les numéros et les notes. Un retour à `v0.9.0` nécessite les anciennes sources et la base sauvegardée ensemble. Depuis `0.14.0.dev0`, une migration **4 vers 5** ajoute le statut d’utilisation, indépendant du QR/RFID. Conserver les sources et la base d’avant migration ensemble pour un retour à une version antérieure.

Les essais couvrent les sauvegardes et restaurations sans mot de passe, le contrôle d’intégrité et les limites de décompression, la compatibilité des anciennes planifications, l’activation et la désactivation du chiffrement, chiffrement et mauvais mot de passe, fichiers altérés/incompatibles, limites de taille, conservation des données, conflits, imports transactionnels, restauration complète et partielle, retour arrière et journal après interruption, planification quotidienne/hebdomadaire et changements d’heure, rétention, support absent ou non inscriptible et absence de repli sur le disque système. Les écritures et restaurations d’essai restent sur des données temporaires séparées du stock réel.
