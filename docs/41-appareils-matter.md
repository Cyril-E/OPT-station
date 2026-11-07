# Commander les appareils Matter de l’atelier

OPT Station utilise un contrôleur Matter installé sur le Raspberry Pi. Dans l’onglet **Imprimante**, les prises, les relais et les éclairages sélectionnés affichent leur état. Le Pi relit l’appareil après une commande pour confirmer le nouvel état.

## Préparer le Pi

Depuis **v0.27.0-rc.3**, la commande GitHub installe BlueZ, une version vérifiée de Node.js et Matter Server avec ses dépendances verrouillées, puis démarre le service dans le compte d’OPT Station. Pour ajouter le serveur à une station installée, relancer la commande GitHub avec le même compte. Un contrôleur déjà configuré et ses appairages sont conservés. [Installation en une commande](33-installation-une-commande.md)

Le serveur répond par une socket Unix privée, dans le dossier d’exécution du compte. OPT Station la trouve automatiquement. Le Pi et les appareils doivent pouvoir communiquer en IPv6 et se découvrir sur le réseau local. Les appareils Thread ont besoin d’un routeur de bordure Thread joignable depuis le Pi. [Prérequis réseau du contrôleur](https://github.com/matter-js/matterjs-server/blob/v1.5.5/docs/os_requirements.md)

L’installateur configure le Bluetooth du contrôleur quand un adaptateur est détecté. Pour régler un adaptateur ajouté ultérieurement, exécuter `systemctl --user edit opt-station-matter.service`, ajouter le bloc suivant puis redémarrer le service. Utiliser `0` pour `hci0` et adapter le numéro selon le Pi.

```ini
[Service]
Environment=BLUETOOTH_ADAPTER=0
```

## Associer et choisir les commandes

1. Ouvrir **Paramètres → Appareils Matter** sur le Pi ou en HTTPS avec l’accès distant complet. Cliquer sur **Rechercher les appareils associés**.
2. Ouvrir **Associer un appareil Matter** et saisir le code numérique ou le texte du QR Matter. Pour un appareil déjà appairé ailleurs, utiliser le nouveau code de partage fourni par son application et garder **Appareil déjà sur le réseau** coché.
3. Pour un appareil Wi-Fi neuf, décocher **Appareil déjà sur le réseau** et renseigner le Wi-Fi si nécessaire. Le contrôleur conserve le Wi-Fi fourni pour l’association. Pour une première association Thread, le contrôleur doit avoir reçu le jeu de paramètres du réseau Thread. [Association et paramètres réseau du contrôleur](https://github.com/matter-js/matterjs-server/blob/v1.5.5/docs/websockets_api.md#credentials)
4. Cocher chaque canal à afficher et lui donner un nom, par exemple **Éclairage atelier** ou **Sèche-filament**. Choisir **Prise de l’imprimante · arrêt protégé** pour la seule prise qui alimente l’imprimante suivie par PrusaLink.
5. Cocher **Activer les commandes Matter** et enregistrer. Les commandes sont dans **Imprimante → Appareils Matter**.

L’interrupteur physique et le comportement au retour du secteur déterminent si l’imprimante démarre. Pour l’éteindre, cliquer sur **Éteindre**, puis confirmer. Avant de couper la prise, le Pi relit PrusaLink et exige l’état **Au repos** ou **Prête**, sans travail ni transfert. Les consignes de chauffe doivent être à zéro et la buse et le plateau sous 40 °C. Un état absent ou une connexion perdue bloque la coupure. [Recommandations Prusa sur le refroidissement](https://help.prusa3d.com/article/heaters-timeout-31817-core-one-35817-core-one-l-36817-core-one-indx-26817-mk4s-13817-mk4-27817-mk3-9s-21817-mk3-9-28817-mk3-5s-23817-mk3-5-17817-xl-12817-mini_838108?product=core-one)

Les accessoires disposent de l’allumage et de l’arrêt. Si l’état est indisponible ou si le résultat d’une commande est incertain, actualiser l’affichage et vérifier l’appareil.

Les réglages OPT Station sauvegardent les noms et les sélections. Les clés d’association du contrôleur sont dans `~/.local/share/opt-station-matter`, à sauvegarder séparément. Une restauration de configuration désactive les commandes jusqu’à leur réactivation.
