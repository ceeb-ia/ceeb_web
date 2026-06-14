EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


AVATAR_MESSAGES = {
    "classifications_metadata": {
        "id": "classifications_metadata",
        "title": "Metadades",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "A Metadades configures les característiques generals de la classificació.",
                "highlight": "[data-avatar-anchor='classifications-metadata-section']",
            },
            {
                "text": "Aquí pots definir el nom de la classificació, el seu tipus i el seu estat.",
                "highlight": "[data-avatar-anchor='classifications-metadata-identity']",
            },
        ],
        "actions": [],
    },
    "classifications_metadata_type": {
        "id": "classifications_metadata_type",
        "title": "Tipus de classificació",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "El tipus indica si la classificació és individual o per equips.",
                "highlight": "[data-avatar-anchor='classifications-metadata-type']",
            },
            {
                "text": "Si la classificació és individual, IA Score treballarà directament amb les inscripcions com a unitats classificables.",
                "highlight": "[data-avatar-anchor='classifications-metadata-type']",
            },
            {
                "text": "Si la classificació és per equips, hauràs d’indicar també el context d’equips sobre el qual vols treballar.",
                "highlight": "[data-avatar-anchor='classifications-metadata-team-context']",
            },
        ],
        "actions": [],
    },
    "classifications_metadata_status": {
        "id": "classifications_metadata_status",
        "title": "Estat",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "L’estat permet controlar si la classificació està activa i si serà visible de cara al públic.",
                "highlight": "[data-avatar-anchor='classifications-metadata-status']",
            },
        ],
        "actions": [],
    },
    "classifications_metadata_team_context": {
        "id": "classifications_metadata_team_context",
        "title": "Context d'equips",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Si la classificació és per equips, hauràs d’indicar també el context d’equips sobre el qual vols treballar.",
                "highlight": "[data-avatar-anchor='classifications-metadata-team-context']",
            },
            {
                "text": "Aquest context és el que has definit prèviament a Inscripcions, dins de l’espai d’Equips.",
                "highlight": "[data-avatar-anchor='classifications-metadata-team-context']",
            },
            {
                "text": "El context indica quins equips existeixen en aquest escenari competitiu i quines inscripcions formen part de cada equip.",
                "highlight": "[data-avatar-anchor='classifications-metadata-team-context']",
            },
        ],
        "actions": [],
    },
    "classifications_metadata_team_mode": {
        "id": "classifications_metadata_team_mode",
        "title": "Mode d'equips",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "En una classificació per equips també hauràs d’escollir el mode d’equips: Derivada individual o Nativa d’equip.",
                "highlight": "[data-avatar-anchor='classifications-metadata-team-mode']",
            },
            {
                "text": "En el mode Derivada individual, l’equip obté la seva nota a partir de les contribucions individuals dels seus membres.",
                "highlight": "[data-avatar-anchor='classifications-metadata-team-mode']",
            },
            {
                "text": "Això vol dir que cada membre competeix com a inscripció individual, i després IA Score combina aquestes notes per calcular el resultat de l’equip.",
                "highlight": "[data-avatar-anchor='classifications-metadata-team-mode']",
            },
            {
                "text": "Aquest mode només té sentit amb aparells individuals, perquè les notes provenen dels exercicis individuals dels membres.",
                "highlight": "[data-avatar-anchor='classifications-metadata-team-mode']",
            },
            {
                "text": "En el mode Nativa d’equip, l’equip és la unitat competitiva.",
                "highlight": "[data-avatar-anchor='classifications-metadata-team-mode']",
            },
            {
                "text": "Això vol dir que l’equip ha competit com a equip en un aparell d’equip, fent un exercici conjunt.",
                "highlight": "[data-avatar-anchor='classifications-metadata-team-mode']",
            },
            {
                "text": "En aquest cas, la nota de l’equip pot combinar camps valorats per membre amb camps globals de l’equip.",
                "highlight": "[data-avatar-anchor='classifications-metadata-team-mode']",
            },
            { 
                "text": "Aquest mode només funciona amb aparells d’equip, perquè la nota neix d’una participació conjunta de l’equip.",
                "highlight": "[data-avatar-anchor='classifications-metadata-team-mode']",
            },
            {
                "text": "Per tant, una classificació Derivada individual es construeix a partir d’aparells individuals, mentre que una classificació Nativa d’equip es construeix a partir d’aparells d’equip.",
                "highlight": "[data-avatar-anchor='classifications-metadata-team-mode']",
            },
            {
                "text": "Si un equip no participa en cap aparell d’equip, només podrà obtenir classificacions d’equip derivades de resultats individuals.",
                "highlight": "[data-avatar-anchor='classifications-metadata-team-mode']",
            },
        ],
        "actions": [],
    },
}
