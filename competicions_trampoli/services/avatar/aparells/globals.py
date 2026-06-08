EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


AVATAR_MESSAGES = {
    "welcome": {
        "id": "welcome",
        "title": "Aparells globals",
        "avatar": "avatar/greeting_2.png",
        "avatars": [
            "avatar/greeting_2.png",
            *EXPLAINING_AVATARS,
        ],
        "variant": "welcome",
        "steps": [
            {
                "text": "En aquesta pantalla trobaràs els Aparells globals que ja has creat, i també podràs crear-ne de nous."
            },
            {
                "text": "Aquests aparells viuen de manera global dins d’IA Score. Això et permet configurar-los una sola vegada i reutilitzar-los després en diferents competicions."
            },
            {
                "text": "Quan aculls un aparell dins d’una competició, IA Score en crea una còpia pròpia per a aquella competició."
            },
            {
                "text": "Això vol dir que els canvis que facis sobre l’aparell dins d’una competició no afectaran la configuració de l’aparell global."
            },
        ],
        "actions": [
            {
                "label": "Crear aparell",
                "action": "create_apparatus",
            },
        ],
    },
    "create_apparatus": {
        "id": "create_apparatus",
        "title": "Crear aparell",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "action",
        "steps": [
            {
                "text": "Crear un aparell global serveix per preparar una base reutilitzable abans d’entrar-la en una competició."
            },
            {
                "text": "A IA Score pots treballar amb aparells individuals i aparells d’equip."
            },
            {
                "text": "En un aparell individual competeix una inscripció; en un aparell d’equip competeix un equip i la puntuació pot combinar camps de membres i camps globals."
            },
        ],
        "actions": [
            {
                "label": "Crear aparell",
                "action": "create_apparatus",
            },
        ],
    },
    "filters": {
        "id": "filters",
        "title": "Cerca i filtres",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Els filtres t’ajuden a trobar ràpidament un aparell quan el catàleg creix."
            },
            {
                "text": "Pots buscar per nom o codi, veure només aparells actius o inactius, i separar els que ja tenen puntuació configurada."
            },
            {
                "text": "Aquests filtres només canvien el que veus en aquesta pantalla; no modifiquen cap aparell."
            },
        ],
        "actions": [],
    },
    "apparatus_cards": {
        "id": "apparatus_cards",
        "title": "Targetes d’aparell",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Cada targeta mostra el codi, el nom, la unitat competitiva i l’estat de l’aparell."
            },
            {
                "text": "També veuràs si l’aparell ja s’utilitza en competicions i si té la puntuació configurada."
            },
            {
                "text": "Pots editar la configuració general, definir la puntuació o eliminar l’aparell si encara no està en ús."
            },
        ],
        "actions": [],
    },
    "scoring_schema": {
        "id": "scoring_schema",
        "title": "Puntuació de l’aparell",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "La puntuació defineix quins camps valorarà el jutge i com es calcula el resultat de l’exercici."
            },
            {
                "text": "Si un aparell apareix com a pendent de puntuació, encara pots crear-lo igualment, però hauràs de completar aquesta part abans d’utilitzar-lo plenament."
            },
            {
                "text": "Quan l’aparell es copiï dins d’una competició, aquesta configuració servirà com a punt de partida."
            },
        ],
        "actions": [],
    },
}
