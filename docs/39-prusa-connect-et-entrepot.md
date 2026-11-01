# Prusa Connect : consommation et entrepôt

Disponible depuis **v0.25.0**, cette intégration consulte Prusa Connect depuis le serveur de la station. Elle peut actualiser la consommation des bobines déjà enregistrées dans OPT Station, même quand tous les onglets OPT Station sont fermés. PrusaLink continue de fournir le suivi local et les notifications.

## Accès et mise en route

Dans **Paramètres → Prusa Connect · Consommations et entrepôt**, après activation de l’accès complet :

1. Ouvrir une **nouvelle fenêtre privée Chrome**, puis se connecter à [Prusa Connect](https://connect.prusa3d.com/). Utiliser cette session uniquement pour la station. Ne pas importer le renouvellement d’une session quotidienne encore utilisée dans un navigateur ou PrusaSlicer : les renouvellements concurrents peuvent invalider l’autre session.
2. Dans cette fenêtre, ouvrir les outils de développement Chrome : menu **⋮ → Plus d’outils → Outils de développement**, puis **Application**. Selon la largeur, l’onglet peut être dans le menu **»** des outils.
3. Dans la colonne de gauche : **Stockage → Stockage local → https://connect.prusa3d.com**. Choisir la ligne **`auth.access_token`**, copier uniquement sa valeur et la saisir dans **Jeton d’accès utilisateur Connect** dans OPT Station.
4. Pour conserver la connexion après expiration du premier jeton, copier également la valeur de **`auth.refresh_token`** dans **Renouvellement de la session et accès enregistrés → Jeton de renouvellement, facultatif**. Conserver l’identifiant public du client Prusa par défaut pour une session issue du site Connect.
5. Cocher **Activer la connexion Prusa Connect**, puis **Enregistrer et tester Connect**. Le test est une lecture ; laisser les deux options d’actualisation décochées pour vérifier les correspondances avant toute modification de stock.
6. Choisir l’organisation et l’imprimante. Lorsqu’une seule organisation est accessible, le choix automatique est possible. Enregistrer et tester de nouveau après modification de ces choix.
7. Fermer la fenêtre privée Connect qui a servi à l’import. Cocher ensuite **Actualiser la consommation de la bobine chargée**, et éventuellement **Actualiser aussi les consommations de l’entrepôt**, puis enregistrer.

Ne jamais transmettre les jetons dans une conversation, une issue ou une capture. Ils donnent un accès utilisateur Connect, plus étendu que les seules lectures réalisées par OPT Station. Les mots de passe Prusa et les codes de double authentification restent saisis sur le site Prusa. Sans jeton de renouvellement, un accès expiré suspend les lectures et doit être remplacé dans ce formulaire.

La clé API d’envoi de fichiers de Connect, les accès PrusaLink et les accès caméra ont d’autres usages. Ils ne sont pas assimilés à un jeton utilisateur pour cette intégration.

Ce mode importe une session existante ; il ne prétend pas être un parcours OAuth enregistré au nom d’OPT Station auprès de Prusa. Un parcours d’autorisation tiers officiellement pris en charge pourra remplacer cet import lorsqu’il sera disponible et qualifié. Le client actuel s’appuie sur les requêtes de l’interface web Connect, qui peuvent évoluer indépendamment d’OPT Station.

## Bobine chargée et quantité enregistrée

Le collecteur lit les outils FFF actifs, l’UUID d’instance du matériau chargé depuis NFC, sa masse initiale et son **compteur total de consommation en grammes**. Il ne déduit pas une consommation réelle de l’estimation du fichier d’impression et n’additionne pas le compteur à chaque lecture.

L’UUID d’instance OpenPrintTag doit correspondre exactement à une fiche existante : un nom, une couleur, une référence commerciale ou un UUID de matériau ne suffisent pas. Le poids initial reçu doit aussi correspondre à la masse initiale connue dans cette fiche (priorité à la valeur réelle, puis nominale). Aucune masse initiale inconnue n’est inventée.

L’inventaire reçoit uniquement le compteur total consommé ; le restant est recalculé sur sa masse initiale existante. Les données matériau, notes, numéro de bobine, dates, photos, état stock/en service et archivage restent conservés. Une quantité à zéro n’archive pas automatiquement la bobine. Une bobine absente du stock, terminée ou ambiguë n’est pas modifiée.

Les lectures sont partagées par le Pi, avec un intervalle configurable de **30 à 900 secondes**. La date affichée est la date de **lecture de Connect**, pas une garantie d’horodatage de la dernière extrusion sur l’imprimante. Les outils hors ligne ou non identifiés par NFC ne fournissent pas de nouvelle consommation chargée. Une réponse incomplète, une panne ou un accès refusé conservent les dernières quantités ; les tentatives ralentissent après un échec.

Sur le profil CORE One 8 consulté, le tag reconnu visuellement sans filament chargé laissait encore l’outil sans bobine dans la réponse Connect. Vérifier le chargement depuis le menu de l’imprimante pour qualifier les données de bobine chargée ; la reconnaissance du tag seule ne garantit pas leur émission cloud.

### Corrections et relecture NFC

Une consommation Connect inférieure au compteur local ne le diminue pas. La télémétrie chargée observée fournit des grammes entiers : un écart inférieur à 1 g avec un compteur RFID plus précis est indiqué comme un arrondi, sans modifier la fiche. Les autres baisses sont signalées comme un compteur plus ancien. Une correction explicite de consommation ou de quantité restante, dans l’interface ou par MCP, suspend les actualisations de cette fiche. Dans **Imprimante → Bobine en cours et consommation**, **Reprendre le compteur Connect** permet de les reprendre explicitement, après vérification de la fiche. Les autres bobines continuent leur suivi.

Une mise à jour Connect n’écrit pas physiquement le RFID. La fiche porte `connect_sync` comme provenance et conserve la dernière observation matérielle. Pour une fiche RFID, un compteur reçu peut rester signalé en attente de relecture. Une relecture physique égale ou plus récente acquitte le compteur automatique ; un ancien contenu du tag ne remplace pas une consommation Connect supérieure. Les autres corrections locales sont conservées. L’écriture ou recréation d’un tag reste une action matérielle distincte.

Les écritures RFID en cours ou non réconciliées bloquent l’actualisation de la fiche concernée. Les requêtes MCP conservent leur contrôle de version : relire la fiche avant modification, car le collecteur peut l’avoir actualisée. Le catalogue reste à treize outils ; il n’expose ni accès Connect ni commande cloud.

## Entrepôt Prusa et perspectives de synchronisation

Le client web Connect dispose de lectures paginées pour les bobines de l’entrepôt, leurs UUID d’instance, leur consommation totale, leur restant, leur affectation à une imprimante et leurs archives. Il dispose aussi de requêtes de création, modification et suppression, d’historique et de matériaux personnalisés. Leur présence dans le client web n’établit pas une API tierce stable.

La version actuelle lit l’entrepôt et indique combien de bobines sont reconnues dans OPT Station. L’option d’actualisation permet un flux **Connect → OPT Station pour les quantités** des UUID déjà connus. La télémétrie de la bobine chargée prime sur la copie de son compteur dans l’entrepôt. Les doublons et les bobines archivées dans Connect ne sont pas synchronisés depuis l’entrepôt. Une indisponibilité de cette lecture n’empêche pas la lecture de la bobine chargée.

### Envoyer une bobine depuis l’inventaire

Depuis la fiche d’une bobine de filament active, avec l’accès complet :

1. Cliquer sur **Envoyer vers Prusa Connect**.
2. Vérifier l’organisation destinataire, le nom avec son numéro `Bxxxx`, les quantités et les notes enregistrées.
3. Si un poids ou la consommation manque, ouvrir **Corriger les poids et la consommation**, renseigner les valeurs connues, puis **Enregistrer les valeurs et vérifier**. Le poids nominal désigne le filament neuf annoncé ; le poids réel est le filament neuf effectivement mesuré, sans le contenant. Ces corrections modifient uniquement la fiche locale. Une consommation inconnue reste vide ; saisir zéro seulement si la bobine n’a pas été utilisée. Une correction de consommation suspend son suivi automatique jusqu’à reprise explicite.
4. Cliquer sur **Envoyer cette bobine**. La station enregistre d’abord la référence matériau dans le catalogue Connect si nécessaire, crée une seule fiche, puis contrôle son identité, ses données et sa présence dans la liste de matériaux de l’entrepôt.

L’envoi conserve l’UUID d’instance utilisé par le QR et le RFID. Il transmet les données compatibles connues : marque, matière, couleur, masses initiales, consommation, longueur nominale, diamètre, tare, propriétés matériau, notes et emplacement. Les diamètres en millimètres sont convertis en micromètres pour Connect ; les longueurs restent en millimètres. Les photos et les autres champs locaux restent sur la station. Aucune masse ou consommation inconnue n’est remplacée par zéro pour permettre un envoi.

Le nom d’entrepôt inclut le numéro de bobine sans changer le nom du matériau. La création est suivie, si nécessaire, d’une modification limitée à ce nom. Aucune commande d’imprimante ni écriture RFID n’est envoyée. L’envoi conserve la fiche locale et ses versions ; l’enregistrement explicite de corrections de poids est une action distincte. Le journal d’envoi est ajouté dans la base SQLite et inclus dans les sauvegardes d’inventaire.

Connect peut accepter une fiche contenant seulement une copie des données matériau, sans l’afficher dans son entrepôt. Le contrôle des seules fiches brutes est donc insuffisant. La station vérifie également le catalogue qui alimente l’interface Connect et son nombre de bobines. Si une fiche existe mais sa référence manque au catalogue, l’aperçu propose **Rendre la bobine visible** : seule la référence matériau est enregistrée ; la bobine, son identifiant, ses quantités et ses notes ne sont pas recréés ni écrasés.

Une seconde demande recherche d’abord le même UUID et confirme sa présence sans créer de doublon ni écraser ses quantités ou ses notes distantes. Plusieurs fiches portant le même UUID, ou le même numéro visible avec une autre identité, bloquent toute nouvelle création. Si la réponse d’une création est perdue, le journal permet une relecture et une reprise après redémarrage. Si aucune fiche ne peut être identifiée avec certitude, la station ne relance pas une création aveugle. Une modification locale ou un changement de destination après l’aperçu impose un nouveau contrôle.

Cet envoi est explicite et individuel. La lecture automatique ne crée pas de fiches et ne les réécrit pas dans le cloud. Les outils MCP ne donnent pas accès à cet envoi. La validation réelle vérifie également les bobines dans la page **Matériaux → Dans l’entrepôt** de Connect, avec l’organisation choisie : une présence dans les fiches brutes de l’API ne suffit pas à confirmer leur affichage.

### Limites d’une synchronisation complète

Les bobines distantes inconnues ne sont pas importées et les notes distantes ne remplacent pas les notes locales. Une synchronisation continue des fiches dans les deux sens devra préciser :

- La création et le rapprochement des UUID d’instance, sans fabriquer de doublons à partir d’un UUID de produit.
- L’autorité sur les masses, notes, emplacements, états et archives.
- Les conflits entre une correction manuelle, la télémétrie et une modification dans l’application Prusa.
- Les limites du compte, les droits de l’équipe et la reprise idempotente après une réponse perdue.

## Données privées, sauvegardes et installation

Les accès et options sont enregistrés atomiquement dans **`$HOME/openprinttag-data/connect-settings.json`** par défaut, avec permissions **`0600`**, hors Git. Les jetons ne sont pas renvoyés au navigateur ou au MCP. Ils sont inclus dans les sauvegardes de configuration : conserver ces sauvegardes privées, y compris lorsque le mot de passe facultatif est désactivé.

La restauration d’une configuration désactive la connexion Connect. Vérifier les accès, l’organisation, l’imprimante et les correspondances de stock avant de la réactiver. Les données d’inventaire conservent la provenance et les éventuelles suspensions manuelles.

L’installation habituelle inclut ce collecteur et son formulaire ; aucun paquet supplémentaire, compte préconfiguré ou secret n’est distribué. La connexion et les deux options d’actualisation sont désactivées par défaut. Les requêtes utilisent uniquement les origines HTTPS fixes Prusa, avec validation des certificats et sans suivi des redirections. Le collecteur automatique effectue des lectures GraphQL. Seul l’envoi explicite depuis une fiche autorise l’enregistrement de sa référence matériau, la création d’une bobine et l’attribution de son nom dans l’entrepôt. Une réponse incertaine impose une relecture, sans répétition aveugle de ces opérations. L’autre échange est le renouvellement optionnel de la session.

## Sources et qualification

Sources primaires examinées le **1er novembre 2026** :

- [Documentation Prusa App et OpenPrintTag](https://help.prusa3d.com/article/openprinttag-nfc-filaments-with-prusa-app_1252992) : lecture, écriture, entrepôt et suivi des bobines chargées.
- [API mobile Connect](https://connect-mobile-api.prusa3d.com/api/docs.html), à distinguer des requêtes actuelles du client web.
- [Configuration publique du client Connect](https://connect.prusa3d.com/environment.js) : origine GraphQL et identifiant public OAuth du client web.
- [Client web Connect 2026.39](https://connect.prusa3d.com/assets/api-DwXzPGlp.js) : requêtes `GetPrintersFffTelemetry`, `GetWarehouseItems` et opérations d’entrepôt. SHA-256 du fichier étudié : `a4ac7f153ba1d21f9ac98d2c9938b48eaf730cbfce99a8bfd39b39eaeaf364c7`.
- [Gestion de session du client Connect](https://connect.prusa3d.com/assets/jwt-sYePnEOP.js) : accès Bearer et renouvellement des jetons de session.

Les essais automatisés utilisent des données isolées : idempotence, UUID stricts, masses nettes, valeurs inconnues ou anciennes, conflits de versions, corrections manuelles, relecture NFC, erreurs, renouvellement et restrictions d’accès. La connexion réelle, le renouvellement, la liste des organisations et imprimantes et une lecture d’entrepôt vide ont été vérifiés sur un Pi. Les requêtes identifient explicitement la station avec `User-Agent: OPT-Station/<version>` ; le service de compte a refusé le client Python par défaut pendant cette qualification.

La lecture réelle au repos d’une bobine chargée a été rapprochée de l’inventaire par son UUID d’instance, avec une masse initiale concordante. Le compteur cloud entier a été comparé au compteur RFID décimal, dont la précision reste conservée. Le collecteur automatique à 30 secondes a été activé et sa lecture d’arrière-plan vérifiée, sans changement de l’inventaire dans ce cas d’arrondi. Les essais couvrent également le catalogue matériau distinct des fiches brutes, la réparation d’une fiche invisible sans doublon et la correction des poids sans remise à zéro de la consommation.

Pendant une impression réelle, deux augmentations successives du compteur cloud ont actualisé automatiquement la bobine correspondante dans l’inventaire, sans passage sur le lecteur du Pi. Les lectures répétées du même total n’ont pas augmenté sa consommation ni sa version. Le total concorde encore à la fin de l’impression. Les autres fiches, l’identité, le matériau, les notes, les dates et l’état de la bobine suivie sont conservés ; le journal d’écritures RFID de la station est inchangé.

Cette qualification porte sur les grammes entiers transmis par Connect, dont le rythme de publication dépend de l’imprimante et du service cloud. Elle ne promet pas une mesure à chaque seconde ni la précision décimale d’une relecture NFC. La lecture d’un entrepôt contenant la bobine exportée et son rapprochement sont qualifiés. L’actualisation des quantités depuis un lot d’entrepôt distinct reste à qualifier ; l’envoi individuel ne valide pas une synchronisation continue de toutes les fiches dans les deux sens.

La réparation de fiches invisibles est vérifiée dans le catalogue et dans l’interface réelle de Connect, en conservant leurs identifiants et toutes leurs données. Le transfert d’un lot de bobines actives est également qualifié : chaque UUID n’a qu’une fiche, les fiches déjà présentes sont conservées et les données envoyées sont relues. Les valeurs manquantes ont été renseignées uniquement après confirmation explicite. Les identités, notes, modèles, données individuelles non corrigées et opérations RFID sont conservés.

Le catalogue renvoie un nombre de bobines nul (`null`) pour un matériau personnalisé créé avant sa première bobine ; la reprise de cet état est testée sans réenregistrement du matériau ni doublon. Les nouvelles demandes d’envoi retrouvent les mêmes fiches. Les **950 tests sur Pi**, les **948 tests sur Mac** avec deux exclusions liées à l’environnement, ainsi que les sept moteurs JavaScript passent. Ces contrôles de publication n’écrivent aucun tag physique et ne transfèrent aucune bobine supplémentaire.
