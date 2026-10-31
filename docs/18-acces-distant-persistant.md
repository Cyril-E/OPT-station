# Accès distant persistant, sans code

Le niveau d’accès distant se règle dans Configuration → Accès distant.

## Choisir le partage depuis le bureau

Depuis une machine du même réseau, ouvrir l’adresse annoncée au démarrage d’OPT Station, puis **Configuration → Accès distant**. Choisir un niveau et cliquer sur **Enregistrer le partage**.

| Choix | Fonctions disponibles depuis le réseau |
| --- | --- |
| Désactivé | Les données et appareils restent locaux sur le Pi. Configuration reste accessible pour réactiver le partage depuis le bureau. |
| Inventaire et modèles | Consulter et gérer le stock, créer des favoris et modèles. NFC, caméras et suivi imprimante restent locaux. |
| Accès complet sans code | Stock, modèles, lecture/écriture NFC, caméra QR, suivi PrusaLink, caméras et réglages de connexion des appareils. |

**L’accès complet reste actif jusqu’à sa désactivation ou au choix d’un autre niveau.** Il n’a plus d’expiration de douze heures, ne demande aucun code et ne repose pas sur une session de navigateur. Fermer une page, changer d’ordinateur ou redémarrer le Pi ne remet pas ce choix à zéro.

Le réglage est commun à la station : il s’applique aux machines du réseau local, pas seulement au navigateur qui l’a enregistré. Les autres pages ouvertes actualisent leurs droits à leur prochain contrôle d’état, environ toutes les cinq secondes. Les routes du serveur appliquent le nouveau niveau immédiatement.

Les trois niveaux sont modifiables dans Configuration sur le Pi **ou depuis le bureau**, y compris quand les fonctions distantes sont désactivées. Aucune action sur le routeur ni ouverture d’un accès Internet n’est ajoutée.

## Ce qui est conservé

L’inventaire, les modèles, les connexions PrusaLink, les caméras et leurs secrets sont conservés. La préparation, la confirmation et la vérification des écritures NFC restent nécessaires. Une écriture déjà autorisée termine sa relecture si le partage change pendant l’opération; les nouvelles demandes sont ensuite soumises au niveau choisi.

Les secrets PrusaLink et caméra restent stockés sur le Pi et masqués dans les réponses de configuration. Supprimer le code d’accès de la station ne supprime pas les identifiants propres à ces appareils.

## Installation et migration

Les dépendances et services sont ceux des [guides d’installation](12-installation-station-reelle.md) et de [suivi imprimante](17-suivi-imprimante-et-cameras.md). L’écoute réseau doit être activée par `--lan`; le formulaire ne modifie pas l’adresse d’écoute du serveur.

Le choix est enregistré atomiquement dans **`network-settings.json`**, au format `{"version":2,"mode":"full"}` pour l’accès complet, avec permissions `0600`. Inclure ce fichier dans les sauvegardes privées. L’ancien fichier `network-access.json` n’est plus utilisé et reste conservé pour un éventuel retour à une ancienne version; aucun nouveau code n’est généré.

Une ancienne configuration `version: 1` qui demandait un code ne devient pas automatiquement ouverte : son ancien mode complet est lu comme **Inventaire et modèles** jusqu’au choix explicite du nouveau partage. L’enregistrement dans Configuration écrit alors le format 2.

Pour revenir au logiciel `v0.5.0`, arrêter le serveur, restaurer le fichier `network-settings.json` de version 1 conservé dans la sauvegarde préalable, puis remettre le lien vers l’ancienne installation. Conserver le fichier de l’ancien code. Les données d’inventaire et les identifiants des appareils ne nécessitent pas de migration.

## Vérifications

Les tests vérifient les droits de plusieurs ordinateurs sans cookie ni connexion, la conservation du niveau après recréation du serveur, la réactivation depuis Configuration en mode désactivé, la migration des anciens réglages, les erreurs d’enregistrement et les contrôles d’origine et de nom d’hôte. Les anciennes routes de code/connexion et leurs fenêtres sont retirées.

Les vérifications logicielles et les limites matérielles de la version courante sont détaillées dans le [guide de vérification](08-verification-prototype.md).

La sauvegarde préalable conserve l’installation et le réglage de partage précédents. Le stock, les favoris, le journal, les sauvegardes NFC et les identifiants des appareils ont été vérifiés inchangés; aucune écriture NFC réelle n’a été déclenchée.
