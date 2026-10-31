# Accéder à OPT Station sur le réseau local

Le partage réseau est persistant, sans code, et réglable depuis le Pi ou depuis une autre machine du même réseau.

## Ouvrir la station

Depuis un ordinateur ou un téléphone du même réseau, ouvrir l’adresse annoncée par OPT Station au démarrage, par exemple `http://<adresse-du-pi>:8765/`. Aucun tunnel SSH ni programme OPT Station local n’est nécessaire. Les données, le lecteur NFC et les caméras utilisés sont ceux du Pi.

Dans **Configuration → Accès distant**, choisir un niveau, puis **Enregistrer le partage** :

| Niveau | Fonctions accessibles à distance |
| --- | --- |
| Désactivé | Configuration, thème et matériel détecté; les données et appareils restent locaux. Configuration permet de réactiver le partage depuis le bureau. |
| Inventaire et modèles | Consulter et gérer le stock, retirer une bobine, créer ou modifier les favoris et fiches modèles. NFC, suivi imprimante et caméras restent locaux. |
| Accès complet sans code | Toutes les fonctions, dont lecture/écriture NFC, capture QR, suivi PrusaLink en lecture seule, caméras et réglages des appareils. |

Le choix est commun aux machines du réseau local et reste enregistré après fermeture du navigateur ou redémarrage. **L’accès complet n’a aucune expiration et ne demande ni code ni renouvellement de session.** Pour le fermer, enregistrer Inventaire et modèles ou Désactivé depuis Configuration. Une écriture NFC déjà autorisée termine sa vérification; les nouvelles demandes respectent immédiatement le niveau choisi.

Sur l’adresse locale `http://127.0.0.1:8765/` du Pi, toutes les fonctions restent disponibles. Les favoris sont des fiches modèles réutilisables : ils ne recopient ni identité de bobine ni consommation individuelle.

## Activer la fonction sur le serveur

Installer les sources d’une version publiée et les dépendances du [guide de la station réelle](12-installation-station-reelle.md).

Pour un lancement manuel sur le Pi, arrêter préalablement le service qui occupe le même port, puis :

```sh
cd "$HOME/apps/openprinttag-station"
.venv/bin/python -m openprinttag_app --mode hardware --camera --lan --data-dir "$HOME/openprinttag-data"
```

`--lan` active l’écoute IPv4 sur `0.0.0.0` et le choix du partage réseau dans Configuration. Une nouvelle installation commence en mode Inventaire et modèles. `--allowed-host` permet de fixer un nom ou une adresse réellement attribuée au Pi. Répéter cette option pour autoriser plusieurs noms d’accès. Sans adresse explicite, la station tente de relever son adresse de sortie.

Pour rendre l’activation persistante, depuis un terminal du Pi utilisant déjà le service utilisateur, créer une surcharge :

```sh
mkdir -p "$HOME/.config/systemd/user/openprinttag.service.d"
cat > "$HOME/.config/systemd/user/openprinttag.service.d/network.conf" <<'UNIT'
[Service]
ExecStart=
ExecStart=%h/apps/openprinttag-station/.venv/bin/python -m openprinttag_app --mode hardware --camera --lan --data-dir %h/openprinttag-data
UNIT
systemctl --user daemon-reload
systemctl --user restart openprinttag.service
systemctl --user status openprinttag.service --no-pager
```

Terminer une éventuelle écriture avant de redémarrer le service. Cette surcharge remplace sa commande de lancement : conserver les autres options propres à une installation différente. Le navigateur du Pi continue à utiliser `http://127.0.0.1:8765/` et son affichage automatique en plein écran.

Exemple fictif de variables équivalentes pour un lancement par une autre méthode (remplacer l’adresse `192.0.2.10` par celle du Pi) : `OPENPRINTTAG_NETWORK=1`, `OPENPRINTTAG_NETWORK_URL=http://192.0.2.10:8765`, et l’adresse dans `OPENPRINTTAG_ALLOWED_HOSTS`. L’écoute du serveur doit aussi être activée sur le réseau; la méthode CLI ci-dessus règle ces éléments ensemble.

## Conservation et vérification

Le niveau choisi est conservé dans **`network-settings.json`**, au format 2 et avec des permissions `0600`. Inclure ce fichier dans les sauvegardes privées du répertoire de données. Aucun cookie de connexion ni code n’est créé. L’ancien `network-access.json` reste conservé pour un éventuel retour à une ancienne version, mais n’est plus utilisé.

Lors d’une mise à jour, un ancien mode complet protégé par code est lu comme Inventaire et modèles jusqu’au choix explicite du partage sans code. Voir la [migration et le retour à v0.5.0](18-acces-distant-persistant.md#installation-et-migration).

Les contrôles d’origine, de contenu JSON et de nom d’hôte restent appliqués. Aucun réglage de routeur ni accès Internet n’est ajouté. Les machines pouvant joindre la station disposent des fonctions du niveau choisi, via la même connexion HTTP locale.

Vérifier depuis une autre machine : stock et favoris accessibles en mode inventaire, fonctions matérielles disponibles en mode complet sans code, puis refusées après désactivation. En mode désactivé, Configuration doit permettre la réactivation. Recharger dans un autre navigateur pour vérifier le choix commun. L’écriture d’un vrai tag continue à demander une préparation et une confirmation explicites, avec sauvegarde et relecture.
