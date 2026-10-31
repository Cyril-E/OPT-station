# Périmètre fonctionnel du lecteur et de l’inventaire

Ce document fixe les fonctions attendues d’OPT Station. Les fonctions réalisées et leurs limites sont précisées dans le [mode d’emploi](06-mode-emploi.md), l’[architecture](07-architecture.md) et la [feuille de route](14-feuille-de-route.md).

## Plateforme et phases

| Élément | Profil logiciel et matériel | Validation à prévoir |
| --- | --- | --- |
| Ordinateur | Raspberry Pi 5; autres plateformes selon les dépendances disponibles | Système, architecture et périphériques réellement utilisés |
| Système | Raspberry Pi OS 64 bits, Python 3.11 ou ultérieur | Image installée, pilotes et session graphique |
| Stockage | Support compatible avec le système et les données persistantes | Espace libre, droits et sauvegarde |
| Tags | NFC-V/ISO 15693, profil SLIX2 pris en charge par l’adaptateur actuel | Mémoire, protections et écriture suivie de relecture |
| Acquisition QR | Caméra compatible avec la pile Raspberry Pi; profil OV5647 qualifié | Netteté et décodage sur le montage final |
| Pilotage | Navigateur, écran et souris; affichage local optionnel en plein écran | Écran tactile et clavier à l’écran selon le matériel |
| Accès réseau | Navigateur d’une machine du réseau local | Niveaux d’accès, adresses et fonctions autorisées |

Le modèle d’écran, la nappe et l’orientation doivent être compatibles avec le Pi. Le Touch Display 2 de 10,1 pouces est une option pour le Pi 5; voir la [fiche écran](10-ecran-tactile.md). La [fiche caméra](11-camera-qr.md) distingue les profils et les essais nécessaires.

L’adaptateur NFC réel utilise l’ACS ACR1552U-M1 USB-A avec PC/SC/CCID. Le lecteur d’une imprimante est une intégration distincte; sa présence ne prouve pas la disponibilité de données de consommation par une API.

## Langues

L’interface propose **français et anglais**. Les autres langues pourront être ajoutées selon les besoins; le [guide des langues](22-langues-interface.md) décrit le fonctionnement livré.

Prévoir un sélecteur de langue accessible depuis la station et l’interface web, avec mémorisation du choix dans chaque navigateur. Les onglets, formulaires, aides, confirmations et messages d’erreur doivent être disponibles dans les deux langues.

La traduction concerne la présentation. Elle conserve les clés, valeurs et unités du format OpenPrintTag, les identifiants de bobine, le texte QR brut et les données enregistrées. Les noms de produits et textes saisis par l’utilisateur ne sont pas traduits automatiquement. Les formats d’affichage des nombres et dates peuvent suivre la langue choisie, avec une sérialisation API/NFC identique.

Les traductions doivent être regroupées dans des catalogues à clés stables, pour ajouter ensuite une langue sans dupliquer les écrans ou la logique métier. Prévoir un repli en français si une traduction manque. Lors de l’implémentation, vérifier les parcours Lecture, Écriture, Inventaire et favoris dans les deux langues, ainsi que l’absence de modification des données lors d’un changement de langue.

## Parcours métier principaux

Les trois parcours métier principaux sont organisés ainsi :

| Onglet | Rôle | Actions principales |
|---|---|---|
| Lecture | Lire le tag et consulter les informations de la bobine | Afficher les valeurs disponibles et la présence dans le stock; ajouter la bobine à l’inventaire ou l’en retirer |
| Écriture | Préparer les données d’un nouveau tag ou modifier un tag existant | Créer une fiche depuis QR, données favorites ou saisie manuelle; relire puis corriger les champs d’un tag existant; écrire et vérifier |
| Inventaire | Consulter l’état des différentes bobines et leurs valeurs enregistrées | Afficher la liste du stock et les fiches détaillées, avec les dernières quantités connues et dates de lecture |

