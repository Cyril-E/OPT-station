# Références locales gelées

Les snapshots suivants ont été récupérés en lecture seule depuis les dépôts officiels, le 23 octobre 2026. Aucun code téléchargé n’a été exécuté.

## Lecteur déjà commandé, déclaré par Cyril

- Modèle déclaré : lecteur USB Lianshi ACR122U, selon la [fiche commerciale signalée](https://www.amazon.fr/dp/B07DK9GX1N). L’appareil physique et sa révision n’ont pas été inspectés; confirmer l’étiquette avant d’attribuer cette fiche à l’unité réelle.
- Le manuel officiel [ACS ACR122U v3.06](https://www.acs.com.hk/download-manual/418/TSP-ACR122U-3.06.pdf) a été vérifié dans la recherche documentaire associée : ISO 14443 A/B, MIFARE, FeliCa et NFC Forum Types 1 à 4; pas d’ISO 15693/NFC-V. Cyril a fourni le modèle et le lien commercial, pas ces caractéristiques. L’accès direct au PDF a échoué dans cet environnement; voir [la provenance](../docs/04-sources-et-provenance.md). Cela exclut l’ACR122U déclaré comme lecteur-écrivain du tag OpenPrintTag MK1. Une modification logicielle ne peut pas ajouter le protocole radio manquant.
- Le PDF n’a pas pu être téléchargé localement pendant cette tâche; voir les limites et l’état d’accès dans [la provenance](../docs/04-sources-et-provenance.md). Il n’est donc pas couvert par `SHA256SUMS.txt`.

## Candidat USB à évaluer, non choisi

- ACS ACR1552U-M1, USB-A, recommandé après recherche comme candidat; Cyril ne l’a pas acheté et le choix n’est pas final.
- Sources : [page officielle ACS](https://www.acs.com.hk/en/products/575/), [manuel v1.09](https://www.acs.com.hk/download-manual/13473/REF-ACR1552U-Series-1.09.pdf) et [fiche libccid](https://ccid.apdu.fr/ccid/iProduct.html).
- §5.3.4.2 du manuel (p. 43–45) décrit `FF FB` en pass-through ISO 15693 pour lecture/écriture simple et multiple de blocs, avec exemple NXP SLIX2; firmware requis ≥ 1.03.00. libccid répertorie ACR1552 1S CL Reader (`072f:2303`) depuis la version 1.5.3 avec statut « should work »; éviter de supposer ce support avec libccid 1.5.2. Des versions Debian arm64/armhf existent.
- Les sources ACS et CCID sont référencées, mais les PDF et pages ne sont pas copiés localement; le résumé du manuel provient de la recherche associée.
- Compatibilité de bout en bout et fonctionnement Raspberry Pi non testés. Les offres commerciales de repère sont [ShopNFC](https://shopnfc.com/fr/lecteurs-encodeurs-nfc/580-acr1552u-lecteur-encodeur-nfc-multi-iso.html) et [PC21](https://www.pc21.fr/fiche/acr1552u-m1-acr1552u-usb-nfc-reader-iv-usb-type-a--i5672777.html); aucun total livré n’est garanti ici. Aucune page commerciale archivée, aucun achat.

## Standard OpenPrintTag

- Dossier complet : upstream/openprinttag-specification-060e420/
- Branche main, commit 060e420892d66c062c8af440c97701aab96bac79, daté du 9 octobre 2026.
- Licence MIT, copie upstream conservée à la racine du snapshot.
- Contient les définitions des champs/enums, le format NFC, la spécification physique, les notes techniques, exemples NDEF/CBOR, tests, utilitaires Python et fichiers média.

Points d’entrée :
- docs_src/nfc_data_format.md
- docs_src/physical_spec.md
- docs_src/nfc_technical_details.md
- data/main_fields.yaml, data/meta_fields.yaml, data/aux_fields.yaml
- utils/README.md, utils/rec_info.py, utils/rec_update.py, utils/nfc_initialize.py, utils/opt_check.py

## Base matériaux

- Archive complète du périmètre utile : openprinttag-material-database-2451ae7.tar.gz
- Branche main-pr, commit 2451ae7adc115cfc40cf1892bddbb0b4a2f1b1a3, daté du 14 octobre 2026.
- Contient les dossiers data/brands, data/materials, data/material-packages et data/material-containers, avec README.md, LICENSE et schema_version.conf.
- Les quatre arbres de données comptent 28 307 fichiers dans Git; l’archive fait 1,7 Mio et contient aussi les trois fichiers de métadonnées/licence listés ci-dessus.
- L’archive n’inclut pas data/tmp/assets ni les outils d’édition/validation de la base.
- Quatre enregistrements restent dépliés pour inspection rapide dans material-database-examples/data/: marque Prusament, matériau ASA Jet Black, package PLA Prusa Orange 1 kg et contenant 1000g.

Le commit de cette base épingle le schéma DB dans openprinttag-architecture au commit 954d050b1a83a8cee03ea8ab8d342d6741c61281. La copie générée se trouve dans upstream/openprinttag-architecture-954d050/schema/generated/opt_db_schema/.

## Intégrité

SHA-256 de l’archive matériaux : effb295912943c3cc6d5b0341251b7b7352a5da63322285676dc316a54c265ab. Les 117 sommes des copies et de l’archive sont vérifiées dans [SHA256SUMS.txt](SHA256SUMS.txt). Ces sommes représentent les fichiers locaux effectivement écrits; elles ne sont pas publiées par l’upstream.

Pour les commits, licences, liens et limites observées, voir [la provenance](../docs/04-sources-et-provenance.md).
