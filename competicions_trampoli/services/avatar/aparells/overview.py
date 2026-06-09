EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


AVATAR_MESSAGES = {
    "competition_apparatus_phases": {
        "id": "competition_apparatus_phases",
        "title": "Aparells i fases",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Aquesta pantalla reuneix els aparells locals de la competicio i l'arbre de fases de cadascun.",
                "highlight": "[data-avatar-anchor='phase-header']",
            },
            {
                "text": "Cada pestanya representa una instancia local d'un aparell dins d'aquesta competicio, separada del cataleg global.",
                "highlight": "[data-avatar-anchor='phase-app-selector']",
            },
            {
                "text": "L'arbre parteix de la preliminar implicita i creix amb fases filles com semifinals, finals o rondes especifiques.",
                "highlight": "[data-avatar-anchor='phase-tree']",
            },
            {
                "text": "El menu lateral concentra les accions de configuracio de la fase seleccionada: origen i tall, grups i estat.",
                "panel": "origin",
                "highlight": "[data-avatar-anchor='phase-actions-drawer']",
                "scroll": False,
            },
        ],
        "actions": [],
    },
}
