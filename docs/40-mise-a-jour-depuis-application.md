# Mise à jour depuis l’application

Fonction disponible depuis **v0.26.0**. La détection des versions et leurs notes restent décrites dans le [guide de recherche de versions](27-detection-mises-a-jour.md).

## Utiliser le bouton

1. Dans **Paramètres → Mises à jour d’OPT Station**, activer la recherche des versions. Les préversions actuelles nécessitent de conserver **Inclure les préversions** coché.
2. Quand une version plus récente est proposée, consulter ses nouveautés si souhaité, puis cliquer **Mettre à jour**. Le bouton est présent dans le bandeau, dans la fenêtre des nouveautés et dans Paramètres.
3. Laisser le Pi alimenté. La page affiche l’avancement, puis se reconnecte automatiquement pendant le redémarrage de l’application. Aucun redémarrage du Pi n’est lancé.

Le bouton exige l’accès local sur le Pi ou l’accès complet depuis le réseau. L’accès Inventaire permet de consulter les versions et l’avancement. Les réglages GitHub modifiés doivent être enregistrés avant l’installation. Une opération NFC, un scan QR, une analyse IA, une impression d’étiquette ou une sauvegarde en cours doit être terminée avant le lancement.

La mise à jour commence uniquement sur demande : une nouvelle publication ou un redémarrage du Pi ne lance aucune installation spontanée. Si la réponse au clic est perdue, la page recherche le résultat ; elle ne renvoie pas automatiquement une seconde demande.

## Installation initiale du service

Les installations et réinstallations faites avec l’[installateur en une commande](33-installation-une-commande.md) depuis v0.26.0 incluent et activent automatiquement le service, sur une station neuve ou existante. Le Pi peut ensuite effectuer les mises à jour depuis son écran ou depuis un autre ordinateur, sans mot de passe administrateur à chaque opération.

Si seules les nouvelles sources ont été déployées sur une station existante, sans passer par l’installateur complet, activer une seule fois le service dans un terminal du Pi :

```sh
sudo python3 "$HOME/apps/openprinttag-station/deploy/install-updater.py" --user "$USER"
```

Saisir le mot de passe du Pi dans son terminal. Recharger ensuite OPT Station. Si le script est absent, installer d’abord la première version publiée contenant cette fonction avec la commande d’installation habituelle ; les versions antérieures ne peuvent pas ajouter ce service depuis leur interface.

## Conservation et vérification

Le service travaille indépendamment du navigateur et de l’application qu’il remplace. Il utilise uniquement les releases publiques du dépôt officiel **Cyril-E/OPT-station**. Un dépôt personnalisé reste consultable pour la détection, avec installation manuelle. Aucun jeton GitHub privé n’est transmis au service système.

Pour chaque demande, il relit les métadonnées de la release exacte, vérifie qu’elle est publiée et plus récente que les sources installées, puis contrôle le SHA-256 de l’archive contre les métadonnées GitHub et le fichier fourni avec l’archive. Les chemins, les liens et la version des sources sont vérifiés avant utilisation. Le premier format pris en charge pour cette installation est **v0.26.0**.

Les sources téléchargées et les scripts du service appartiennent au système. Le navigateur ne peut fournir ni commande, ni URL, ni dossier à exécuter. L’environnement Python de l’application utilise le compte ordinaire de la station. Aucun accès sudo général n’est accordé à ce compte ou à l’application.

La préparation utilise l’installateur existant. Avant activation, les données sont sauvegardées et les fichiers de lancement sont enregistrés. L’inventaire, les notes, les photos, les modèles, les accès privés, les sauvegardes RFID, les réglages réseau et l’autorité HTTPS sont conservés. Le certificat approuvé sur les autres appareils ne doit pas être réinstallé. Aucun tag RFID n’est réécrit.

La demande et l’état d’installation sont persistants. Les nouvelles opérations qui modifieraient la station sont suspendues pendant l’installation ; la consultation de l’inventaire et de l’avancement reste possible tant que l’application répond.

## Échec ou interruption

Une erreur avant activation conserve l’application existante. Une erreur pendant l’activation déclenche le retour arrière de l’installateur ; le service vérifie ensuite que la version précédente répond de nouveau. La sauvegarde privée et les anciennes sources restent disponibles.

Si le courant est coupé ou si la restauration ne peut pas être confirmée, l’état indique qu’une reprise manuelle est nécessaire. Le redémarrage n’exécute pas à nouveau la demande et ne remplace pas la sauvegarde par une seconde tentative. Une nouvelle installation depuis l’interface est bloquée tant que cet état n’est pas examiné.

Sur le Pi, les éléments de diagnostic sont :

```sh
sudo journalctl -u opt-station-update.service --no-pager -n 80
sudo less /var/lib/opt-station-updater/worker.log
sudo cat /var/lib/opt-station-updater/recovery.json
```

Le journal détaillé et les emplacements de reprise restent privés. Le navigateur reçoit seulement la version demandée, l’avancement, les dates et le résultat. Conserver le dossier de sauvegarde et suivre la [procédure de reprise de l’installateur](33-installation-une-commande.md#réinstallation-et-échec) avant de relancer une installation manuelle. Le service ne nettoie pas automatiquement les sauvegardes ni les anciennes sources.

## Qualification

Les essais logiciels utilisent des archives contrôlées, des fichiers de configuration et SQLite réels, avec les commandes de paquets et de services simulées. Ils couvrent le lancement unique, les accès réseau, les opérations concurrentes, les empreintes, la conservation des données et certificats, les erreurs d’activation, la vérification du retour arrière et le signalement d’une interruption.

La progression, une indisponibilité temporaire du serveur et la reconnexion sont également exercées dans le client JavaScript. Ces essais ne constituent pas une validation matérielle d’une mise à jour entre deux releases publiques sur le Pi ; cette validation sera signalée séparément.

Le service a été installé et démarré sur Raspberry Pi OS Trixie arm64, avec validation des unités par systemd, vérification des scripts appartenant au système et reconnaissance depuis l’interface HTTPS. L’inventaire, les réglages privés, le certificat et le kiosque sont conservés. Le premier essai réel d’installation d’une release depuis l’application reste à effectuer. La qualification de v0.26.0 comprend **974 tests sur Mac**, avec deux exclusions liées à l’environnement, **976 sur Pi** et les sept moteurs JavaScript, sans dépendance supplémentaire ni changement du schéma SQLite 6.