Cette structure doit fonctionner avec écran et souris en V1, puis être reprise sur l’écran tactile.

L’accès par navigateur sur le réseau local complète ces trois onglets : il permet de consulter l’inventaire, d’en retirer une bobine et de définir des données favorites réutilisables dans le parcours Écriture.

## Onglet Lecture

La lecture d’un tag doit retrouver la bobine concernée dans l’inventaire, ou proposer son ajout si elle est inconnue. Le logiciel doit présenter les informations du matériau et les données de suivi disponibles, en indiquant leur origine et leur date de dernière observation ou modification.

Présenter une action **Ajouter à l’inventaire** si la bobine est absente, ou **Retirer de l’inventaire** si elle est présente. L’ajout est explicite et doit éviter les doublons. Le retrait concerne la présence dans le stock; il conserve les données écrites sur le tag. Le simple scan consulte le tag et rafraîchit la fiche d’une bobine déjà connue sans déclencher d’écriture NFC.

Pour la quantité restante, le standard fournit `consumed_weight` (Aux, clé 0, en grammes). Le calcul documenté est :

`quantité restante = poids net de matière initial − consumed_weight`

Le poids initial est `actual_netto_full_weight` (Main, clé 17) lorsqu’il est connu; à défaut, le standard prévoit `nominal_netto_full_weight` (Main, clé 16). Le résultat fondé sur un poids nominal doit être présenté comme une estimation. Une consommation absente ne vaut pas zéro; si les données nécessaires manquent, afficher une quantité inconnue.

Lorsqu’une imprimante compatible actualise le tag pendant l’utilisation de la bobine, la station Raspberry Pi relit ensuite les valeurs du tag pour rafraîchir le suivi et l’inventaire. Le tag assure ainsi le transfert de l’état de consommation entre l’imprimante et la station.

Le parcours attendu est : création/configuration du tag sur la station → utilisation de la bobine et actualisation du tag par l’imprimante → nouveau scan sur la station → mise à jour de la fiche d’inventaire de cette même bobine. Le logiciel doit reprendre la consommation relue sur le tag et éviter de réécrire par défaut une ancienne valeur de l’inventaire.

L’inventaire conserve la dernière valeur connue jusqu’au prochain scan. La date du scan doit être enregistrée localement; elle ne représente la date d’écriture par l’imprimante que si cette information est effectivement disponible. La qualification du suivi PrusaLink couvre une **Prusa CORE One** avec le firmware **8.0.0+17068**. Le moment exact de ses écritures NFC reste à relever lors des essais matériels. L’[étude des API](16-etude-api-imprimante.md) prépare le suivi réseau; les adresses et identifiants seront saisis dans Configuration.

## Onglet Écriture

Cet onglet propose deux parcours : **Créer un nouveau tag** et **Modifier un tag existant**.

### Créer un nouveau tag

Trois sources de données doivent être proposées dès la première version :

1. Scanner le QR fourni avec une bobine, reconnaître son contenu et rechercher les informations correspondantes lorsqu’un mapping documenté ou une fiche de référence existe.
2. Entrer manuellement les informations, avec possibilité de compléter ou corriger les données issues du QR avant écriture.
3. Choisir une fiche favorite définie depuis l’interface web, puis compléter et vérifier les informations propres à la nouvelle bobine.

Un QR peut porter un identifiant de produit, un identifiant de bobine, une URL ou un autre texte; il ne contient pas nécessairement toutes les informations matière. Le logiciel doit conserver le contenu brut, montrer ce qui a été reconnu, signaler les champs manquants et proposer la saisie manuelle si le format est inconnu. Une même référence produit peut correspondre à plusieurs bobines physiques.

Avant écriture, présenter la fiche à confirmer, valider les types/unités/limites des champs OpenPrintTag et conserver la provenance des valeurs. Les informations inconnues restent inconnues; aucune date de fabrication ou valeur technique ne doit être inventée pour remplir un formulaire.

### Modifier un tag existant

