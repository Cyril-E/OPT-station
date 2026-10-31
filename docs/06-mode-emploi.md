# Mode d’emploi d’OPT Station

L’onglet **Configuration** regroupe le matériel détecté, les thèmes clair/sombre, la langue et les accès distants. Les niveaux de partage sont **Désactivé**, **Inventaire et modèles** et **Accès complet sans code**, persistants jusqu’à modification. Voir le [guide Configuration et apparence](15-configuration-et-apparence.md).

Depuis une autre machine du même réseau, ouvrir l’adresse annoncée par la station. Le mode **Inventaire et modèles** permet de consulter le stock et de gérer la bibliothèque. Le mode **Accès complet sans code** donne aussi accès au lecteur NFC et aux caméras. Voir le [guide réseau](13-acces-reseau.md).

La caméra OV5647 et le lecteur réel ACS ACR1552U-M1 sont intégrés sur le Pi depuis les versions précédentes. La lecture et l’écriture d’une fiche sur un tag SLIX2 ont réussi. En mode réel, Configuration indique **Matériel réel**, la confirmation s’intitule **Écrire et vérifier le tag** et le panneau du simulateur est masqué. Les étapes d’installation complètes sont dans le [guide de la station réelle](12-installation-station-reelle.md).

Le mode simulation reste disponible pour préparer les usages : tags et écritures virtuels, inventaire et favoris persistants, reconnaissance de texte QR ou de codes produit. Dans ce mode, Configuration indique **Simulation**, l’état du lecteur indique **Lecteur simulé** et la validation s’intitule **Simuler l’écriture**. Les données sont séparées de celles du mode matériel.

Le profil matériel qualifié comprend un Raspberry Pi 5 sous Raspberry Pi OS/Trixie arm64, un lecteur ACS ACR1552U-M1, une caméra OV5647 et un affichage HDMI. Le retour automatique en plein écran a été vérifié après redémarrage. Le tactile, les autres profils de caméra et la lecture QR à courte distance restent à qualifier. Les tests logiciels couvrent Mac/Python 3.12 et Pi/Python 3.13.

## Installer et démarrer depuis les sources

Pour installer une version publiée sur le Raspberry Pi, suivre le [guide de la station réelle](12-installation-station-reelle.md), avec téléchargement des sources publiques, création de l’environnement sur le Pi, stockage séparé des données et accès réseau. Le [guide historique](09-deploiement-raspberry-pi.md) conserve les étapes de la première livraison en simulation.

Conserver l’arborescence complète du projet, notamment `references/`, `resources/` et `openprinttag_app/`. Les spécifications et le catalogue sont lus en dehors du paquet Python : une wheel seule ne constitue pas encore une distribution autonome.

