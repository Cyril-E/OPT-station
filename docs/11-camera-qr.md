# Caméras et lecture des QR

OPT Station utilise une caméra du Raspberry Pi pour décoder les étiquettes QR. Les caméras réseau de l’imprimante sont une fonction distincte, décrite dans le [guide imprimante](17-suivi-imprimante-et-cameras.md).

## Profil OV5647

Le Camera Module 1 utilise un capteur **OmniVision OV5647**, de résolution nominale 2592 × 1944, avec mise au point fixe. Ce profil a servi à la qualification de la capture et du décodage QR dans l’application. Il ne dispose pas d’un autofocus motorisé.

La netteté dépend du réglage de l’objectif, de la distance, de la taille du QR, de l’éclairage et des mouvements. La résolution nominale ne garantit pas une lecture rapprochée. Une distance de lecture particulière doit être qualifiée sur le montage utilisé.

## Camera Module 3

Le [Camera Module 3](https://www.raspberrypi.com/products/camera-module-3/) utilise un capteur Sony IMX708 et un autofocus. Le fabricant décrit les variantes standard/Wide et standard/NoIR dans ses [spécifications matérielles](https://www.raspberrypi.com/documentation/accessories/camera.html#hardware-specifications).

La prise en charge effective doit être vérifiée sur le système installé : détection `imx708`, captures stables, fonctionnement de l’autofocus et lecture des étiquettes à la distance retenue. Un autofocus ou une plage de mise au point annoncée ne suffit pas à garantir le décodage d’un QR.

## Raccordement et diagnostic

Pour le Pi 5, vérifier le type de nappe Standard–Mini et suivre le [guide officiel de connexion](https://www.raspberrypi.com/documentation/accessories/camera.html#install-a-raspberry-pi-camera), alimentation débranchée.

Sur un système disposant des outils Raspberry Pi :

```sh
rpicam-hello --list-cameras
rpicam-still --nopreview --timeout 3000 -o /tmp/opt-station-camera-test.jpg
```

L’image de diagnostic est locale; ne pas la joindre à un dépôt ou rapport si elle contient des informations privées. En l’absence de capture, vérifier capteur, nappe, port, système et versions logicielles avant de modifier les réglages. La documentation de référence est le [guide logiciel caméra Raspberry Pi](https://www.raspberrypi.com/documentation/computers/camera_software.html).

## Parcours dans l’application

Dans **Écriture → Nouveau tag → Scanner avec la caméra**, l’aperçu aide au placement. L’utilisateur choisit explicitement le texte lu avec **Utiliser ce code**. L’arrêt ferme la capture; les images temporaires ne sont pas ajoutées automatiquement à l’inventaire. Les parcours de réception de stock et de création de modèle réutilisent le même mécanisme.

La saisie ou le collage du code reste disponible si la capture n’est pas utilisable. Un résultat lu est analysé avant de préparer une fiche ou une écriture; il n’exécute pas d’instructions et ne déclenche pas une écriture NFC à lui seul.
