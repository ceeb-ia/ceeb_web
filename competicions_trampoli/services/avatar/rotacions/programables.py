from .overview import EXPLAINING_AVATARS


AVATAR_MESSAGES = {
    "rotations_programmables": {
        "id": "rotations_programmables",
        "title": "Programables",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Aqui tens les unitats que es poden col.locar a la graella: grups, series d'equip i unitats de fases.",
                "panel": "programables",
                "highlight": "[data-avatar-anchor='rotations-panel-programables']",
                "scroll": False,
            },
            {
                "text": "Arrossega una unitat pendent fins a una cel.la per programar-la en aquella franja i estacio.",
                "panel": "programables",
                "highlight": "[data-avatar-anchor='rotations-programmable-pending']",
                "scroll": False,
            },
            {
                "text": "Els filtres ajuden a trobar unitats per tipus, categoria, subcategoria o entitat quan el programa creix.",
                "panel": "programables",
                "highlight": "[data-avatar-anchor='rotations-programmable-filters']",
                "scroll": False,
            },
        ],
        "actions": [],
    },
}