Lire d’abord le tag, charger ses valeurs dans la fiche et permettre les corrections demandées par l’utilisateur, par exemple un poids ou une couleur. Montrer les anciennes et nouvelles valeurs avant écriture, avec des intitulés qui distinguent les différents poids :

| Information à corriger | Donnée OpenPrintTag concernée |
|---|---|
| Poids net nominal initial de matière | Main, clé 16 : `nominal_netto_full_weight`, en grammes |
| Poids net réel initial de cette bobine | Main, clé 17 : `actual_netto_full_weight`, en grammes |
| Poids du contenant vide (tare) | Main, clé 18 : `empty_container_weight`, en grammes |
| Quantité de matière déjà consommée | Aux, clé 0 : `consumed_weight`, en grammes |
| Quantité restante | Valeur calculée à partir du poids net initial et de `consumed_weight` |
| Couleur principale et couleurs secondaires | Main : `primary_color` (clé 19), `secondary_color_0` à `secondary_color_4` (clés 20 à 24), selon le type standard `color_rgba` |

Si l’interface permet d’ajuster directement le restant, elle doit recalculer `consumed_weight` à partir du poids net initial connu, montrer la modification et signaler les valeurs incohérentes. Cette correction ne doit pas changer implicitement le poids initial. La modification d’une couleur doit respecter la représentation OpenPrintTag du champ concerné.

Une correction sur la même bobine conserve son identité. Les champs non modifiés, les clés inconnues, les offsets et tailles de régions doivent être préservés selon les règles de mise à jour du standard. Les poids initiaux et couleurs appartiennent à Main : leur modification dépend de ses protections. Un champ protégé doit être indiqué comme non modifiable; la station ne doit pas contourner le verrouillage.

### Vérifier l’écriture

Après écriture, relire le tag et vérifier le résultat avant d’annoncer la réussite et de confirmer son association à une bobine de l’inventaire. Préserver les données inconnues et respecter les protections des régions Main et Aux. Distinguer création d’un tag, mise à jour d’un tag existant, remplacement d’un tag pour la même bobine et réemploi d’un tag pour une nouvelle bobine.

La conformité aux définitions OpenPrintTag s’applique aux deux parcours : noms et clés des champs, types, unités, valeurs d’enums, limites de taille, encodage et règles d’évolution. Les informations complémentaires d’inventaire restent distinctes des champs standard du tag.

## Onglet Inventaire

L’inventaire est une fonction de la première version. Il doit conserver les bobines d’une session à l’autre et permettre leur ajout, consultation, recherche, modification et sortie du stock. Une bobine physique doit avoir sa propre fiche, même si une autre possède le même matériau, le même produit ou le même QR produit.

L’onglet présente l’état des différentes bobines en stock et leurs valeurs disponibles, avec accès au détail de chaque fiche. Les commandes d’ajout et de retrait sont également accessibles depuis l’onglet Lecture, après identification de la bobine.

Données de la fiche :

- identité de la bobine physique et lien avec son tag;
- marque, matériau, couleur et référence produit lorsqu’elles sont connues;
- poids initial et dernière quantité consommée/restante connue, avec provenance et date;
- date de première entrée en stock et ancienneté de stockage, visibles dans la liste et la fiche détaillée;
- état de la bobine et, si utile, emplacement et notes;
- dernier résultat de lecture ou d’écriture du tag, en distinguant un changement enregistré dans l’inventaire d’un changement réellement écrit et relu sur le tag.

Le standard distingue `instance_uuid` (bobine/emballage physique), `package_uuid`/GTIN (référence produit) et `material_uuid` (matériau). Un scan répété doit retrouver la même fiche. La règle d’association doit aussi gérer le remplacement d’un tag et le réemploi d’un ancien tag sans fusionner deux bobines différentes.

