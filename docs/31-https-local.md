# HTTPS local

HTTPS utilise Caddy, une autorité de certification propre à la station et une page d’aide bilingue. L’installateur complet en une commande reste à réaliser; les sources et archives publiées sont accessibles sans authentification.

## Fonctionnement

- Caddy reçoit HTTPS sur le port **443** et transmet à OPT Station sur **127.0.0.1:8766**. Le serveur applicatif n’écoute plus directement sur le réseau.
- Les adresses HTTP sur les ports **80** et **8765** conduisent à l’aide d’installation du certificat. Les autres chemins sont redirigés vers HTTPS; aucune commande matérielle n’est traitée en HTTP par la passerelle.
- La station garde son nom réseau, par exemple `https://opt-station.local`. Les IPv4 privées détectées sont également configurées. Remplacer cet exemple par l’adresse annoncée à l’installation.
- L’écran local utilise **https://localhost/**, avec vérification du certificat. Les clients distants conservent leurs droits Inventaire ou Complet; ils ne deviennent pas des clients locaux à cause de la passerelle.
- Caddy génère et renouvelle ses certificats. Sa clé privée et son autorité restent dans **/var/lib/opt-station-caddy**, hors de l’inventaire et des archives du projet. Une réinstallation des réglages réutilise cette autorité.

La station ne demande pas de domaine public et l’installation n’ajoute aucune redirection de ports sur le routeur. Le partage reste destiné au réseau local. Les certificats n’ajoutent ni compte ni mot de passe aux niveaux de partage existants.

## Installation sur une station existante

Préparer les nouvelles sources complètes et leur environnement Python selon le [guide d’installation](12-installation-station-reelle.md). Pour une première activation de HTTPS, faire tourner ces sources en HTTP : le programme d’installation vérifie l’absence d’opération matérielle en cours. Sur une station déjà en HTTPS, le remplacement des sources conserve les réglages et l’autorité; une réexécution reste possible pour actualiser les adresses.

Depuis le dossier des nouvelles sources sur le Pi, avec le compte ordinaire de la station :

```sh
python3 deploy/install-https.py --dry-run
sudo python3 deploy/install-https.py
```

Le premier appel montre le plan sans modifier le système. Le second installe les paquets Debian/Raspberry Pi OS **caddy**, **avahi-daemon** et **ca-certificates**, prépare les services, importe le certificat public pour le système et Firefox du Pi, puis contrôle une connexion HTTPS avec validation du certificat. Le mot de passe administrateur se saisit uniquement dans le terminal du Pi.

L’outil utilise le compte ordinaire indiqué par `SUDO_USER`. Un installateur exécuté directement en root doit préciser `--user`. Il accepte `--hostname` pour le nom court du Pi et plusieurs `--address` pour fixer les IPv4 locales; par défaut il les relève sur la machine. Le mode et l’activation de la caméra sont conservés; `--mode simulation` et `--no-camera` permettent de choisir un autre profil.

Le service applicatif doit déjà exister et préciser son répertoire de données avec **--data-dir**. Le script conserve ce répertoire, y compris s’il est différent de **$HOME/openprinttag-data**. Les sources actives doivent être reliées par **$HOME/apps/openprinttag-station**; le service garde ce chemin stable pour les futures mises à jour. Le script refuse les ports occupés par un autre serveur et les configurations HTTPS non reconnues. Les autres politiques Firefox sont conservées.

Les changements de fichiers sont sauvegardés dans un dossier privé sous **/var/lib/opt-station-https-backups**. Un échec d’activation restaure ces fichiers et relance la configuration applicative précédente. Les clés de l’autorité ne sont pas supprimées ni régénérées. L’inventaire et les réglages des appareils ne sont pas remplacés.

## Reconnaître le certificat sur un autre appareil

Ouvrir l’adresse d’aide annoncée, de forme **http://nom-du-pi.local/https**. Elle reste accessible avant la reconnaissance du certificat et même si le partage de l’inventaire est désactivé.

1. Comparer l’empreinte SHA-256 avec celle affichée dans **Configuration → Connexion sécurisée** sur l’écran du Pi.
2. Télécharger le **certificat public** et l’importer dans les autorités de confiance de l’appareil.
3. Fermer et rouvrir le navigateur, puis ouvrir l’adresse HTTPS de la station. Aucun avertissement de certificat ne doit rester.

### Quel nom rechercher ?

Le fichier téléchargé est **opt-station-root-ca.crt**. Dans Trousseaux d’accès et les magasins de certificats, il apparaît sous son nom interne, affiché dans **Nom du certificat** sur la page d’aide et dans Configuration. Avec Caddy, ce nom ressemble à **Caddy Local Authority - AAAA ECC Root**, par exemple **Caddy Local Authority - 2026 ECC Root**. L’année peut varier : utiliser le nom réellement affiché par la station.

### Mac — importation et approbation SSL

