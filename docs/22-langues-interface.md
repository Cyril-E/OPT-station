# Langues de l’interface

Ouvrir **Paramètres → Apparence → Langue de l’interface** et choisir **Français**, **English**, **Español** ou **Deutsch**. L’espagnol et l’allemand sont disponibles depuis **v0.22.0**.

| Langue | Chemin dans l’interface | Format des nombres et dates |
| --- | --- | --- |
| Français | Paramètres → Apparence → Langue de l’interface | `fr-FR` |
| English | Settings → Appearance → Interface language | `en-GB` |
| Español | Ajustes → Apariencia → Idioma de la interfaz | `es-ES` |
| Deutsch | Einstellungen → Darstellung → Oberflächensprache | `de-DE` |

Le français reste la langue par défaut. Le choix est conservé pour le navigateur utilisé, indépendamment du thème et des droits d’accès. Le Pi et le Mac peuvent donc utiliser des langues différentes. Plusieurs onglets du même navigateur sur la même adresse suivent le choix mémorisé. Si le navigateur refuse le stockage local, un message indique que le choix ne vaut que pour la page ouverte.

Le changement s’applique immédiatement aux onglets, boutons, libellés, messages, confirmations, fenêtres de scan et réglages. Il ne recharge pas la page et ne reconstruit pas les formulaires : les champs non enregistrés restent présents. Les nombres et dates utilisent le format de la langue choisie, selon les formats indiqués ci-dessus. Les unités restent celles de la station : grammes, millimètres et degrés Celsius.

Les noms de bobines, marques, modèles, emplacements, identifiants, fichiers et données saisis ne sont pas traduits. Le contenu du QR et les valeurs RFID restent identiques. Les clés canoniques Main/Aux et les valeurs des énumérations officielles ne dépendent pas de la langue. Le nom d’un modèle « Inconnu », par exemple, reste « Inconnu » en anglais, alors que l’indicateur d’une valeur absente s’affiche « Unknown ».

Le choix est enregistré sous `opt-station-language` dans le stockage local du navigateur. Aucun réglage serveur ou fichier privé supplémentaire n’est créé. Le service et la session graphique du Pi conservent leurs réglages existants.

## Maintenance et vérifications

Les traductions sont dans **`openprinttag_app/static/translations.js`** (anglais), **`translations-es.js`** (espagnol) et **`translations-de.js`** (allemand), avec les mêmes messages français comme clés. Les trois dictionnaires sont chargés avant le moteur de langue, sur la page principale et la page d’aide HTTPS. Aucune traduction en ligne ni dépendance supplémentaire n’est nécessaire. Les messages à paramètres utilisent `{0}`, `{1}`, etc.; ces paramètres doivent être conservés dans la traduction. Les libellés statiques sont marqués dans le HTML, et les messages dynamiques utilisent `OPT_I18N.msg`. Les noms et valeurs utilisateur passent par le rendu brut, sans recherche ni remplacement automatique dans le contenu.

Les tests vérifient la couverture des messages, les paramètres, les libellés d’accessibilité, les valeurs canoniques et la conservation des données. Le test du moteur de langue s’exécute sur le Mac avec :

```sh
node tests/interface_i18n.cjs
```

Il contrôle les quatre langues, le choix mémorisé, les changements entre onglets, le stockage indisponible, les messages du backend, les pluriels allemands et la conservation des valeurs de formulaire. Dans le navigateur, le passage français/anglais a également été vérifié avec des réglages non enregistrés et un modèle créé par MCP contenant des noms français.

Les libellés dynamiques ne remplacent que leur propre nœud de texte lors d’une bascule de langue; les champs, unités et marqueurs qu’ils contiennent sont conservés. Ce cas est couvert par un test de régression du moteur et par un parcours navigateur français → anglais avec des formulaires de caméra renseignés, en vérifiant la conservation de leurs champs et valeurs.

L’assistant IA reçoit aussi la langue choisie (`fr`, `en`, `es`, `de`) pour ses explications et propositions. Les clés et valeurs canoniques du format RFID ne changent pas. Les notes de version GitHub restent affichées dans leur langue de publication.