Prérequis : Python 3.11 ou plus récent, avec création d’environnements virtuels et pip disponibles. Depuis le répertoire du projet sur le Mac ou sa copie complète sur le Pi :

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m openprinttag_app --mode simulation
```

Le téléchargement des dépendances nécessite une connexion lors de l’installation. Le fonctionnement décrit ici utilise ensuite les données locales. Le verrou `requirements.lock` a été vérifié sur Mac/Python 3.12 et Raspberry Pi OS/Trixie arm64/Python 3.13. Pour le lecteur réel et la caméra sur le Pi, utiliser l’environnement `--system-site-packages` et les paquets système du guide de la station réelle.

Ouvrir **http://127.0.0.1:8765** dans le navigateur de la station. Garder le terminal ouvert ; `Ctrl+C` arrête le serveur. Le port peut être changé avec `--port`. Le mode par défaut est `simulation`, sauf si la variable `OPENPRINTTAG_MODE` a été définie : l’option explicite ci-dessus évite cette ambiguïté.

L’option `--mode hardware` active le lecteur PC/SC réel. Poser un tag, cliquer sur **Lire le tag**, puis créer ou modifier sa fiche avec les mêmes parcours; valider avec **Écrire et vérifier le tag**. Les commandes du simulateur restent réservées au mode `simulation`. Chaque mode conserve sa propre base et le changement de mode ne copie pas les bobines fictives dans le stock réel.

## Prendre en main les onglets

### Lecture : consulter une bobine et gérer sa présence en stock

1. En mode matériel, poser une bobine ou son tag sur le lecteur. Dans le simulateur, choisir une bobine et cliquer sur **Présenter le tag**.
2. Cliquer sur **Lire le tag**. La fiche affiche les champs du tag, le restant connu, les protections et l’utilisation mémoire.
3. Choisir **Ajouter à l’inventaire** pour enregistrer cette bobine en stock, ou la retirer si elle y figure déjà.

Les deux bobines initiales sont des démonstrations fictives, sans validation fabricant. Un tag vierge doit recevoir des données avant son ajout à l’inventaire.

L’ajout et le retrait concernent uniquement le stock local. Retirer une bobine conserve sa fiche et les données de son tag. Une nouvelle lecture d’une bobine connue actualise ses valeurs et sa date de lecture sans réactiver automatiquement une bobine retirée : son retour en stock demande un ajout explicite.

### Écriture : créer ou modifier les données d’un tag

Pour créer :

1. En mode matériel, poser un tag vierge sur le lecteur; dans le simulateur, cliquer sur **Créer un tag vierge**. Cliquer ensuite sur **Lire le tag**.
2. Dans **Écriture**, garder **Nouveau tag**. Saisir les valeurs connues, appliquer un favori ou reconnaître un code produit. La classe de matériau est obligatoire ; les champs facultatifs peuvent rester vides.
3. Cliquer sur **Vérifier les modifications**, lire le tableau avant/après, puis sur **Écrire et vérifier le tag** en mode matériel, ou **Simuler l’écriture** en simulation.
4. Attendre la confirmation de la relecture. L’écriture d’un nouveau tag ne l’ajoute pas automatiquement au stock : utiliser ensuite **Lecture → Ajouter à l’inventaire**.

Pour modifier, lire d’abord la bobine, puis choisir **Modifier ce tag** ou **Modifier un tag existant**. Modifier par exemple une couleur, une masse initiale connue ou la masse consommée. Le restant est calculé ; ce n’est pas un champ indépendant à écrire. Vider un champ facultatif existant demande sa suppression explicite. Les champs non modifiés sont conservés ; l’identité de la bobine reste inchangée.

Les sections avancées montrent les autres champs du schéma OpenPrintTag. Respecter les unités affichées, notamment grammes pour les masses. Les couleurs utilisent la forme `#RRGGBB` ou `#RRGGBBAA`. Une information inconnue doit rester non renseignée, sans valeur estimée présentée comme certaine.

Les régions **Main** et **Aux** ont leurs propres protections et capacités. Les champs d’une région protégée restent en lecture seule ; l’application ne fournit pas de déverrouillage matériel. La bobine PETG de démonstration permet d’observer Main protégé. Une fiche trop volumineuse est refusée avant l’écriture.

La préparation reste valable cinq minutes et pour le même tag dans le même état. Modifier la fiche impose une nouvelle préparation. Si le tag change, relire avant de préparer à nouveau ; une préparation expirée ou perdue au redémarrage doit également être refaite. Une validation n’est utilisable qu’une fois.

### Inventaire : consulter le dernier état connu et préparer des favoris

L’onglet affiche les bobines **en stock**, leur dernière lecture et les quantités connues. La recherche filtre les fiches ; le détail d’une ligne montre leurs valeurs. Les fiches retirées sont conservées dans la base, mais ne sont pas affichées par défaut dans cette interface.

Les favoris sont des modèles réutilisables, créés ou modifiés dans **Vos favoris et modèles**. On peut les sélectionner ensuite dans **Écriture**. Ils contiennent des caractéristiques communes ; ils ne recopient ni identité individuelle, ni consommation, ni masse réelle propre à une bobine. Modifier un favori ne modifie aucun tag déjà écrit.

### Configuration : matériel, apparence et accès distant

