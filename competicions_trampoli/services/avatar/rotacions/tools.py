from .overview import EXPLAINING_AVATARS


AVATAR_MESSAGES = {
    "rotations_tools": {
        "id": "rotations_tools",
        "title": "Eines",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Eines concentra controls que revisen o ajusten el programa sense ser la graella principal.",
                "panel": "globals",
                "highlight": "[data-avatar-anchor='rotations-panel-tools']",
                "scroll": False,
            },
            {
                "text": "Mostrar grups fora de programa controla si els grups no programats tambe apareixen a notes i jutges.",
                "panel": "globals",
                "highlight": "[data-avatar-anchor='rotations-out-of-program']",
                "scroll": False,
            },
        ],
        "actions": [],
    },
    "rotations_validation": {
        "id": "rotations_validation",
        "title": "Validacio",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "La validacio revisa duplicats, simultaneitats, incompatibilitats i franges buides.",
                "panel": "globals",
                "highlight": "[data-avatar-anchor='rotations-validation']",
                "scroll": False,
            },
            {
                "text": "Els avisos no bloquegen el desat; serveixen per detectar problemes abans de publicar o exportar.",
                "panel": "globals",
                "highlight": "[data-avatar-anchor='rotations-validation']",
                "scroll": False,
            },
        ],
        "actions": [],
    },
    "rotations_rest_station": {
        "id": "rotations_rest_station",
        "title": "Estacio de descans",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Una estacio de descans afegeix una columna auxiliar per representar pauses o espais sense aparell competitiu.",
                "panel": "globals",
                "highlight": "[data-avatar-anchor='rotations-rest-station']",
                "scroll": False,
            },
        ],
        "actions": [],
    },
    "rotations_clear_program": {
        "id": "rotations_clear_program",
        "title": "Netejar programa",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "warning",
        "steps": [
            {
                "text": "Netejar programa elimina les assignacions de la graella i serveix per reiniciar la planificacio.",
                "panel": "globals",
                "highlight": "[data-avatar-anchor='rotations-clear-program']",
                "scroll": False,
            },
            {
                "text": "Es una accio global i destructiva; convé usar-la nomes quan vols tornar a comencar la distribucio.",
                "panel": "globals",
                "highlight": "[data-avatar-anchor='rotations-clear-program']",
                "scroll": False,
            },
        ],
        "actions": [],
    },
}
