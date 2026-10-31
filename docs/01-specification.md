# Synthèse technique OpenPrintTag

Collecte et résumé établis le 23 octobre 2026 à partir du dépôt officiel figé au commit 060e420892d66c062c8af440c97701aab96bac79. Les fichiers source complets sont dans [la copie locale du dépôt](../references/upstream/openprinttag-specification-060e420/).

## Ce que le standard décrit

OpenPrintTag définit un format de données matériaux porté dans un tag NFC, ainsi que les règles de lecture, mise à jour et protection. Le chemin de données documenté est :

1. Couche radio NFC-V, basée sur ISO/IEC 15693-3.
2. Message NDEF dans un TLV NDEF, avec un enregistrement MIME application/vnd.openprinttag. Cet enregistrement ne doit pas être découpé en chunks. D’autres TLV ou enregistrements NDEF peuvent coexister; l’enregistrement OpenPrintTag n’est pas nécessairement le premier.
3. Charge utile OpenPrintTag composée de régions Meta, Main et, si présente, Aux.
4. Chaque région est une carte CBOR à clés entières. Les définitions exactes sont les YAML locaux dans references/upstream/openprinttag-specification-060e420/data/.

Ce n’est donc ni un simple JSON posé sur une étiquette NFC, ni un format de tag NFC-A/NTAG interchangeable avec NFC-V.

## Régions et règles d’évolution

| Région | Contenu et rôle | Règles importantes |
|---|---|---|
| Meta | Offsets et tailles des régions Main/Aux, relatifs au début de la charge utile NDEF | Main est toujours présent. Sans offset, il suit Meta. Aux est facultatif; sa présence est signalée par son offset. |
| Main | Marque, matériau, caractéristiques physiques et paramètres d’impression | Données plutôt statiques; le fabricant peut protéger cette région. |
| Aux | Suivi dynamique, par exemple matière consommée | Facultatif, mais fortement recommandé. Minimum 16 octets si présent; 32 octets recommandés. Cette région est conçue pour rester inscriptible. |

Les régions CBOR sont limitées chacune à 512 octets. C’est une limite de section du format, pas la capacité garantie d’un tag physique. Les clés inconnues doivent être ignorées à la lecture et préservées lors d’une mise à jour; les enums inconnus de 0 à 65535 doivent également rester préservés. Les clés dépréciées ne sont jamais réutilisées. Un lecteur doit accepter des cartes CBOR non triées.

Pour mettre à jour un champ, le standard demande de ne pas modifier les autres champs, la Meta, la position ou la taille des régions. Il recommande de n’écrire que dans la région modifiée et, en pratique, que dans les blocs qui diffèrent. Une réinitialisation complète est une opération distincte, destinée à l’initialisation ou au réemploi du tag.

## Champs et encodage

Le schéma exhaustif est conservé dans data/main_fields.yaml, data/meta_fields.yaml, data/aux_fields.yaml et les fichiers d’enums du dépôt source.

- Meta : clés 0–3 pour offset/taille Main et offset/taille Aux.
- Main : clé 8 material_class est obligatoire. Les champs recommandés comprennent GTIN (4), type (9), nom matériau (10), marque (11), date de fabrication (14), poids net nominal/réel (16–17), poids du contenant (18), couleur (19), tags matière (28), densité (29), diamètre filament (30) et températures d’impression (34–38). Le schéma comprend aussi UUID, IDs spécifiques à la marque, couleurs secondaires/CIELAB/RAL, certifications, séchage, géométrie de bobine et champs SLA pour les résines.
- Aux : consommé (0), groupe de travail (1), utilisateur de plage générique (2), dernier brassage de résine (3), emplacement de stockage (4), puis date/prix/devise d’achat privés (5–7).
- Les clés propriétaires ne sont admises que dans les plages réservées de Aux; la plage générique exige un identifiant d’utilisateur et une convention partagée. Le projet devrait commencer sans extensions propriétaires et préserver celles déjà présentes.

Encodages CBOR spécifiés : enum = entier; enum_array = tableau d’entiers; timestamp = entier Unix; number = entier signé/non signé ou flottant; uuid et bytes = chaînes d’octets; string = texte UTF-8; color_rgba = chaîne d’octets RGB ou RGBA (3–4 octets); color_lab = tableau de trois valeurs number. Les champs string:X et bytes:X plafonnent la longueur en octets.

Les UUID utilisent UUIDv5 selon les espaces de noms documentés. Un UUID explicitement encodé prévaut. À défaut, le lecteur peut le déduire à partir de la marque, du nom matériau, du GTIN ou de l’UID NFC. Pour NFC-V, l’UID attendu est un bloc de 8 octets, avec E0 en premier octet; les pilotes peuvent retourner un ordre différent. Il faudra normaliser l’ordre avant toute déduction.