Consulter le lecteur et le capteur détectés, choisir un thème clair ou sombre, la langue et le niveau d’accès distant. Configuration reste accessible depuis le réseau pour régler le partage. Le mode **Accès complet sans code** autorise les fonctions du lecteur et de la caméra. Voir le [guide détaillé](15-configuration-et-apparence.md).

## Après une utilisation par l’imprimante

L’imprimante équipée d’un système compatible actualise le tag pendant l’usage de la bobine. Le suivi PrusaLink affiche l’état de l’imprimante sans synchroniser sa consommation avec l’inventaire : il faut **relire le tag** pour actualiser cette quantité. La quantité affichée depuis une autre machine reste donc celle de la dernière lecture sur la station.

Aujourd’hui, le bouton **Simuler l’imprimante** ajoute une consommation au tag simulé. Pour voir cette consommation dans le stock, cliquer ensuite sur **Lire le tag**, puis consulter l’inventaire. Une masse consommée inconnue n’est pas assimilée à zéro. Si le calcul utilise la masse nominale faute de masse réelle initiale, le restant est signalé comme estimé.

## Importer un QR ou un code produit

Dans **Écriture**, placer le curseur dans **Contenu du QR ou code produit**, puis coller le texte ou utiliser un scanner qui se comporte comme un clavier. Cliquer sur **Reconnaître le code** et vérifier les valeurs proposées avant de les appliquer.

Un GTIN valide peut retrouver une fiche dans la copie locale de la base officielle. En cas de plusieurs correspondances, choisir la bonne fiche ; sans correspondance, seul le GTIN connu est proposé. Depuis `0.11.1.dev0`, une URL de bobine Prusament reconnue récupère les données de la fiche officielle pour vérification; les autres URL restent du texte brut et ne sont pas ouvertes. Un format inconnu nécessite une saisie manuelle. Le texte brut appliqué est conservé comme provenance locale, pas comme champ arbitraire du tag.

### Scanner avec la caméra du Pi