Les informations d’inventaire peuvent être plus riches que le contenu du tag : toutes n’ont pas à être écrites en NFC. Par exemple, le champ standard `storage_location` (Aux, clé 4) est limité à 8 octets. Au retour de l’imprimante, la consommation relue sur le tag doit rafraîchir l’inventaire avec la date de lecture. Si une modification locale en attente ou d’autres données créent un conflit, montrer les valeurs et demander laquelle retenir avant toute écriture; ne pas écraser silencieusement une valeur.

### Numéro lisible de bobine

Fonction implémentée dans **0.10.0.dev0**; voir le [guide des numéros et notes](24-numeros-et-notes-inventaire.md). À la première entrée d’une bobine dans le stock, lui attribuer automatiquement un numéro unique au format **Bxxxx**, en commençant par **B0000**, puis **B0001**, **B0002**, etc. Utiliser au moins quatre chiffres, puis poursuivre au-delà de B9999 sans revenir à zéro. Ce numéro concerne la bobine physique; un modèle ou favori n’en reçoit pas. Il complète les identifiants logiques et matériels existants sans les remplacer.

La séquence est commune à toute la station, persistante et protégée contre deux créations simultanées depuis des clients différents. Le même numéro suit la bobine après redémarrage, relecture, correction, association RFID, retrait, retour en stock et archivage. Un numéro déjà attribué n’est jamais réutilisé pour une autre bobine; il est indépendant du compteur des bobines consommées. Répéter l’ajout de la même bobine ne lui attribue pas un nouveau numéro.

Afficher ce repère dans la liste et la fiche d’inventaire, sur l’étiquette lorsqu’elle est imprimée, ainsi que dans les consultations MCP. La recherche doit permettre de retrouver directement une bobine par son numéro, par exemple **B0042**, y compris dans les archives.

**Parcours sans impression :** créer la fiche et entrer la bobine au stock, noter son numéro au feutre sur l’emballage, puis rechercher ce numéro dans l’inventaire à l’ouverture. Depuis la fiche retrouvée, préparer les données, confirmer l’écriture du tag RFID, le relire et l’associer à cette même bobine. Ce parcours ne demande ni impression ni scan QR et conserve l’identité, la date d’entrée et les données de la fiche existante. L’étiquette QR complète reste une autre façon de retrouver la bobine et ses données.

### Notes de l’inventaire et des bobines

Deux zones sont implémentées dans **0.10.0.dev0** : un carnet commun à l’inventaire et des notes personnelles sur chaque bobine, y compris archivée. Les notes libres peuvent contenir des tares ou des remarques; distinguer contenant vide, filament et poids total, ainsi que mesure et référence indicative. Elles restent séparées des données RFID et ne changent pas automatiquement une quantité ou un modèle.

