# Écran et pilotage local

OPT Station peut être utilisée depuis le navigateur d’un ordinateur du réseau ou sur un écran connecté au Raspberry Pi. Le profil d’affichage local utilise un navigateur en plein écran, lancé après l’ouverture de la session graphique.

## Raspberry Pi Touch Display 2 de 10,1 pouces

Le [Touch Display 2](https://www.raspberrypi.com/products/touch-display-2/) de 10,1 pouces est une option pour une station à base de Pi 5. La compatibilité du modèle d’écran et les connexions DSI doivent être vérifiées avec le [guide du fabricant](https://www.raspberrypi.com/documentation/accessories/touch-display-2.html#compatibility) avant le montage. Cette variante n’est pas une cible compatible avec le Pi 4.

Le format portrait natif et l’orientation d’usage demandent une vérification de l’interface sur le matériel final. L’écran HDMI constitue également un moyen de pilotage. La qualification d’un navigateur à la souris ne vaut pas validation complète de la saisie tactile.

## Mise en service

- Vérifier l’alimentation, la nappe, le port et la compatibilité avec le modèle de Pi.
- Installer un système disposant d’une session graphique prise en charge.
- Vérifier la résolution, l’orientation, la lisibilité et la saisie des formulaires.
- Installer le service d’affichage suivant le [guide de station réelle](12-installation-station-reelle.md).

L’ouverture automatique du bureau dépend de la configuration du système. Le service d’affichage attend une réponse de l’application avant de lancer Firefox en mode kiosque. Les commandes du guide n’activent pas implicitement une connexion automatique du système.

## Vérification tactile

Avant de qualifier un montage tactile, tester les boutons, le défilement, la fermeture des fenêtres, les champs numériques, les menus et le clavier à l’écran. La connexion des périphériques NFC et caméra reste indépendante de l’affichage.

## Activer le mode tactile depuis Paramètres

Depuis **v0.27.0-rc.5**, dans **Paramètres → Matériel détecté → Mode tactile du Pi**, cocher **Activer le mode tactile du Pi**, puis **Enregistrer le mode tactile**. Le réglage permet de faire défiler les listes en glissant un doigt sur l’écran. Le désactiver remet l’émulation de souris du bureau.

La commande est disponible sur le Pi avec un écran tactile détecté et le bureau labwc standard de Raspberry Pi OS. Elle demande l’accès local ou distant complet. **Actualiser le tactile** relit le matériel et les réglages actuels. Le choix s’applique aux écrans tactiles raccordés, conserve leur sortie vidéo et leur calibration, et recharge le bureau sans redémarrer le Pi.

Le choix reste dans la configuration du bureau après redémarrage. Cette configuration système est distincte des sauvegardes applicatives d’OPT Station ; le fichier précédent est conservé dans `~/.config/labwc/rc.xml.opt-station-backup` après une modification. Une session graphique indisponible ou un profil de bureau personnalisé non pris en charge désactive la commande avec une explication.

Sur le Pi de référence, le défilement de l’inventaire au doigt a été confirmé par un essai utilisateur le 11 novembre 2026 après désactivation de `mouseEmulation`. La [documentation labwc](https://labwc.github.io/labwc-config.5.html) décrit la conversion des événements tactiles en mouvements de souris lorsque cette émulation est active.

## Mise en veille de l’écran

Dans **Paramètres → Matériel détecté → Veille de l’écran**, choisir **Jamais** ou un délai de **1, 2, 5, 10, 15, 30 ou 60 minutes**, puis **Enregistrer la veille**. Le délai correspond à l’absence d’interaction sur le Pi ; utiliser OPT Station depuis un autre ordinateur ne réinitialise pas ce délai.

La veille éteint les sorties écran du Pi. Un toucher, un mouvement de souris ou une touche du clavier les réveille. Le Pi et les services d’OPT Station continuent de fonctionner. **Réveiller l’écran** permet aussi de demander le réveil depuis un navigateur ayant l’accès complet.

Le choix est conservé dans `screen-settings.json`, inclus dans les sauvegardes de configuration. OPT Station reprend ce délai au démarrage et après une restauration. Le réglage reste désactivé par défaut jusqu’au premier enregistrement. Il est disponible avec le bureau labwc et les composants `swayidle` et `wlopm`, ajoutés aux dépendances d’affichage de l’installation.

La commande utilise l’inactivité native du bureau, avec une configuration dédiée aux commandes d’écran. Voir les documentations [swayidle](https://github.com/swaywm/swayidle/blob/master/swayidle.1.scd) et [labwc](https://labwc.github.io/labwc-config.5.html). Le réveil tactile doit être vérifié avec le montage utilisé.

**Essais validés sur le Pi le 11 novembre 2026 :** activation et désactivation du mode tactile depuis Paramètres, défilement de l’inventaire au doigt, extinction automatique de l’écran et réveil par le bouton d’OPT Station. Le réveil au toucher a été confirmé par un essai utilisateur. Le délai final enregistré est de **5 minutes**.
