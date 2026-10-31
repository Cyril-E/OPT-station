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
