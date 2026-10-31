# Arrêter et redémarrer le Raspberry Pi

Les commandes sont disponibles dans Configuration → Alimentation du Raspberry Pi.

## Utilisation

Sur l’écran du Pi, ou depuis un ordinateur du réseau avec **Accès complet sans code** activé, choisir **Arrêter le Pi** ou **Redémarrer le Pi**, puis confirmer. Le focus initial est sur **Annuler**. Ouvrir ou annuler la confirmation n’envoie aucune commande système. La confirmation expire après deux minutes.

Terminer les écritures NFC et impressions d’étiquettes, puis arrêter le scan QR. La station refuse la demande tant qu’une de ces opérations ou une modification HTTP est en cours. Ce contrôle est refait au moment de confirmer. Les formulaires non enregistrés des autres navigateurs ne sont pas détectables : les enregistrer avant de confirmer.

Après confirmation, les nouvelles opérations de la station sont bloquées et un message d’attente apparaît sur les navigateurs connectés. Une demande n’est envoyée qu’une fois. Si le système la refuse, le message explique le refus et les opérations redeviennent possibles. Si son résultat est incertain, la station ne renvoie pas automatiquement la commande.

- **Arrêter** interrompt OPT Station et son accès réseau. Attendre l’arrêt complet du Pi avant de débrancher l’alimentation. Une absence de réponse réseau ne suffit pas à prouver cet arrêt. Le rallumage devra être effectué sur place.
- **Redémarrer** interrompt temporairement la station. La page ouverte se recharge lorsqu’un nouveau processus serveur répond. Le service backend et Firefox en mode kiosque utilisent le démarrage automatique déjà installé et validé; les formulaires non enregistrés seront perdus.

En accès **Inventaire et modèles** ou **Désactivé**, les commandes sont indisponibles à distance. Le mode simulation et les ordinateurs qui ne sont pas des Raspberry Pi ne peuvent pas arrêter l’hôte avec cette fonction. Les niveaux d’accès habituels restent inchangés.

## Installation et droits

La fonction utilise `/usr/bin/busctl` et le service système `systemd-logind`, présents sur le Pi validé sous Debian Trixie. Aucun paquet Python supplémentaire, accès root pour OPT Station, règle sudo ou politique polkit supplémentaire n’est nécessaire sur cette station. Le service conserve `NoNewPrivileges=true` et son délai d’arrêt de 45 secondes.

Le backend identifie le Pi par `/proc/device-tree/model` et exige le mode matériel. Il interroge les méthodes `CanPowerOff` et `CanReboot` et n’active chaque bouton que si la réponse est `yes`. Les méthodes d’action sont exclusivement `PowerOff(false)` ou `Reboot(false)`, sans autorisation interactive, sans option forcée et avec délai borné. Référence : [interface officielle de logind](https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.login1.html).

Pour contrôler l’installation **sans arrêter ni redémarrer le Pi**, depuis son terminal :

```sh
command -v busctl
systemctl --user is-active openprinttag.service
curl --fail --silent http://127.0.0.1:8765/api/system/power
```

La réponse JSON doit indiquer `supported: true` et les deux actions autorisées. **Vérifier les droits** relance uniquement cette lecture. Si les boutons restent indisponibles, conserver le message de l’interface et vérifier la session graphique ainsi que les droits du compte exécutant le service. Une session SSH peut recevoir `challenge` alors que le service utilisateur reçoit `yes`; le résultat de l’API du service est celui utilisé par la station. Aucune autorisation n’est ajoutée automatiquement en cas de refus.

## API et protection des opérations

| Route | Effet |
| --- | --- |
| `GET /api/system/power` | Capacités et état; accès local/complet exigé. |
| `POST /api/system/power/prepare` | Prépare `poweroff` ou `reboot`, retourne un jeton valable 120 secondes; aucune commande système. |
| `POST /api/system/power` | Exige l’action et son jeton de confirmation; consomme le jeton, retourne HTTP 202 puis transmet la demande une seule fois. |
| `GET /api/status` | État de la demande et identifiant du processus pour suivre le retour du Pi; aucune commande système. |

Les requêtes d’action exigent JSON et respectent la vérification d’origine existante. Aucune commande, aucun chemin ni argument système fourni par le navigateur n’est exécuté. Pendant l’arrêt, les modifications API et les lectures NFC qui actualisent le stock sont refusées; les lectures d’état restent possibles. Les erreurs système détaillées ne sont pas renvoyées au navigateur. Un délai dépassé est traité comme un résultat incertain, sans répétition.

## Sauvegarde et validation

La mise à jour ne change ni le schéma SQLite ni les fichiers privés de réglages. Sauvegarder le dossier de données avant installation et conserver le précédent dossier source pour un retour en arrière. Les instructions d’installation de base restent celles du [guide de station réelle](12-installation-station-reelle.md).

Les tests automatisés utilisent un faux pilote système : permissions, accès distant, confirmation, expiration, demandes concurrentes, blocage des opérations en cours, refus système et résultat incertain sont exercés sans commande d’arrêt réelle. Le parcours de confirmation et d’annulation est également vérifié dans le navigateur.

Les vérifications logicielles et les limites matérielles de la version courante sont détaillées dans le [guide de vérification](08-verification-prototype.md).

**Validation matérielle :** les boutons **Redémarrer** et **Arrêter** sont validés sur Raspberry Pi, avec retour automatique d’OPT Station après redémarrage. Ces essais manuels complètent les tests automatisés et les vérifications d’annulation ci-dessus.
