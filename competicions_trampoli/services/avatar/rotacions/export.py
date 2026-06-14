from .overview import EXPLAINING_AVATARS


AVATAR_MESSAGES = {
    "rotations_export": {
        "id": "rotations_export",
        "title": "Export",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Export et permet descarregar el programa en Excel, en format participants o en format grups.",
                "panel": "export",
                "highlight": "[data-avatar-anchor='rotations-panel-export']",
                "scroll": False,
            },
            {
                "text": "Les dades d'export defineixen titol, seu, data i logo que apareixeran al fitxer.",
                "panel": "export",
                "highlight": "[data-avatar-anchor='rotations-export-meta']",
                "scroll": False,
            },
        ],
        "actions": [],
    },
    "rotations_export_fields": {
        "id": "rotations_export_fields",
        "title": "Camps d'export",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Els camps de participants decideixen quina informacio extra es mostra dins les cel.les de l'Excel.",
                "panel": "export",
                "highlight": "[data-avatar-anchor='rotations-export-fields']",
                "scroll": False,
            },
            {
                "text": "Pots ordenar aquests camps per adaptar l'Excel a la lectura que necessitis.",
                "panel": "export",
                "highlight": "[data-avatar-anchor='rotations-export-fields']",
                "scroll": False,
            },
        ],
        "actions": [],
    },
}
