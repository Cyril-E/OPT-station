# Développement et premiers essais

Pour installer une station avec le matériel NFC et la caméra, suivre le [guide de station réelle](12-installation-station-reelle.md). Ce document décrit le mode simulation et les vérifications à effectuer avant de brancher les périphériques.

## 1. Récupérer une version

Télécharger l’archive complète et son empreinte SHA-256 depuis les releases publiques. Aucun compte ni jeton GitHub n’est nécessaire.

Les archives des releases contiennent les fichiers à la racine. Les extraire dans un nouveau dossier de version, en conservant `openprinttag_app/`, `references/`, `resources/`, `deploy/`, les verrous et les tests. Une archive créée manuellement avec `git archive --prefix` peut avoir un dossier parent différent; vérifier sa structure avant l’extraction.

## 2. Préparer Python

Utiliser Python 3.11 ou ultérieur. Depuis le dossier extrait :

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --only-binary=:all: -r requirements.lock
.venv/bin/python -m pytest -q
```

Le mode simulation n’exige pas le lecteur NFC ni Picamera2. Sur Raspberry Pi OS, les bibliothèques caméra et NFC système sont utilisées avec un environnement `--system-site-packages`; le guide matériel décrit cette variante. Ne pas copier l’environnement Python d’une autre architecture.

## 3. Lancer la simulation

```sh
.venv/bin/python -m openprinttag_app
```

Ouvrir [http://127.0.0.1:8765/](http://127.0.0.1:8765/). Le mode doit être explicitement indiqué comme simulé. Les périphériques et fiches de démonstration sont fictifs; aucune écriture physique n’est effectuée. La base `simulation.sqlite3` reste séparée de `inventory.sqlite3`.

## 4. Parcours de vérification

Tester lecture, préparation, confirmation et relecture simulée; recevoir une bobine QR, consulter sa fiche et les modèles; vérifier les notes, les archives, les numéros et les champs inconnus. Le succès de ces essais ne prouve pas la compatibilité d’un lecteur ou d’un tag physique.

## 5. Accès réseau d’essai

```sh
.venv/bin/python -m openprinttag_app --lan
```

La commande annonce l’adresse du serveur. Le partage se règle dans Configuration. Utiliser le nom ou l’adresse réels de la station; les adresses `192.0.2.x` de la documentation sont fictives.

Un tunnel SSH d’administration peut exposer le serveur local à un navigateur de la machine cliente, par exemple avec un compte et un nom de Pi à adapter :

```sh
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18765:127.0.0.1:8765 maker@opt-station.local
```

Ouvrir ensuite `http://127.0.0.1:18765/`. Un tunnel vers l’interface locale donne accès aux fonctions de la station locale; ne le partager qu’avec une personne autorisée.

## 6. Données persistantes

Utiliser le même `--data-dir` lors des changements de sources pour retrouver les fiches. Sauvegarder le dossier de données, serveur arrêté, avant une mise à jour. Les identifiants, captures et images de tags privés ne doivent pas être ajoutés au dépôt.

## 7. Passer au matériel

Vérifier le protocole, le lecteur et le tag, puis suivre le [guide matériel](12-installation-station-reelle.md). Les paquets PC/SC et caméra dépendent du système installé; ne pas remplacer arbitrairement les paquets Python du système pour masquer un conflit.

## 8. Mettre à jour

Préparer un nouveau dossier de sources et un environnement Python propre. Les notes de version indiquent les migrations éventuelles. Un retour à un ancien schéma demande les anciennes sources et une sauvegarde compatible; ne pas écraser des données récentes sans décision explicite.

## 9. Version de travail avec capture caméra

L’option `--camera` active la capture QR, y compris avec le lecteur NFC simulé. Les commandes système et dépendances sont documentées dans le [guide d’installation](12-installation-station-reelle.md), et le [guide caméra](11-camera-qr.md) décrit les vérifications de capteur et de netteté.

## 10. Lecteur USB ACS ACR1552U-M1

L’adaptateur réel utilise PC/SC/CCID et le pass-through ISO 15693. Vérifier le modèle, le firmware, le protocole du tag, les droits de la session et la disponibilité du lecteur avant l’écriture. Le [guide de station réelle](12-installation-station-reelle.md) inclut les commandes de diagnostic et les services.
