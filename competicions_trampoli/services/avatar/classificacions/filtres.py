EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


AVATAR_MESSAGES = {
    "classifications_filters": {
        "id": "classifications_filters",
        "title": "Filtres",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "A Filtres pots limitar quines inscripcions entren dins d’aquesta classificació.",
                "highlight": "[data-avatar-anchor='classifications-filters-section']",
            },
            {
                "text": "D’entrada, IA Score pren totes les inscripcions disponibles de la competició.",
                "highlight": "[data-avatar-anchor='classifications-filters-simple']",
            },
            {
                "text": "Amb aquesta secció pots aplicar criteris per quedar-te només amb les inscripcions que t’interessin.",
                "highlight": "[data-avatar-anchor='classifications-filters-simple']",
            },
        ],
        "actions": [],
    },
    "classifications_filters_fields": {
        "id": "classifications_filters_fields",
        "title": "Camps i valors",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Els filtres es basen en diferents camps de la inscripció, com poden ser categoria, entitat, grup, subcategoria o altres dades disponibles.",
                "highlight": "[data-avatar-anchor='classifications-filters-fields']",
            },
            {
                "text": "Per cada criteri pots seleccionar els valors que vols incloure a la classificació.",
                "highlight": "[data-avatar-anchor='classifications-filters-fields']",
            },
            {
                "text": "Per exemple, pots fer que una classificació només tingui en compte una categoria concreta, una entitat determinada o un conjunt específic d’inscripcions.",
                "highlight": "[data-avatar-anchor='classifications-filters-fields']",
            },
        ],
        "actions": [],
    },
    "classifications_filters_partitions": {
        "id": "classifications_filters_partitions",
        "title": "Filtres i particions",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Les particions que hagis configurat s’aplicaran sempre sobre aquest conjunt ja filtrat.",
                "highlight": "[data-avatar-anchor='classifications-filters-simple']",
            },
            {
                "text": "Això vol dir que IA Score primer filtra les inscripcions, i després crea els blocs de classificació segons les particions definides.",
                "highlight": "[data-avatar-anchor='classifications-filters-section']",
            },
            {
                "text": "Els filtres t’ajuden a reutilitzar una mateixa lògica de classificació, però aplicada només al subconjunt de participants que necessites.",
                "highlight": "[data-avatar-anchor='classifications-filters-section']",
            },
        ],
        "actions": [],
    },
    "classifications_filters_advanced": {
        "id": "classifications_filters_advanced",
        "title": "Filtres avançats",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Recorda guardar els canvis perquè els filtres quedin aplicats a la classificació.",
                "highlight": "[data-avatar-anchor='classifications-filters-advanced']",
            },
        ],
        "actions": [],
    },
}