1. Cliquer sur **Télécharger le certificat public**, puis retrouver **opt-station-root-ca.crt** dans **Téléchargements**.
2. Ouvrir Spotlight avec **⌘ Espace**, rechercher **Trousseaux d’accès** et ouvrir cette application.
3. Sélectionner **Système** dans la colonne de gauche. Choisir **Fichier → Importer des éléments**, sélectionner le fichier téléchargé et confirmer son importation dans **Système**. Saisir le mot de passe du Mac dans sa fenêtre si demandé.
4. Choisir la catégorie **Certificats**, effacer toute recherche précédente et rechercher **Caddy**. Vérifier que le nom correspond à celui affiché sur la page d’aide.
5. Double-cliquer sur ce certificat, déplier **Se fier**, puis régler **SSL** sur **Toujours approuver**.
6. Fermer la fenêtre du certificat et valider avec le mot de passe du Mac si demandé.
7. Ouvrir l’adresse HTTPS de la station dans **Chrome**. Si un avertissement persiste, fermer puis rouvrir Chrome et réessayer.

**Si le certificat semble absent :** revenir à **Système → Certificats** et effacer la recherche. Les vues **Racines du système** et **Mes certificats** ne correspondent pas à cet import. Un certificat déjà présent n’a pas besoin d’être importé à nouveau; vérifier son approbation SSL et son empreinte.

### Windows

1. Ouvrir **opt-station-root-ca.crt**, cliquer sur **Installer le certificat** et choisir **Utilisateur actuel**.
2. Choisir **Placer tous les certificats dans le magasin suivant**, puis **Parcourir → Autorités de certification racines de confiance**.
3. Terminer l’importation. Relancer le navigateur et ouvrir l’adresse HTTPS de la station.

### Firefox / Linux

1. Ouvrir **Paramètres → Vie privée et sécurité → Certificats → Afficher les certificats → Autorités**.
2. Cliquer sur **Importer**, sélectionner **opt-station-root-ca.crt** et autoriser cette autorité à identifier des sites web.
3. Vérifier le nom du certificat dans la liste, puis relancer Firefox et ouvrir l’adresse HTTPS de la station.

La page fournit les instructions Mac, Windows et Firefox/Linux. L’installation de cette confiance demande une action sur chaque appareil. Elle ne demande jamais la clé privée de la station. Changer d’adresse crée une nouvelle origine de navigateur : les préférences de thème et de langue peuvent devoir être choisies à nouveau; l’inventaire reste sur le Pi.

Un client MCP doit aussi reconnaître cette autorité. Selon son environnement, il peut utiliser le magasin de certificats du système ou un fichier d’autorités configuré dans son client HTTP. L’adresse MCP affichée passe en **https://nom-du-pi.local/mcp**. Ne pas désactiver la validation TLS pour contourner ce réglage.

La reconnaissance du certificat et l’autorisation des notifications Chrome sont distinctes. Les notifications ne sont pas incluses dans cette étape HTTPS.

## Redémarrage et mises à jour

La passerelle **opt-station-https.service** démarre avec le système. L’application et le navigateur local gardent leurs services utilisateur existants. Les certificats sont indépendants du dossier de sources; remplacer le programme ne doit pas supprimer **/var/lib/opt-station-caddy**. Après changement d’adresse IP, relancer le programme d’installation pour actualiser les alias; le nom `.local` reste l’adresse à privilégier.

Les sauvegardes ordinaires de configuration et d’inventaire n’exportent pas les clés de cette autorité système. Une sauvegarde complète du Pi doit protéger séparément ce dossier et **/etc/opt-station**. Ne pas copier une même autorité privée entre plusieurs stations indépendantes.

Pour revenir temporairement à l’accès HTTP, arrêter et désactiver la passerelle avec l’administrateur, renommer les surcharges **https.conf** des deux services utilisateur, puis recharger et relancer les services. Les anciennes commandes HTTP du service principal sont alors reprises. Conserver les certificats pour une réactivation ultérieure.

## Vérifications et références

La qualification comprend **628 tests sur Mac et Raspberry Pi**, un Caddy récent sur Mac et le paquet Debian sur Pi. L’installation système, sa réexécution, la conservation de l’autorité et l’affichage local en plein écran sont vérifiés. Les accès par nom et IP depuis un autre ordinateur, les faux en-têtes et l’isolement du backend sont contrôlés avec validation du certificat. La base et les réglages sont conservés. L’ouverture HTTPS dans Chrome sur macOS est également validée après import dans Système et approbation SSL.

Les tests couvrent les niveaux de partage derrière la passerelle, les origines, les faux en-têtes de client local, les certificats publics et leurs empreintes, les erreurs de configuration et la restauration des fichiers. Un essai avec un vrai Caddy contrôle TLS, le refus d’une autorité inconnue, la conservation de l’autorité après redémarrage, les redirections et le MCP.

```sh
OPT_STATION_CADDY=/chemin/vers/caddy .venv/bin/python -m pytest -q tests/test_https_gateway.py
```

Références : [HTTPS local et certificats Caddy](https://caddyserver.com/docs/automatic-https#local-https), [en-têtes du proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#defaults), [service système Caddy](https://caddyserver.com/docs/running), [certificats Firefox](https://firefox-admin-docs.mozilla.org/reference/policies/certificates/), [confiance des certificats sur Mac](https://support.apple.com/fr-fr/guide/keychain-access/kyca11871/mac).
