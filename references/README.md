# Références locales gelées

Les snapshots suivants ont été récupérés en lecture seule depuis les dépôts officiels, le 23 octobre 2026. Aucun code téléchargé n’a été exécuté.

## Documentation et profils NFC

Les protocoles requis, les pilotes et les profils matériels vérifiés sont décrits dans le [guide d’installation](../docs/12-installation-station-reelle.md) et le [guide de vérification](../docs/08-verification-prototype.md).

Références des fabricants et pilotes :

- [Manuel ACS ACR122U v3.06](https://www.acs.com.hk/download-manual/418/TSP-ACR122U-3.06.pdf).
- [Page ACS ACR1552U](https://www.acs.com.hk/en/products/575/) et [manuel ACR1552U v1.09](https://www.acs.com.hk/download-manual/13473/REF-ACR1552U-Series-1.09.pdf).
- [Liste des lecteurs reconnus par libccid](https://ccid.apdu.fr/ccid/iProduct.html).

Les manuels ACS et les pages web ne sont pas inclus dans les snapshots locaux ni dans `SHA256SUMS.txt`. La provenance des références et leurs limites sont décrites dans [Sources et provenance](../docs/04-sources-et-provenance.md).

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
