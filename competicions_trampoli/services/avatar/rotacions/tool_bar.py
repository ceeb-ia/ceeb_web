from .overview import EXPLAINING_AVATARS


AVATAR_MESSAGES = {
    "competition_rotations_toolbar": {
        "id": "competition_rotations_toolbar",
        "title": "Planner",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "La barra del planner concentra els panells de treball per preparar i revisar el programa.",
                "highlight": "[data-avatar-anchor='rotations-toolbar']",
            },
            {
                "text": "Programables conte els grups, series i unitats de fase que pots arrossegar a la graella.",
                "panel": "programables",
                "highlight": "[data-avatar-anchor='rotations-nav-programables']",
                "scroll": False,
                "actions": [{"label": "Obrir Programables", "action": "open_panel", "panel": "programables"}],
            },
            {
                "text": "Franges agrupa la creacio manual, la generacio automatica i les accions massives sobre franges seleccionades.",
                "panel": "franges",
                "highlight": "[data-avatar-anchor='rotations-nav-franges']",
                "scroll": False,
                "actions": [{"label": "Obrir Franges", "action": "open_panel", "panel": "franges"}],
            },
            {
                "text": "Eines reuneix validacio, visibilitat, notes internes, descansos i operacions globals.",
                "panel": "globals",
                "highlight": "[data-avatar-anchor='rotations-nav-tools']",
                "scroll": False,
                "actions": [{"label": "Obrir Eines", "action": "open_panel", "panel": "globals"}],
            },
            {
                "text": "Export prepara les dades i camps que sortiran als Excels del programa.",
                "panel": "export",
                "highlight": "[data-avatar-anchor='rotations-nav-export']",
                "scroll": False,
                "actions": [{"label": "Obrir Export", "action": "open_panel", "panel": "export"}],
            },
        ],
        "actions": [],
    },
}
