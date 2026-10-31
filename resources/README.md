# Catalogue GTIN local

`catalogue.json` est un index généré depuis la copie officielle de la base OpenPrintTag conservée dans ce projet. Il sert uniquement à proposer des fiches produit à partir d’un GTIN valide. Il n’identifie pas à lui seul une bobine physique et n’est pas un décodeur universel des QR fabricant.

| Origine | Version |
| --- | --- |
| Base `OpenPrintTag/openprinttag-database` | `2451ae7adc115cfc40cf1892bddbb0b4a2f1b1a3` |
| Schéma de la base | `954d050b1a83a8cee03ea8ab8d342d6741c61281` |
| Définitions du tag | `060e420892d66c062c8af440c97701aab96bac79` |
| Licence de la base | MIT, texte complet et attribution conservés dans `source.license_text` |

Empreinte SHA-256 du catalogue : `21cd3c02347780085203997a3a0b3989d6f2efbe04ec59f9edddbc749df7d2ef`.

L’index examine 13 412 fiches de conditionnement. Il retient 8 109 fiches ayant un GTIN valide, pour 7 548 GTIN distincts. Parmi ceux-ci, 559 correspondent à plusieurs fiches : l’application demande de choisir et ne sélectionne pas silencieusement un produit. Les 5 303 fiches sans GTIN valide restent dans l’archive source mais ne sont pas recherchables par cet index.

Les propriétés proviennent des jointures explicites marque/matériau/conditionnement. Le diamètre du filament est converti de µm en mm pour le tag. Aucun poids réel individuel, aucune consommation et aucun identifiant de bobine ne sont inventés. Les chemins d’origine sont conservés dans les résultats.

Pour reconstruire l’index à partir de l’archive locale :

```sh
.venv/bin/python scripts/build_catalogue.py
```

Ce script appartient à l’application. Il vérifie l’empreinte de l’archive avant de lire ses YAML comme données, sans extraire ni exécuter les sources téléchargées. Il n’effectue aucune requête réseau. Conserver les licences tierces lors d’une future distribution; la licence de notre application reste à choisir séparément.
