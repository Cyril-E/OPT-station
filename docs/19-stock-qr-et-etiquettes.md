# Bobines emballées, QR complets et étiquettes USB

Le parcours permet de stocker une bobine encore emballée, de préparer son étiquette complète, puis de l’associer à un tag RFID après ouverture.

## Recevoir une bobine sans tag

Dans **Inventaire → + Bobine emballée**, choisir un favori, analyser un code reconnu ou renseigner les valeurs connues. Les données matière et de suivi sont disponibles dans les champs courants et dans les sections dépliables. La consommation inconnue reste vide; saisir `0` seulement si elle est connue comme nulle.

**Ajouter au stock et créer le QR** crée une fiche avec une identité de bobine unique, sans lire ni écrire le lecteur RFID. Deux bobines identiques reçoivent des identités distinctes. Un QR OPT Station déjà connu retrouve sa fiche au lieu de créer un doublon.

L’inventaire et le détail présentent :

- **Utilisation : En stock / En service**, modifiable depuis le détail, y compris pour une bobine déjà équipée de RFID;
- **Identification : QR / RFID**, indépendante de l’utilisation;
- **Date d’entrée** et ancienneté pour favoriser les plus anciennes.

Voir le [guide des changements d’utilisation](30-utilisation-et-modeles-inventaire.md).

Le passage au RFID, les lectures et les sorties puis retours de la même bobine conservent la date d’entrée d’origine. La date de dernière lecture reste distincte. Pour les anciennes fiches sans trace fiable de réception, **Date inconnue** et **Ancienneté inconnue** restent affichées; la migration n’invente aucune date. Ces fiches suivent les dates connues dans le tri par ancienneté.

## Contenu du QR

### QR de fiche produit Prusa

