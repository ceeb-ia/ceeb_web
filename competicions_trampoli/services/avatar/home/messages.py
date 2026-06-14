
EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


AVATAR_MESSAGES = {
    "welcome": {
        "id": "welcome",
        "title": "Benvingut!",
        "avatar": "avatar/greeting_2.png",
        "avatars": [
            "avatar/greeting_2.png",
            *EXPLAINING_AVATARS,
        ],
        "variant": "welcome",
        "steps": [
            {
                "text": "Hola! Soc en Guillem, el teu assistent d’IA Score."
            },
            {
                "text": "Estic aquí per ajudar-te a gestionar les teves competicions de manera fàcil, ràpida i ordenada."
            },
            {
                "text": "Des d’aquesta pantalla tens accés a les configuracions globals d’IA Score."
            },
            {
                "text": "Pots crear una competició nova o entrar en una competició ja existent per continuar treballant."
            },
        ],
        "actions": [
            {
                "label": "Crear competició nova",
                "action": "create_competition",
            },
            {
                "label": "Veure competicions",
                "action": "open_competition",
            },
        ],
    },
    "home_accesses": {
        "id": "home_accesses",
        "title": "Accessos del home",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Des d’aquesta pantalla tens accés a les configuracions globals d’IA Score."
            },
        ],
        "actions": [],
    },
    "create_competition": {
        "id": "create_competition",
        "title": "Nova competició",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "action",
        "steps": [
            {
                "text": "Des d’aquí pots crear una competició nova i començar-ne la configuració inicial."
            },
            {
                "text": "Després de crear-la, podràs entrar-hi per preparar inscripcions, fases, rotacions, classificacions i notes."
            },
            {
                "text": "Si encara no tens clar tot el muntatge, pots crear-la igualment i anar completant els apartats pas a pas."
            },
        ],
        "actions": [
            {
                "label": "Crear competició",
                "action": "create_competition",
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
                "text": "Aquests controls t’ajuden a trobar ràpidament una competició quan la llista comença a créixer."
            },
            {
                "text": "Pots buscar pel nom, filtrar per estat i ordenar la llista per data, creació o nom."
            },
            {
                "text": "Els filtres només afecten el que veus en aquesta pantalla; no modifiquen cap competició."
            },
        ],
        "actions": [],
    },
    "competition_cards": {
        "id": "competition_cards",
        "title": "Targetes de competició",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Cada targeta representa una competició i mostra el seu estat, la data i el nombre de participants."
            },
            {
                "text": "Els botons de cada targeta et porten als mòduls principals: inscripcions, fases, rotacions, classificacions i notes."
            },
            {
                "text": "Si algun botó apareix desactivat, normalment vol dir que no tens permís per aquell apartat o que encara no està disponible per a aquella competició."
            },
        ],
        "actions": [
            {
                "label": "Veure competicions",
                "action": "open_competition",
            },
        ],
    },
}
