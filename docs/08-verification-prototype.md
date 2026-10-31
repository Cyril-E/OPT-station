# Vérification et compatibilité

## Vérifications logicielles

La suite de la version **v0.19.0** comprend **751 tests réussis sur Mac**, avec un test réservé à Linux ignoré, et **752 tests réussis sur Raspberry Pi**. Elle vérifie le codec OpenPrintTag, les protections et interruptions NFC en simulation, le stockage, les migrations, les QR, les étiquettes, les sauvegardes, le MCP, les droits réseau, PrusaLink, HTTPS, les événements d’imprimante et les propositions de l’assistant IA avec des réponses API contrôlées.

Depuis les sources, avec les dépendances de test installées :

```sh
.venv/bin/python -m pytest -q
node tests/interface_i18n.cjs
node tests/interface_notifications.cjs
node tests/interface_updates.cjs
node tests/interface_assistant.cjs
```

Le test réel de passerelle utilise Caddy. Si ce binaire n’est pas dans le PATH, indiquer son emplacement :

```sh
OPT_STATION_CADDY=/chemin/vers/caddy .venv/bin/python -m pytest -q tests/test_https_gateway.py
```

Sans Caddy, ce test est ignoré. La qualification complète indiquée ci-dessus inclut son exécution. Les vérifications JavaScript couvrent la langue, les saisies, les préférences, les permissions de notification, la reprise, les doublons entre onglets, les notes de version et les propositions IA avec des API de navigateur contrôlées. Le sommaire est vérifié dans le navigateur aux largeurs 390, 1280 et 1920 pixels, en français/anglais et thèmes clair/sombre, avec conservation d’une saisie non enregistrée.

## Profils matériels et essais

| Fonction | Profil vérifié | Limites |
| --- | --- | --- |
| Lecture et écriture NFC | Raspberry Pi 5, ACS ACR1552U-M1 USB, NFC-V/SLIX2 | Lecture et écriture initiale suivie de relecture vérifiées. Les nouveaux lecteurs, tags et firmwares demandent leurs propres essais. |
| Remplacement d’un RFID depuis l’inventaire | Lecteur simulé, conservation de l’identité et des données | Remplacement physique d’un tag encore à qualifier. |
| Acquisition QR | Caméra OV5647 et ZXing-C++ | Courte distance, autofocus et autres capteurs à qualifier selon le montage. |
| Impression d’étiquettes | NIIMBOT B3S_P USB, 70 × 40 mm | QR papier relu. Le profil B1 n’est pas qualifié physiquement. |
| PrusaLink | CORE One, firmware 8.0.0+17068 | Suivi en lecture seule au repos et pendant des impressions; aucune commande de mouvement ou de travail. |
| Notifications Chrome | HTTPS, certificat approuvé, Chrome sur macOS | Notification de test et déclenchement sur une vraie fin d’impression validés. Intervention réelle encore à qualifier. |
| Démarrage et alimentation | Raspberry Pi OS 64 bits, session graphique et services systemd | Plein écran, arrêt et redémarrage vérifiés. Le tactile dépend de l’écran retenu. |
| Sauvegardes planifiées | Moteur testé sur destinations temporaires; sauvegarde manuelle USB et aperçu de restauration validés | Exécution nocturne planifiée sur support externe encore à qualifier. |

L’édition des fiches par MCP est confirmée par un essai utilisateur. Les tests d’écriture utilisent des données isolées et couvrent les corrections de consommation, les conflits de version, la sauvegarde/restauration et les relectures RFID. Les contrôles automatisés sur le stock réel utilisent des appels sans changement et ne réécrivent aucun tag.

## Contrôles d’une installation

Vérifier le matériel détecté dans Configuration, puis suivre les guides [NFC et installation](12-installation-station-reelle.md), [caméra](11-camera-qr.md), [écran](10-ecran-tactile.md), [HTTPS](31-https-local.md) et [notifications](32-notifications-imprimante.md). Une réussite logicielle ne suffit pas à qualifier un nouveau montage physique.