Depuis `0.13.1.dev0`, les liens officiels **`prusa3d.com/product/prusament-…`** sont reconnus aussi lorsqu’ils ne commencent pas par `https://`. Exemple testé : [Prusament TPU 95A Lipstick Red 500g](https://www.prusa3d.com/product/prusament-tpu-95a-lipstick-red-500g-nfc/). L’analyse charge la fiche du produit sélectionné, sans reprendre les valeurs des autres couleurs proposées par la boutique.

Marque, matière, nom, poids nominal, couleur du nuancier, diamètre et plages de températures sont préremplis lorsqu’ils sont publiés. La fiche produit ne fournit pas les mesures individuelles : **poids réel, tare, longueur réelle, date de fabrication et consommation restent inconnus**. Lire le tag NFC de la bobine ou renseigner uniquement les valeurs connues. Ne pas réutiliser automatiquement la tare d’une autre bobine. La couleur du nuancier de la boutique reste à vérifier avant enregistrement.

Le parcours fonctionne dans **+ Bobine emballée**, **Écriture** et **Depuis un tag ou un QR** pour créer un modèle. La saisie du texte et le choix **Utiliser ce code** après un scan caméra conduisent au même préremplissage. L’analyse ne crée aucune bobine ni aucun modèle; vérifier les champs puis enregistrer explicitement. Deux bobines du même produit reçoivent chacune leur identité propre.

La récupération nécessite Internet et ne consulte que la page produit officielle, avec taille et durée bornées. Une panne ou une page non reconnue produit un message visible et conserve les champs saisis. Les données vérifiées peuvent ensuite être enregistrées ou préparées pour le RFID sans recharger la page. Les liens vers les fiches individuelles `prusament.com/spool/…`, les GTIN et les QR complets `OPT1` restent pris en charge.

### QR autonome OPT Station

L’étiquette transporte **toutes les données OpenPrintTag renseignées dans Main et Aux**, l’identité logique de la bobine et sa date d’entrée lorsqu’elle est connue. Sa lecture ne consulte ni catalogue ni service Internet pour reconstruire les données RFID. Le numéro matériel du futur tag est relevé au moment de l’association.

Le format propre à OPT Station porte le préfixe `OPT1:` : champs encodés avec les clés et types CBOR du codec RFID, enveloppe versionnée, compression zlib bornée, base32 en majuscules et contrôle SHA-256 tronqué à 64 bits. Ce contrôle détecte une corruption; il ne constitue pas une signature d’origine. Les données lues sont validées comme toute saisie avant préparation du tag. Les grands entiers et les valeurs inchangées restent décodés côté serveur pour éviter un passage avec perte de précision par un nombre JavaScript.

Le format reste distinct des QR fabricant, URL et GTIN. Une étiquette dépassée ne réinitialise pas la consommation d’une bobine déjà équipée d’un RFID. Les champs inconnus d’un ancien tag provoquent un refus d’export complet plutôt qu’une omission silencieuse.

## Préparer le RFID à l’ouverture

Depuis **Étiquette QR → Préparer le tag RFID**, ou depuis **Écriture → Scanner avec la caméra**, charger le QR. Présenter un tag vierge, cliquer sur **Relire le tag présenté**, puis **Vérifier les modifications**. La fiche complète peut être vérifiée et corrigée avant la confirmation d’écriture.

Après **Écrire et vérifier le tag**, la station contrôle le tag, effectue sa sauvegarde, écrit et relit les données. L’association à la fiche existante est enregistrée après réussite. La fiche conserve son identité et sa date d’entrée; aucune seconde bobine n’est créée. La capacité et les protections du tag restent contrôlées : un contenu trop grand est refusé, sans retrait de champs.

En cas d’interruption, le badge reste QR tant que l’association n’est pas vérifiée. **Vérifier un tag déjà écrit** relit le tag sans l’écrire et permet de terminer une association si les données correspondent à la fiche ou à une préparation explicitement confirmée et journalisée. Une différence non expliquée par ces données est refusée. Ne pas relancer automatiquement une écriture incertaine.

Si une bobine sous QR a été sortie du stock, scanner son étiquette depuis **+ Bobine emballée** pour retrouver sa fiche, puis utiliser **Remettre au stock**. Cette action conserve son identité, sa date d’entrée et son historique.

## Configurer l’imprimante d’étiquettes

Dans **Configuration → Imprimante d’étiquettes QR**, depuis le Pi ou un navigateur en accès complet :

1. Choisir le modèle, le port USB du Pi et le format du rouleau.
2. Pour le profil qualifié : **NIIMBOT B3S_P**, **USB**, **70 × 40 mm**, densité initiale **3**. Le port peut être `/dev/ttyACM0`, selon les périphériques branchés. Un chemin stable `/dev/serial/by-id/…` peut être enregistré si disponible.
3. Cliquer sur **Enregistrer et détecter** : l’identification n’imprime aucune étiquette. Le modèle doit correspondre au profil choisi.
4. Cocher **Activer l’impression des étiquettes**, puis enregistrer.

La B3S_P est identifiée avec le code modèle `272`, une tête de 576 points et 8 points/mm. Le rendu 70 × 40 utilise **560 × 320 pixels**, sans interpolation du QR. Le profil B1 est également prévu, mais son essai physique reste à réaliser. Le connecteur actuel utilise l’USB série; le Bluetooth n’est pas implémenté.

Dans l’aperçu d’une bobine, **Imprimer une étiquette** envoie une seule page à l’imprimante du Pi, même si la demande vient d’un autre ordinateur. **Télécharger PNG** permet de conserver l’image. Une nouvelle action explicite permet de réimprimer la même identité. Le QR conserve ses données complètes; si le format rend ses modules trop petits, l’impression est refusée et un format plus grand est demandé.

Les demandes ont un identifiant conservé pendant les reprises réseau : renouveler la même demande consulte son résultat et ne lance pas une seconde copie. Un redémarrage marque les impressions restées en cours comme incertaines. Après une erreur ou une interruption, vérifier le papier avant de demander une nouvelle copie. Le retour du périphérique et la lisibilité physique du QR sont deux vérifications distinctes.

## Installation et sauvegarde

Conserver la procédure du [guide de la station réelle](12-installation-station-reelle.md), avec Python arm64 et un environnement `--system-site-packages`. Les nouveaux composants sont épinglés dans `requirements.lock` : **Segno 1.6.6**, **Pillow 13.0.0**, **pySerial 3.5**. Ils ne nécessitent aucun compte NIIMBOT ni service cloud.

```sh
cd "$HOME/apps/openprinttag-station"
.venv/bin/python -m pip install --only-binary=:all: -r requirements.lock -r requirements-camera.lock
.venv/bin/python -c 'import segno, PIL, serial; print("Composants étiquettes disponibles")'
```

Pour relever les ports sans imprimer :

```sh
.venv/bin/python -m serial.tools.list_ports
ls -l /dev/serial/by-id/
```

Le compte qui exécute le service doit disposer des droits de lecture et d’écriture sur le port. En cas de refus, vérifier le groupe et les droits du périphérique avec l’administrateur avant de modifier la session. Une détection n’envoie aucune commande de calibration, d’avance papier, de firmware ou d’écriture RFID des consommables.

**Sauvegarder le répertoire de données avant mise à jour, serveur arrêté.** Le schéma SQLite passe de 1 à 2 : les fiches existantes sont conservées, l’UID devient facultatif pour les bobines sous QR, et les dates d’arrivée inconnues restent vides. Les journaux de préparation et d’impression sont conservés dans la base. Les réglages USB sont enregistrés atomiquement dans `label-printer-settings.json`, avec permissions `0600`, à inclure dans les sauvegardes privées.

Pour revenir au logiciel `v0.6.0`, arrêter le serveur et restaurer **ensemble** l’ancienne installation et la sauvegarde SQLite antérieure à la migration. L’ancien logiciel refuse le schéma 2. Conserver séparément la base mise à jour pour préserver les changements effectués depuis la mise à niveau. Les fichiers PrusaLink/caméras et d’accès réseau ne sont pas migrés par cette fonction.

## Lire un QR fabricant Prusament

Depuis `0.11.1.dev0`, dans **Nouvelle bobine en stock**, scanner le QR fabricant puis choisir **Utiliser ce code**, ou coller son lien et cliquer sur **Analyser le code**. Le Pi récupère la fiche officielle et préremplit les valeurs disponibles. La progression et le résultat sont affichés dans le formulaire; une panne Internet ou une page illisible affiche une erreur explicite et conserve les champs déjà saisis. Il est possible de réessayer ou d’utiliser la bibliothèque.

Les liens reconnus ont la forme `https://prusament.com/spool/<produit>/<identifiant>/`. Le Pi consulte uniquement ce domaine en HTTPS, sans redirection ni exécution des scripts de la page. Il lit les données `spoolData` fournies par le fabricant et le diamètre explicitement affiché. Les autres liens ne sont pas ouverts. Les formats OPT Station et GTIN conservent leur fonctionnement hors ligne.

Pour un QR individuel de forme `https://prusament.com/spool/<produit>/<identifiant>/`, l’analyse récupère les informations publiées par le fabricant, dont les mesures individuelles lorsqu’elles existent. Le bouton **Ajouter au stock et créer le QR** conserve ensuite les données vérifiées dans un QR OPT Station utilisable hors ligne.

## Vérifications

Les vérifications logicielles et les limites matérielles de la version courante sont détaillées dans le [guide de vérification](08-verification-prototype.md).

La B3S_P réelle a été reconnue en USB. Une impression unitaire a été confirmée par son retour de fin après adaptation à sa séquence de protocole. La relecture de l’étiquette imprimée avec une caméra OV5647 a confirmé : lecture dès la première image, texte QR strictement identique et données Main/Aux, identité et date d’entrée conservées. Aucun tag RFID réel n’a été écrit pendant ces essais; les étiquettes de test ne sont pas ajoutées au stock réel.

Les profils et le protocole USB sont implémentés à partir des références [NiimBlueLib](https://github.com/MultiMote/niimbluelib), [NiimPrintX](https://github.com/labbots/NiimPrintX) et des [documents de protocole](https://github.com/eigger/hass-niimbot/tree/master/docs). Aucun de ces clients n’est exécuté par la station; le connecteur USB est inclus dans l’application.

Les migrations et la conservation des données ont été contrôlées avant installation. La version **0.7.0.dev1** conserve ce parcours et ajoute les [commandes d’alimentation du Pi](20-arret-et-redemarrage-pi.md).

Un second essai utilise la chaîne complète API → rendu PNG → processus USB → B3S_P, avec une fiche dans une base temporaire séparée. L’impression est confirmée; une répétition de la même demande renvoie le même résultat sans nouvelle copie. Le stock réel reste inchangé. Le contenu du premier QR papier permet aussi de produire sans perte une image OpenPrintTag pour le profil de 312 octets, sans l’écrire sur un tag réel.