Depuis le navigateur local du Pi, aller dans **Écriture → Nouveau tag → Scanner avec la caméra**. L’application doit être lancée avec `--camera` et les dépendances caméra installées; voir le [guide Pi](09-deploiement-raspberry-pi.md#9-version-de-travail-avec-capture-caméra). L’accès par tunnel SSH depuis le Mac donne le même contrôle local.

1. Présenter le QR face à la caméra. L’aperçu se met à jour pendant l’essai.
2. Avec l’OV5647, ajuster la distance et immobiliser le code sous une bonne lumière : cette caméra n’a pas d’autofocus. Une lecture à 20 cm n’est pas validée.
3. Après détection, vérifier le texte, puis choisir **Utiliser ce code**. Si plusieurs QR sont visibles, choisir celui de la bobine concernée.
4. La reconnaissance préremplit les données disponibles. Pour un QR Prusament, le Pi consulte la fiche officielle via Internet; vérifier les valeurs et compléter les informations absentes avant enregistrement ou écriture.

**Arrêter le scan**, fermer la fenêtre ou quitter le parcours interrompt la capture. Le scan s’arrête aussi après lecture ou à l’expiration de l’essai (45 secondes de recherche, plus ouverture de la caméra). En cas de blocage matériel, le processus est arrêté dans un délai borné. Un seul scan fonctionne à la fois. Les images et les textes non confirmés sont temporaires : effacés au prochain scan, au plus tard trois minutes après sa fin, ou à l’arrêt de l’application. Le texte choisi n’est enregistré comme provenance d’une bobine qu’au moment de l’écriture vérifiée.

Un code inconnu ou une URL non prise en charge reste utilisable comme texte brut, sans ouverture de page ni déduction de propriétés. La saisie et le collage restent disponibles lorsque la caméra est désactivée ou indisponible. Les formats QR propriétaires sans mapping documenté demandent une saisie manuelle.

## Accéder à la station sur le réseau local

Les navigateurs du réseau utilisent l’inventaire partagé de la station. Le mode **Inventaire et modèles** permet la consultation et la gestion de bibliothèque sans accès au lecteur ou à la caméra. **Accès complet sans code** autorise aussi les fonctions matérielles; ce choix est commun au réseau et persistant. Voir le [guide réseau](13-acces-reseau.md).

Pour un lancement manuel, arrêter préalablement le service qui occupe le port, puis utiliser :

```sh
.venv/bin/python -m openprinttag_app --mode hardware --camera --lan --data-dir "$HOME/openprinttag-data"
```

Ouvrir l’adresse annoncée au démarrage depuis une autre machine du même réseau. Pour ajouter un nom d’accès, utiliser `--allowed-host` avec le nom ou l’adresse réelle, sans port; l’option peut être répétée. Sur le Pi, l’adresse locale est **http://127.0.0.1:8765/**. Sans `--lan`, le serveur écoute seulement sur la boucle locale. Le serveur actuel est prévu pour un lancement direct, sans proxy intermédiaire.

## Données persistantes et sauvegarde

Par défaut, les données sont dans `var/`, à la racine du projet :

| Fichier | Usage |
| --- | --- |
| `var/simulation.sqlite3` | Tags simulés, inventaire d’essai, favoris, provenance et journal d’essai. |
| `var/inventory.sqlite3` | Base distincte du mode matériel. |

Les bases ne sont pas fusionnées lors d’un changement de mode. `--data-dir /chemin/vers/donnees` permet de choisir leur répertoire. Une variable `OPENPRINTTAG_DATA_DIR` peut également le définir.

Pour une sauvegarde simple, arrêter le serveur, puis copier le répertoire de données complet. SQLite peut utiliser des fichiers compagnons `-wal` et `-shm` ; conserver l’ensemble évite une copie partielle. Arrêter également l’application avant une restauration. Les sauvegardes manuelles et planifiées, l’aperçu et la restauration sont aussi accessibles dans Configuration; voir le [guide de sauvegarde](26-sauvegardes-et-restauration.md).

## Si une opération est refusée

| Message ou situation | Action |
| --- | --- |
| Tag ou données modifiés, préparation expirée, conflit d’inventaire | Relire la bobine ou actualiser la liste, puis préparer à nouveau. |
| Région protégée | Consulter ses valeurs ; limiter les modifications aux régions autorisées. |
| Valeur invalide ou capacité dépassée | Corriger les champs ou réduire les données facultatives, puis vérifier à nouveau. |
| Écriture incertaine | Relire le tag avant toute nouvelle tentative. Ne pas relancer l’écriture automatiquement. |
| Tag écrit et vérifié, inventaire non confirmé | Relire pour réconcilier l’état local ; ne pas réécrire le tag par réflexe. |
| Lecteur matériel indisponible | Vérifier USB, `pcscd.socket`, les paquets système et la session locale; utiliser le diagnostic du guide d’installation. |
| Accès NFC refusé depuis le LAN | Choisir Accès complet sans code dans Configuration; sans `--lan`, utiliser le navigateur local de la station. |
| Hôte refusé | Vérifier l’adresse utilisée et la valeur de `--allowed-host`, puis relancer le serveur. |

## Documentation complémentaire

Le [guide de la station réelle](12-installation-station-reelle.md) décrit l’installation et la [feuille de route](14-feuille-de-route.md) présente les travaux restants. Les sources et versions publiques sont accessibles sans compte GitHub. Les licences des références tierces restent applicables.

Voir aussi [l’architecture](07-architecture.md), le [cahier des charges](05-cahier-des-charges.md) et les [sources et licences](04-sources-et-provenance.md).

## Créer un modèle depuis une bobine

Depuis **Lecture → Créer un modèle** après lecture d’un tag, ou **Inventaire → Vos favoris et modèles → Depuis un tag ou un QR**, lire la source puis vérifier et nommer la fiche avant de l’enregistrer. Le modèle reprend les caractéristiques réutilisables; l’identité, les mesures individuelles et les données de suivi ne sont pas copiées. Voir le [guide détaillé](28-modeles-depuis-rfid-et-qr.md).
