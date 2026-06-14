EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


AVATAR_MESSAGES = {
    "classifications_presentation": {
        "id": "classifications_presentation",
        "title": "Presentació",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "A Presentació configures com es visualitzarà aquesta classificació de cara al públic.",
                "highlight": "[data-avatar-anchor='classifications-presentation-section']",
            },
            {
                "text": "Aquesta secció t’ajuda a convertir el resultat calculat per IA Score en una classificació clara, llegible i ben presentada per al públic.",
                "highlight": "[data-avatar-anchor='classifications-presentation-section']",
            },
        ],
        "actions": [],
    },
    "classifications_presentation_top": {
        "id": "classifications_presentation_top",
        "title": "Top N",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Primer pots definir el Top N d’inscripcions que vols mostrar.",
                "highlight": "[data-avatar-anchor='classifications-presentation-rules']",
            },
            {
                "text": "Si vols mostrar totes les inscripcions de la classificació, deixa aquest valor a 0.",
                "highlight": "[data-avatar-anchor='classifications-presentation-rules']",
            },
        ],
        "actions": [],
    },
    "classifications_presentation_ties": {
        "id": "classifications_presentation_ties",
        "title": "Mostrar empats",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Si actives Mostrar empats, el tall del Top N no deixarà fora unitats competitives empatades en aquella posició.",
                "highlight": "[data-avatar-anchor='classifications-presentation-rules']",
            },
            {
                "text": "Per exemple, si mostres un Top 3 i hi ha un empat a la tercera posició, IA Score pot mostrar totes les unitats empatades en aquell lloc.",
                "highlight": "[data-avatar-anchor='classifications-presentation-rules']",
            },
        ],
        "actions": [],
    },
    "classifications_presentation_main_table": {
        "id": "classifications_presentation_main_table",
        "title": "Taula principal",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Després trobaràs la configuració de la Taula principal.",
                "highlight": "[data-avatar-anchor='classifications-presentation-main-table']",
            },
            {
                "text": "La Taula principal defineix la informació que es mostrarà sempre per cada inscripció o unitat competitiva dins de la classificació.",
                "highlight": "[data-avatar-anchor='classifications-presentation-main-table']",
            },
            {
                "text": "Normalment aquí hi posaràs dades com la posició, el nom i els punts obtinguts.",
                "highlight": "[data-avatar-anchor='classifications-presentation-main-table']",
            },
            {
                "text": "Els punts provenen del càlcul que has configurat prèviament a la secció de Puntuació.",
                "highlight": "[data-avatar-anchor='classifications-presentation-main-table']",
            },
        ],
        "actions": [],
    },
    "classifications_presentation_columns": {
        "id": "classifications_presentation_columns",
        "title": "Columnes",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "També pots afegir valors de les columnes importades de l’Excel o valors dels camps puntuats pels jutges.",
                "highlight": "[data-avatar-anchor='classifications-presentation-main-table']",
            },
            {
                "text": "Això et permet decidir quina informació ha de ser visible d’entrada en el llistat públic.",
                "highlight": "[data-avatar-anchor='classifications-presentation-main-table']",
            },
        ],
        "actions": [],
    },
    "classifications_presentation_detail": {
        "id": "classifications_presentation_detail",
        "title": "Detall desplegable",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "A continuació pots configurar el Detall.",
                "highlight": "[data-avatar-anchor='classifications-presentation-detail']",
            },
            {
                "text": "El Detall és la informació que apareix dins d’un desplegable quan l’usuari prem sobre una inscripció o unitat competitiva.",
                "highlight": "[data-avatar-anchor='classifications-presentation-detail']",
            },
            {
                "text": "Funciona com una extensió de la Taula principal: no es mostra sempre, però permet consultar més informació quan cal.",
                "highlight": "[data-avatar-anchor='classifications-presentation-detail']",
            },
            {
                "text": "Segons el tipus de classificació, pots configurar diferents tipologies de taules de detall.",
                "highlight": "[data-avatar-anchor='classifications-presentation-detail']",
            },
        ],
        "actions": [],
    },
    "classifications_presentation_detail_sections": {
        "id": "classifications_presentation_detail_sections",
        "title": "Seccions del detall",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Pots crear tantes taules de detall com necessitis per mostrar la informació complementària de manera ordenada.",
                "highlight": "[data-avatar-anchor='classifications-presentation-detail']",
            },
            {
                "text": "Si vols, el detall també pot aparèixer obert d’entrada, sense que l’usuari l’hagi de desplegar manualment.",
                "highlight": "[data-avatar-anchor='classifications-presentation-detail']",
            },
            {
                "text": "Amb el selector Disposició de seccions pots controlar com es mostren les taules de detall.",
                "highlight": "[data-avatar-anchor='classifications-presentation-detail']",
            },
            {
                "text": "En mode Pestanyes, les seccions es mostren com cards o pestanyes que l’usuari pot seleccionar.",
                "highlight": "[data-avatar-anchor='classifications-presentation-detail']",
            },
            {
                "text": "En mode Vertical, les taules de detall es mostren una darrere l’altra en disposició vertical.",
                "highlight": "[data-avatar-anchor='classifications-presentation-detail']",
            },
        ],
        "actions": [],
    },
    "classifications_presentation_styles": {
        "id": "classifications_presentation_styles",
        "title": "Estil visual",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Finalment, pots personalitzar l’aspecte visual de la classificació.",
                "highlight": "[data-avatar-anchor='classifications-presentation-styles']",
            },
            {
                "text": "Pots assignar colors personalitzats a les diferents particions de la classificació per fer-les més fàcils d’identificar.",
                "highlight": "[data-avatar-anchor='classifications-presentation-styles']",
            },
            {
                "text": "També pots destacar certes posicions amb colors de fons, com ara or, plata i bronze per als tres primers llocs.",
                "highlight": "[data-avatar-anchor='classifications-presentation-styles']",
            },
        ],
        "actions": [],
    },
    "classifications_presentation_preview": {
        "id": "classifications_presentation_preview",
        "title": "Previsualització",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Recorda guardar els canvis perquè la configuració de presentació quedi aplicada.",
                "highlight": "[data-avatar-anchor='classifications-presentation-preview']",
            },
        ],
        "actions": [],
    },
}
