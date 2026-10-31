# Références et licences tierces

La licence du code de cette application n’est pas encore choisie. Les licences des copies et des données tierces ci-dessous restent applicables indépendamment de cette décision. La distribution publique conserve les notices et attributions ci-dessous.

| Référence incluse | Version | Licence et attribution conservées |
| --- | --- | --- |
| Spécification officielle OpenPrintTag | `060e420892d66c062c8af440c97701aab96bac79` | [Licence MIT du snapshot](references/upstream/openprinttag-specification-060e420/LICENSE) |
| Schémas officiels de la base | `954d050b1a83a8cee03ea8ab8d342d6741c61281` | [Licence du snapshot d’architecture](references/upstream/openprinttag-architecture-954d050/LICENSE) |
| Base officielle de matériaux et conditionnements | `2451ae7adc115cfc40cf1892bddbb0b4a2f1b1a3` | Licence MIT dans l’archive source; texte complet et attribution PRUSA RESEARCH A.S. conservés aussi dans `resources/catalogue.json`, propriété `source.license_text` |

Les exemples binaires et les fichiers de référence restent accompagnés de leur contexte et de leur provenance. Le catalogue local est généré depuis les données archivées; ses chemins de fiches d’origine et ses versions sont conservés. Voir [son descriptif](resources/README.md), [les références](references/README.md) et [la provenance détaillée](docs/04-sources-et-provenance.md).

Les dépendances Python sont nommées et épinglées dans `requirements.lock`. Elles sont téléchargées lors de l’installation, sans embarquer ici l’environnement `.venv` ni remplacer leurs propres licences.

Le serveur MCP utilise le [SDK Python officiel Model Context Protocol](https://github.com/modelcontextprotocol/python-sdk), distributions `mcp 2.3.0` et `mcp-types 2.3.0`, sous licence MIT. Leurs dépendances sont également épinglées dans le fichier de verrouillage et conservent les licences fournies par leurs distributions. Aucun client IA ni identifiant de fournisseur IA n’est embarqué dans l’application.

La capture caméra optionnelle utilise [ZXing-C++](https://github.com/zxing-cpp/zxing-cpp), bindings Python `zxing-cpp 3.1.1`, sous licence Apache-2.0, épinglé dans `requirements-camera.lock`. La roue téléchargée conserve ses propres fichiers de licence. Picamera2, libcamera et NumPy proviennent des paquets de Raspberry Pi OS; leurs licences restent applicables. Pillow est désormais épinglé pour le rendu des étiquettes dans l’environnement de l’application.

L’accès NFC optionnel utilise [pyscard](https://github.com/LudovicRousseau/pyscard), installé sur le Pi via `python3-pyscard 2.2.2-1`, sous LGPL-2.1 ou ultérieure d’après le fichier copyright du paquet Debian. PC/SC et le pilote CCID sont fournis par les paquets système; ils ne sont pas embarqués dans les sources du projet. Leurs licences et notices restent celles de ces distributions.

Le rendu des étiquettes utilise [Segno](https://github.com/heuer/segno), version 1.6.6, sous licence BSD-3-Clause, et [Pillow](https://github.com/python-pillow/Pillow), version 13.0.0, sous licence MIT-CMU. Le transport USB utilise [pySerial](https://github.com/pyserial/pyserial), version 3.5, sous licence BSD-3-Clause. Ces dépendances et leurs notices sont fournies par leurs distributions Python. Les références de protocole NIIMBOT sont documentées dans le [guide des étiquettes](docs/19-stock-qr-et-etiquettes.md); aucun client tiers ni code de ces dépôts n’est embarqué ou exécuté.