Le standard ne fournit pas de signature cryptographique ni de garantie d’authenticité : un tag peut être cloné.

## NFC : exigences vérifiées

### Tag de référence

Le document physique officiel indique que, pour l’instant, la conformité physique ne couvre que le tag de référence OpenPrintTag MK1; une spécification générique est annoncée pour plus tard. Il s’agit d’une étiquette passive circulaire d’environ 90 mm, avec une antenne imprimée d’environ 79 mm, et une puce NXP ICODE SLIX2/SLX2 selon la nomenclature du document. La table physique indique 316 octets de mémoire, tandis que les notes techniques parlent d’un tag SLIX2 de 320 octets. Le générateur web affiche 312 octets libres pour son profil courant. Ces nombres décrivent des couches/configurations différentes et ne doivent pas être fusionnés en une capacité universelle; le tag réel et les octets NDEF/CC/TLV doivent être mesurés.

### Lecteur et implantation

Le document physique fixe pour un lecteur conforme :

- protocole ISO/IEC 15693-3 NFC-V;
- antenne circulaire de 72 à 80 mm, 75 mm typique;
- puissance RF typique de 1 W, maximum 1,6 W;
- fréquence de résonance 13,553 à 13,567 MHz, 13,56 MHz typique;
- antenne parallèle au flanc de la bobine, centrée avec une excentricité maximale de 5 cm, aussi proche que possible et à l’écart des grandes masses métalliques.

Le tag doit être posé sur une surface plane non métallique, de préférence sur une joue de bobine et dans l’axe; la source demande une position à 130 mm au plus de l’un ou l’autre côté. Elle recommande une cavité de protection d’au moins 0,25 mm pour la puce. Le détail complet, les dessins et le PDF sont dans docs_src/physical_spec.md et docs_src/media/.

La note technique dit que le format est conçu autour du SLIX2 320 B et peut fonctionner avec d’autres tags NFC-V de capacité suffisante. Le document physique restreint toutefois la conformité au seul MK1 pour le moment. En attendant une clarification générique, distinguer « peut transporter le format » de « tag physiquement conforme au standard ».

### PN532 et options d’architecture

Le protocole requis est NFC-V/ISO 15693. Le manuel NXP du PN532 décrit les modes ISO/IEC 14443-A/B, MIFARE, FeliCa et NFC-IP; il ne liste pas ISO 15693. Il ne convient donc pas au cas OpenPrintTag visé sans changement de matériel. Un lecteur basé sur PN5180 ou PN7160 sait, selon NXP, communiquer en ISO/IEC 15693; ce sont seulement des exemples de contrôleurs à examiner, pas un choix de matériel. Vérifier le module complet, son antenne, sa puissance, son interface Pi, son pilote Linux et l’accès en lecture/écriture aux blocs. La puce seule ne garantit ni un HAT compatible, ni une pile NDEF, ni une bonne antenne.

Les outils Python du dépôt sont des utilitaires de données binaires : rec_info lit et décrit un flux de tag, rec_update modifie un flux initialisé, nfc_initialize construit une structure neuve et opt_check vérifie la cohérence sémantique. Ils ne démontrent pas qu’un périphérique NFC particulier fonctionne sous Raspberry Pi. Ils sont inclus localement mais n’ont pas été exécutés.

## QR et NFC : ne pas supposer une équivalence

Le format OpenPrintTag ne définit pas de représentation QR ni de conversion universelle QR→tag. Le générateur peut ajouter au message NFC un enregistrement NDEF URI facultatif; cet enregistrement n’est pas un QR. Le document physique évoque aussi un QR contenant une URL et un mot de passe pour certains tags protégés, à analyser selon une règle propre à la marque.

Une discussion officielle indique que Prusa place certains identifiants de bobine lus depuis l’emballage/QR dans brand_specific_material_id. C’est un exemple de mapping de marque, pas la preuve qu’un QR quelconque contient les champs matière ni le binaire OpenPrintTag. Un QR peut être un GTIN, un identifiant fabricant, une URL ou un autre texte; il faut capturer son contenu brut, reconnaître seulement les formats documentés, puis résoudre vers la fiche correspondante. Un GTIN peut alimenter le champ GTIN et retrouver un package dans la base. Un identifiant propriétaire ne doit être rangé dans un champ OpenPrintTag qu’avec une règle confirmée. Si le format est inconnu ou ambigu, l’interface doit demander une sélection manuelle.

Pour le projet, l’import guidé de QR fait partie de la première version, par lecteur QR dédié ou caméra; la saisie manuelle doit aussi permettre de configurer les tags. Le choix du dispositif de scan reste ouvert. L’écran tactile est prévu dans un deuxième temps. Le flux NFC reste fondé sur NDEF/CBOR; aucun mapping universel QR→NFC n’est établi ici. Voir le [périmètre fonctionnel](05-cahier-des-charges.md).
