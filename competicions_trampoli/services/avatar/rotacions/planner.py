from .overview import EXPLAINING_AVATARS


AVATAR_MESSAGES = {
    "rotations_grid": {
        "id": "rotations_grid",
        "title": "Programa de rotacions",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "La graella mostra el programa en forma de franges per files i estacions per columnes.",
                "highlight": "[data-avatar-anchor='rotations-grid-table']",
                "scroll": "[data-avatar-anchor='rotations-grid-header']",
            },
            {
                "text": "A cada cel.la pots col.locar una unitat programable per definir qui competeix, on i en quin moment.",
                "highlight": "[data-avatar-anchor='rotations-grid-table']",
                "scroll": "[data-avatar-anchor='rotations-grid-header']",
            },
            {
                "text": "Els canvis de la graella queden pendents fins que deses el programa.",
                "highlight": "[data-avatar-action='rotations-save-program']",
            },
        ],
        "actions": [],
    },
    "rotations_grid_header": {
        "id": "rotations_grid_header",
        "title": "Franges i estacions",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "La primera columna identifica les franges horaries; la resta de columnes son estacions o aparells.",
                "highlight": "[data-avatar-anchor='rotations-grid-header']",
            },
            {
                "text": "Pots reorganitzar estacions arrossegant les capcaleres de columna.",
                "highlight": "[data-avatar-anchor='rotations-station-headers']",
            },
        ],
        "actions": [],
    },
    "rotations_slot_order": {
        "id": "rotations_slot_order",
        "title": "Ordre de franja",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "El mode d'ordre defineix com es presentara el contingut d'aquesta franja als jutges.",
                "highlight": "[data-avatar-anchor='rotations-slot-order']",
            },
            {
                "text": "Si en una cel.la hi ha mes d'una unitat, IA Score les tracta com un conjunt per calcular l'ordre.",
                "highlight": "[data-avatar-anchor='rotations-first-competitive-row']",
            },
        ],
        "actions": [],
    },
    "rotations_slot_actions": {
        "id": "rotations_slot_actions",
        "title": "Accions de franja",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "El menu de franja agrupa accions rapides com editar, inserir, netejar, extrapolar o afegir una nota interna.",
                "highlight": "[data-avatar-anchor='rotations-franja-actions']",
            },
            {
                "text": "Extrapolar copia l'estructura d'una franja cap a les seguents i desplaca les unitats cap a la dreta.",
                "highlight": "[data-avatar-anchor='rotations-franja-actions']",
            },
        ],
        "actions": [],
    },
}
