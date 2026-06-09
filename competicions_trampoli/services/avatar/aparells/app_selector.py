from .overview import EXPLAINING_AVATARS


AVATAR_MESSAGES = {
    "phase_app_selector": {
        "id": "phase_app_selector",
        "title": "Aparells locals",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Aquestes pestanyes canvien l'aparell de competicio sobre el qual estas treballant.",
                "highlight": "[data-avatar-anchor='phase-app-selector']",
            },
            {
                "text": "Participacióo et porta a decidir quines inscripcions o equips competeixen en l'aparell seleccionat.",
                "highlight": "[data-avatar-action='phase-participation']",
                "actions": [
                    {
                        "label": "Participacióo",
                        "action": "navigate",
                        "selector": "[data-avatar-action='phase-participation']",
                    },
                ],
            },
            {
                "text": "Afegir aparell crea una nova instancia local per aquesta competicio a partir del cataleg global.",
                "highlight": "[data-avatar-action='phase-add-apparatus']",
                "actions": [
                    {
                        "label": "Afegir aparell",
                        "action": "navigate",
                        "selector": "[data-avatar-action='phase-add-apparatus']",
                    },
                ],
            },
        ],
        "actions": [],
    },
}
