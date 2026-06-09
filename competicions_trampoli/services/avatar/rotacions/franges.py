from .overview import EXPLAINING_AVATARS


AVATAR_MESSAGES = {
    "rotations_time_slots": {
        "id": "rotations_time_slots",
        "title": "Franges",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Les franges estructuren el temps del programa. Cada franja acaba sent una fila de la graella.",
                "panel": "franges",
                "highlight": "[data-avatar-anchor='rotations-panel-franges']",
                "scroll": False,
            },
            {
                "text": "La creacio manual et permet afegir una franja amb tipus, horari, titol i color.",
                "panel": "franges",
                "highlight": "[data-avatar-anchor='rotations-manual-slot']",
                "scroll": False,
            },
        ],
        "actions": [],
    },
    "rotations_auto_slots": {
        "id": "rotations_auto_slots",
        "title": "Franges automatiques",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "La generacio automatica crea una sequencia de franges entre una hora inicial i una hora final.",
                "panel": "franges",
                "highlight": "[data-avatar-anchor='rotations-auto-slots']",
                "scroll": False,
            },
            {
                "text": "Si marques esborrar franges existents, el planner substituira l'estructura actual abans de generar la nova.",
                "panel": "franges",
                "highlight": "[data-avatar-anchor='rotations-auto-slots']",
                "scroll": False,
            },
        ],
        "actions": [],
    },
    "rotations_slot_selection": {
        "id": "rotations_slot_selection",
        "title": "Seleccio de franges",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Quan selecciones franges a la graella, aquest panell activa accions massives sobre el conjunt.",
                "panel": "franges",
                "highlight": "[data-avatar-anchor='rotations-slot-selection']",
                "scroll": False,
            },
            {
                "text": "Aquestes accions poden buidar, duplicar, desplacar, canviar durada, color, tipus o eliminar franges seleccionades.",
                "panel": "franges",
                "highlight": "[data-avatar-anchor='rotations-slot-selection']",
                "scroll": False,
            },
        ],
        "actions": [],
    },
}
