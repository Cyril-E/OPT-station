# Sources, versions et provenance

Les spécifications et données de référence sont gelées sur les commits indiqués ci-dessous. Les liens épinglés rendent leur contenu reproductible; une branche amont peut évoluer indépendamment de la version intégrée.

Les données de simulation, exemples de documentation et fixtures de test ne décrivent pas une installation réelle. Les inventaires, captures privées, images de tags et réglages d’équipements restent en dehors des sources distribuées.

## Sources principales

| Source | Version/observation | Copie locale |
|---|---|---|
| [OpenPrintTag — site officiel](https://openprinttag.org/) | Présente l’objectif général, le générateur et le lien vers la spécification. Sa page d’accueil revendique notamment une lecture circulaire/360° et un tag unique, mais ce sont des objectifs de présentation. | URL seulement |
| [Spécification — dépôt officiel](https://github.com/OpenPrintTag/openprinttag-specification/tree/060e420892d66c062c8af440c97701aab96bac79) | Branche main, commit 060e420892d66c062c8af440c97701aab96bac79, 2026-10-09, MIT. Source complète gelée. | references/upstream/openprinttag-specification-060e420/ |
| [Format NFC source](https://github.com/OpenPrintTag/openprinttag-specification/blob/060e420892d66c062c8af440c97701aab96bac79/docs_src/nfc_data_format.md) | NDEF, MIME, CBOR, régions et opérations. | Copie complète dans docs_src/ |
| [Spécification physique source](https://github.com/OpenPrintTag/openprinttag-specification/blob/060e420892d66c062c8af440c97701aab96bac79/docs_src/physical_spec.md) | Tag MK1 de référence, antenne lecteur, placement et caractéristiques mécaniques/électriques. | Copie complète et dessins/PDF |
| [Notes techniques NFC](https://github.com/OpenPrintTag/openprinttag-specification/blob/060e420892d66c062c8af440c97701aab96bac79/docs_src/nfc_technical_details.md) | Recommandations de capacité, mises à jour, protection et limites d’authenticité. | Copie complète dans docs_src/ |
| [Générateur officiel](https://openprinttag.org/generator/) | La page indiquait NFC-V et 312 octets disponibles pour son profil courant; propose aussi un enregistrement NDEF URL facultatif. Cette capacité n’est pas une limite universelle du format. | URL seulement |
| [Base matériaux officielle](https://github.com/OpenPrintTag/openprinttag-database/tree/2451ae7adc115cfc40cf1892bddbb0b4a2f1b1a3) | Branche main-pr, commit 2451ae7adc115cfc40cf1892bddbb0b4a2f1b1a3, 2026-10-14, MIT. README indique 128 marques, 14 666 matériaux, 13 412 packages et 101 contenants. | Archive locale des marques, matériaux, packages et contenants; exemples lisibles |
| [Schéma d’architecture référencé par la base](https://github.com/OpenPrintTag/openprinttag-architecture/tree/954d050b1a83a8cee03ea8ab8d342d6741c61281/schema/generated/opt_db_schema) | Commit 954d050b1a83a8cee03ea8ab8d342d6741c61281, 2026-10-01, MIT; ce hash est lu dans schema_version.conf du commit de base ci-dessus. | Schémas JSON générés copiés localement |
| [Discussion officielle sur les identifiants QR](https://github.com/OpenPrintTag/openprinttag-specification/discussions/72) | Exemple mainteneur : certains IDs de bobine trouvés sur l’emballage/QR Prusa alimentent brand_specific_material_id. Mapping propre à Prusa, pas une définition générique des QR. | URL seulement |

## Sources matérielles complémentaires

- [ACS ACR1552U-M1](https://www.acs.com.hk/en/products/575/) et [manuel v1.09](https://www.acs.com.hk/download-manual/13473/REF-ACR1552U-Series-1.09.pdf) : commandes de pass-through ISO 15693 utilisées par l’adaptateur NFC. Le modèle, le firmware et le protocole du périphérique doivent correspondre au profil pris en charge.
- [NXP SLIX2, Rev 4.2](https://www.nxp.com/docs/en/data-sheet/SL2S2602.pdf) : mémoire, protections par page et compteur; les écritures de l’adaptateur conservent les blocs réservés.
- [Manuel ACS ACR122U](https://www.acs.com.hk/download-manual/418/TSP-ACR122U-3.06.pdf) : ce lecteur ne fournit pas le profil NFC-V/ISO 15693 requis pour OpenPrintTag MK1.
- [Caméras Raspberry Pi](https://www.raspberrypi.com/documentation/accessories/camera.html#hardware-specifications) et [logiciels caméra](https://www.raspberrypi.com/documentation/computers/camera_software.html) : identification des capteurs, connexion et capture. Voir le [guide caméra](11-camera-qr.md).
- [Touch Display 2](https://www.raspberrypi.com/documentation/accessories/touch-display-2.html#compatibility) : vérifier la variante d’écran et le modèle de Pi. Voir la [fiche écran](10-ecran-tactile.md).

## Données fabricant et données individuelles

La base officielle sert à retrouver des caractéristiques de produit. Les liens Prusament pris en charge sont traités suivant le [guide des QR](19-stock-qr-et-etiquettes.md). Une fiche produit ne prouve ni la tare, ni le poids réel, ni la consommation d’une bobine donnée. Les champs absents restent inconnus; les informations individuelles doivent provenir d’une source explicite ou d’une mesure.

## Licences et limites de validation

Les notices et licences des composants tiers sont conservées dans [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). Les copies amont et exemples officiels restent des sources de référence; le logiciel n’exécute pas leurs utilitaires pour traiter un tag.

La conformité du format, les essais simulés et la compatibilité d’un périphérique sont des vérifications distinctes. Les résultats et limites de chaque version sont consignés dans les [notes de version](../CHANGELOG.md). Les données et journaux privés d’un banc matériel ne sont pas des exemples à publier.
