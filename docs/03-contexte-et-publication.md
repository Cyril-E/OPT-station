# Distribution et données de la station

## Sources et installation

Le [dépôt OPT Station](https://github.com/Cyril-E/OPT-station) distribue le code, les ressources, les tests et la documentation technique. Chaque version publiée fournit une archive complète et son empreinte SHA-256. Les archives sont téléchargeables sans compte GitHub; suivre le [guide d’installation](12-installation-station-reelle.md).

L’application utilise les modules `openprinttag_app` et les services `openprinttag.service` et `openprinttag-display.service`. Le lien de sources stable est `$HOME/apps/openprinttag-station`. Les adresses et identifiants des appareils se règlent dans Configuration.

## Données persistantes

L’inventaire, la bibliothèque, les notes, les journaux NFC et les réglages des équipements restent dans le répertoire de données de la station. Ils ne sont pas fournis dans l’archive source. Utiliser les [sauvegardes](26-sauvegardes-et-restauration.md) avant une mise à jour ou un changement de support.

Les certificats HTTPS de chaque station sont stockés séparément des sources et de l’inventaire. Conserver leur autorité lors des mises à jour et suivre le [guide HTTPS](31-https-local.md) pour la confiance des appareils clients.

Le mode simulation utilise des données fictives dans un répertoire distinct. Ne pas remplacer un inventaire matériel par la base de simulation.

## Exemples et dépendances

Les comptes, noms de machines et adresses des commandes sont des exemples. Les adresses `192.0.2.x` sont réservées à la documentation. Les exemples officiels OpenPrintTag conservent leur provenance et leurs identifiants de référence.

Les notices et licences des composants tiers restent applicables; voir [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). La licence du code propre à l’application n’a pas encore été choisie.
