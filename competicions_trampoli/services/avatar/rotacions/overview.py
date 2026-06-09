EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


AVATAR_MESSAGES = {
    "competition_rotations": {
        "id": "competition_rotations",
        "title": "Rotacions",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "A Rotacions construeixes el programa horari real de la competicio: franges, estacions i unitats programables.",
                "highlight": "[data-avatar-anchor='rotations-header']",
            },
            {
                "text": "El planner treballa amb grups, series d'equip i unitats de fases avancades; aquests elements es col.loquen a la graella.",
                "panel": "programables",
                "highlight": "[data-avatar-anchor='rotations-panel-programables']",
                "scroll": False,
            },
            {
                "text": "La graella es el centre del flux: cada fila es una franja i cada columna es una estacio o aparell.",
                "highlight": "[data-avatar-anchor='rotations-grid-table']",
                "scroll": "[data-avatar-anchor='rotations-grid-header']",
            },
            {
                "text": "Abans de donar el programa per bo, revisa avisos, guarda els canvis i exporta el resultat si el necessites fora d'IA Score.",
                "panel": "globals",
                "highlight": "[data-avatar-anchor='rotations-validation']",
                "scroll": False,
            },
        ],
        "actions": [],
    },
}