Les deux types de notes sont persistants, partagés entre les clients autorisés et consultables en lecture par MCP. Une modification concurrente est refusée sans perdre la saisie. Le changement de langue et l’actualisation de l’état ne suppriment pas un brouillon. Voir le [guide des notes](24-numeros-et-notes-inventaire.md#carnet-commun-et-notes-par-bobine).

### Fin de bobine, archivage et compteur

Fonction implémentée dans **0.9.0.dev0**; voir le [guide des archives et du compteur](23-bobines-terminees-et-archives.md). Depuis la liste ou la fiche d’inventaire, le bouton **Marquer comme terminée** permet de :

- Faire passer la bobine à l’état **Terminée** et la sortir du stock actif.
- Conserver sa fiche dans des archives consultables, avec son identité et les données connues.
- Ajouter cette bobine au **compteur des bobines consommées**, une seule fois par bobine physique.

Un simple retrait du stock reste distinct d’une fin de bobine et n’alimente pas ce compteur. Une demande répétée, une actualisation ou une relecture du même tag ne doit ni créer une seconde archive ni recompter la bobine. L’action porte sur l’inventaire et ne modifie pas implicitement les données du tag RFID.

### Date d’entrée en stock et ancienneté

Fonction implémentée dans `0.7.0.dev0`; voir le [guide du parcours](19-stock-qr-et-etiquettes.md). Afficher **Entrée en stock** avec la date de première réception dans l’inventaire, ainsi que l’ancienneté calculée depuis cette date, par exemple « En stock depuis 42 jours ». Cette information doit être visible dans la liste des bobines et dans leur fiche, depuis le Pi comme depuis une machine distante. Elle concerne les bobines sous QR comme celles équipées d’un tag RFID.

Enregistrer cette date lors du premier ajout effectif de la bobine au stock, même sans tag. La conserver lors des lectures, corrections, changements QR → RFID et sorties puis retours de la même bobine. Un éventuel événement de retour en stock est distinct de la première entrée; il ne remet pas son ancienneté à zéro. La date de fabrication et la date de dernière lecture restent des informations séparées.

Proposer un tri **Plus anciennes en premier**, basé sur cette date, pour faciliter l’utilisation prioritaire des bobines reçues les premières. Les dates inconnues sont signalées et placées après les dates connues dans ce tri. Le changement de tri n’effectue aucune sortie de stock ni sélection automatique sur l’imprimante.

La date d’entrée est une donnée persistante d’inventaire. Pour les fiches existantes, ne récupérer une ancienne date que si une trace fiable de leur première entrée est disponible. À défaut, afficher **Date inconnue**, sans utiliser la dernière lecture, la date de migration ou la date de fabrication comme date d’entrée supposée. L’âge de stockage reste alors inconnu.

### Bobines sous emballage hermétique : QR puis tag RFID

Fonction implémentée dans `0.7.0.dev0`; voir le [guide du parcours](19-stock-qr-et-etiquettes.md). Une bobine neuve peut entrer au stock alors qu’elle est encore dans son emballage hermétique contre l’humidité. La création de sa fiche ne doit pas exiger d’ouvrir cet emballage, de fixer un tag ou de présenter un tag au lecteur.

Le parcours attendu est : **réception → fiche et entrée en stock sans tag → étiquette QR sur l’emballage → ouverture pour utilisation → scan QR → préparation, confirmation et vérification du tag RFID**.

Dans l’inventaire, chaque ligne ou carte de bobine et sa fiche détaillée présentent un petit badge avec icône et texte, pour distinguer les deux étapes du parcours :

| Badge | Signification |
| --- | --- |
| **En stock · QR** | Bobine encore emballée, repérée par son étiquette QR, sans association RFID vérifiée. |
| **En service · RFID** | Bobine ouverte pour utilisation, dont le tag a été écrit, relu et associé avec succès à la fiche existante. |

La bascule vers RFID est automatique après cette vérification réussie. Scanner le QR ou préparer les données ne suffit pas; un échec d’écriture conserve l’état précédent et affiche le problème séparément. L’indicateur est enregistré avec la bobine, conservé après redémarrage et identique sur le Pi et les navigateurs distants après actualisation. Il décrit l’étape de préparation et d’identification de la bobine; « En service » ne signifie pas qu’une impression est actuellement en cours. La présence dans l’inventaire reste distincte : le passage à RFID ne retire pas automatiquement la fiche du stock.

- À l’entrée en stock, renseigner les informations connues depuis une fiche favorite, une saisie ou une source QR reconnue. Attribuer une identité propre à la bobine physique, distincte de la référence produit, même si plusieurs bobines sont identiques.
- Générer un QR à partir de cette fiche, avec son identifiant de bobine et **l’ensemble des données applicatives OpenPrintTag destinées au tag RFID**, sans limiter le contenu à une sélection de champs. Inclure toutes les valeurs renseignées de Main et Aux, ainsi que les identifiants logiques de la bobine, du produit et du matériau lorsqu’ils sont connus. Le QR doit permettre de reconstruire ces données avec les mêmes valeurs, types, unités et champs absents, sans consulter le réseau ou la fiche d’inventaire. Conserver notamment la distinction entre poids nominal, poids réel net, tare et consommation; une valeur inconnue reste absente. Le numéro matériel du futur tag est relevé lors de son association, distinct de l’identité logique de la bobine portée par le QR.
- Fournir une étiquette à placer sur l’emballage, imprimable depuis OPT Station sur une petite imprimante directement connectée au Pi, **NIIMBOT B3S_P en USB, avec étiquettes 70 × 40 mm**. Réimprimer l’étiquette d’une même bobine conserve son identité. Le format `OPT1`, son aperçu et ses limites de lisibilité sont décrits dans le [guide d’implémentation](19-stock-qr-et-etiquettes.md).
- À l’ouverture de la bobine pour son passage en production, scanner ce QR pour retrouver la fiche d’inventaire et préremplir la préparation du tag. Présenter les informations avant confirmation; un scan seul ne déclenche aucune écriture RFID.
- Après présentation du tag, appliquer les contrôles existants d’identité, de capacité et de protections, effectuer la sauvegarde, écrire puis relire. Associer le tag à la bobine existante après vérification réussie. Un échec conserve la fiche de stock et indique l’absence d’association vérifiée.
- Le passage de l’état emballé à l’état en utilisation conserve la fiche et son historique. Scanner plusieurs fois le même QR ne crée pas de doublon; deux bobines du même produit restent distinctes. Une étiquette ancienne ne doit pas réinitialiser la consommation d’une bobine déjà utilisée : présenter les éventuels écarts entre QR, inventaire et tag avant de retenir les données.

Ce format d’étiquette propre à OPT Station devra être reconnu explicitement, en conservant le traitement existant des QR fabricant, GTIN, URL et textes inconnus. La génération du QR et son import constituent de nouvelles fonctions de `0.7.0.dev0`, postérieures à `v0.6.0`.

### Impression des étiquettes QR depuis le Pi

Fonction implémentée dans `0.7.0.dev0` : utiliser une petite imprimante d’étiquettes, **NIIMBOT B3S_P en USB, avec étiquettes 70 × 40 mm**, directement connectée au Raspberry Pi. Le Pi génère l’étiquette et transmet la demande à l’imprimante, sans passage par un ordinateur ou un téléphone intermédiaire. Le matériel retenu est la **NIIMBOT B3S_P en USB, avec étiquettes 70 × 40 mm**; l’impression et la relecture du QR papier sont validées. Le profil B1 reste à tester sur un exemplaire physique.

- Proposer **Imprimer l’étiquette** après génération du QR et **Réimprimer** depuis la fiche d’inventaire. Une réimpression conserve l’identifiant de la bobine; elle ne crée ni nouveau stock ni écriture RFID.
- Ajouter les réglages d’imprimante et de format d’étiquette dans **Configuration**, avec un aperçu avant impression. Les demandes depuis un navigateur distant en accès complet utilisent l’imprimante raccordée au Pi, comme les autres périphériques de la station.
- Prévoir le QR complet et, selon la place disponible, un repérage lisible : nom de bobine, matière, couleur et date d’entrée en stock. Adapter le format et la mise en page pour conserver un QR lisible; ne supprimer aucune donnée destinée au RFID pour le faire tenir. Si le contenu ne tient pas de façon lisible, demander un format adapté avant impression.
- Distinguer une étiquette préparée, une demande transmise et une erreur d’impression selon les retours disponibles du périphérique. Une imprimante absente ou en erreur doit permettre de reprendre l’impression sans recréer la bobine.

**Pistes vérifiées le 25 octobre 2026 :** la bibliothèque communautaire [niimprintx](https://github.com/niimbot/niimprintx) annonce la B1 parmi les modèles testés et propose des transports USB série et Bluetooth sous Linux. Le [centre de téléchargement du fabricant](https://www.niimbot.com/us/downloadCenter?showDetail=true) présente la série B1 dans son logiciel Windows. Ces sources donnent une piste d’intégration; elles ne constituent pas une validation sur le Raspberry Pi de la station. Tester la variante exacte, le transport, les dépendances arm64, le format d’étiquette et le décodage par la caméra réelle avant d’annoncer la compatibilité.

## Accès web sur le réseau local

Depuis une machine connectée au réseau local, l’utilisateur doit pouvoir ouvrir l’interface du Raspberry Pi dans un navigateur. Cet accès fait partie de la V1 et complète le pilotage local par écran et souris.

| Fonction web | Comportement attendu |
|---|---|
| Consulter l’inventaire | Afficher les bobines, leurs états, les valeurs enregistrées, la date d’entrée et l’ancienneté en stock, la date de dernière lecture; permettre le tri des plus anciennes en premier |
| Retirer une bobine | Retirer du stock la bobine sélectionnée, même sans présenter son tag au lecteur |
| Définir des données favorites | Créer, nommer, enregistrer et modifier des fiches modèles réutilisables pour préparer les données d’une bobine |

La station locale et les navigateurs utilisent le même inventaire conservé sur le Raspberry Pi. Un retrait effectué depuis le navigateur doit être visible dans l’onglet Inventaire local et dans les autres vues après actualisation. Il conserve le contenu du tag physique. Si cette bobine est rescannée, proposer son ajout explicite au stock plutôt que l’y remettre automatiquement.

Le navigateur affiche l’état connu de l’inventaire. La consommation actualisée par l’imprimante est intégrée lors du prochain scan du tag sur la station. L’identité de la bobine sélectionnée doit rester stable entre les vues afin d’éviter un retrait appliqué à une autre fiche.

### Données de bobines favorites

Les fiches réutilisables fonctionnent ainsi : les « données favorites » sont des fiches modèles réutilisables, par exemple marque, type et nom de matériau, couleur, diamètre, poids net nominal ou paramètres d’impression connus. Les champs précis à proposer restent à détailler. Chaque favori possède un nom de repérage dans l’application; les données destinées au tag respectent les définitions OpenPrintTag.

Les favoris sont enregistrés sur le Raspberry Pi et accessibles depuis l’interface web et le parcours Écriture local. Choisir un favori préremplit la fiche d’une nouvelle bobine; l’utilisateur peut adapter les valeurs avant validation et écriture du tag.

Un favori porte des valeurs réutilisables de matériau/produit. Les identifiants de bobine physique ou de tag, le poids réel mesuré propre à une bobine, la consommation, la quantité restante et la présence dans le stock appartiennent à chaque bobine et doivent être traités individuellement. Deux bobines créées depuis le même favori doivent conserver des identités distinctes. Modifier un favori prépare les utilisations futures; les bobines et tags existants ne sont pas modifiés automatiquement.

## Points restant à qualifier

- Compatibilité du montage final : alimentation, stockage, écran, orientation, mise à l’échelle et saisie tactile.
- Détection, autofocus et netteté des QR à courte distance sur chaque profil de caméra annoncé comme compatible.
- Moment de mise à jour des tags par une imprimante compatible et données de consommation réellement accessibles par Prusa Connect.
- Sauvegarde planifiée sur support externe inscriptible, ainsi que les nouvelles fonctions décrites dans la [feuille de route](14-feuille-de-route.md).
- Remplacement d’un tag depuis l’inventaire sur un tag physique de test; les contrôles logiciels et la reprise après interruption sont couverts en simulation.

## Critères d’acceptation pour les futurs essais

- Lire un tag valide et retrouver la bonne bobine, sans créer de doublon à chaque scan.
- Depuis Lecture, ajouter ou retirer explicitement une bobine de l’inventaire sans modifier son tag.
- Créer une fiche et un tag depuis un QR reconnu, puis depuis une saisie manuelle; permettre de compléter les informations manquantes.
- Refuser de présenter un QR inconnu comme une fiche matière validée et ne pas inventer de valeurs.
- Écrire un tag de test, relire et vérifier les valeurs; signaler une écriture échouée ou une région protégée.
- Depuis Écriture, modifier un poids ou une couleur d’un tag existant lorsque les protections l’autorisent, puis vérifier que les champs non modifiés et l’identité de la bobine sont conservés.
- Afficher la quantité restante comme inconnue, estimée ou calculée à partir d’informations connues, avec leur date et leur origine.
- Après utilisation d’une bobine sur l’imprimante cible, relire le tag et rafraîchir sa consommation dans la même fiche d’inventaire sans réécrire une ancienne valeur.
- Conserver l’inventaire après redémarrage et distinguer plusieurs bobines du même produit.
- Enregistrer une bobine encore emballée dans le stock sans tag RFID et générer son étiquette QR avec son identité et les valeurs connues.
- Vérifier le parcours fiche → génération QR → lecture QR → préparation RFID : toutes les données OpenPrintTag prévues sont restituées sans perte de champ ou de précision, avec les mêmes types, unités, identifiants logiques et valeurs inconnues, même sans accès au catalogue ou à l’inventaire réseau.
- Imprimer une étiquette sur l’imprimante directement connectée au Pi, puis la scanner avec la caméra réelle et vérifier la restitution de l’ensemble des données RFID prévues, pour les contenus et formats d’étiquette pris en charge.
- Depuis le Pi et un navigateur distant en accès complet, imprimer puis réimprimer la même fiche avec la même identité; signaler une imprimante absente ou une erreur sans créer de doublon de stock ni effectuer d’écriture RFID.
- À l’ouverture, scanner l’étiquette QR, préparer et vérifier le tag, puis l’associer à la fiche existante sans créer une seconde bobine; un échec d’écriture ne doit pas être annoncé comme une association réussie.
- Afficher le badge **En stock · QR**, puis **En service · RFID** uniquement après écriture et relecture réussies; vérifier que le badge est conservé après redémarrage, identique dans les vues locales et distantes, et inchangé après un simple scan ou une écriture échouée.
- Réimprimer ou scanner plusieurs fois une étiquette sans créer de doublon, confondre deux bobines identiques ni réinitialiser une consommation déjà connue.
- Depuis Inventaire, consulter l’état et les valeurs connues de chaque bobine, avec la date de dernière lecture.
- Afficher la date de première entrée en stock et l’ancienneté pour les bobines QR et RFID; vérifier leur conservation après redémarrage, lecture, passage au RFID et retour en stock, ainsi que leur cohérence entre vues locales et distantes.
- Vérifier le tri des plus anciennes entrées en premier et l’affichage explicite des dates inconnues, sans attribuer de fausse date aux anciennes fiches lors de la migration.
- Depuis le navigateur d’une autre machine du réseau local, consulter le même inventaire et retirer une bobine; constater le retrait dans la vue locale après actualisation et proposer un ajout explicite lors d’un nouveau scan.
- Définir un favori par l’interface web, le retrouver après redémarrage et l’utiliser dans Écriture pour préparer une nouvelle bobine avec des champs conformes OpenPrintTag.
- Créer deux bobines à partir du même favori avec des identités distinctes et vérifier qu’une modification du favori ne change pas leurs tags ou leur consommation.
- En V1, réaliser les parcours de consultation, saisie, scan et écriture sur l’écran avec la souris.
- En deuxième phase, réaliser les parcours de consultation, saisie, scan et écriture depuis l’écran tactile.

La publication future sur GitHub et le mode d’emploi restent prévus. Le manuel devra couvrir ces parcours, l’inventaire, l’accès web sur le réseau local, les favoris et les limites du suivi de consommation.

## Références locales

Les noms, clés et règles de poids sont tirés de [main_fields.yaml](../references/upstream/openprinttag-specification-060e420/data/main_fields.yaml), [aux_fields.yaml](../references/upstream/openprinttag-specification-060e420/data/aux_fields.yaml) et du [format NFC](../references/upstream/openprinttag-specification-060e420/docs_src/nfc_data_format.md), au commit officiel gelé `060e420892d66c062c8af440c97701aab96bac79`. Les parcours et phases sont les exigences du projet, pas de nouvelles règles du standard.
