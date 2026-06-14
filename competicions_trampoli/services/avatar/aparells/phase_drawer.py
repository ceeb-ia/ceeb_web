from .overview import EXPLAINING_AVATARS


AVATAR_MESSAGES = {
    "phase_actions_menu": {
        "id": "phase_actions_menu",
        "title": "Menu d'accions",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Aquest menu lateral treballa sempre sobre la fase seleccionada a l'arbre.",
                "panel": "origin",
                "highlight": "[data-avatar-anchor='phase-actions-drawer']",
                "scroll": False,
            },
            {
                "text": "Origen i tall defineix la recepta de classificacio que alimentara la fase.",
                "panel": "origin",
                "highlight": "[data-avatar-anchor='phase-nav-origin']",
                "scroll": False,
            },
            {
                "text": "Grups prepara les unitats buides i la seva estructura abans de congelar qui hi entra.",
                "panel": "groups",
                "highlight": "[data-avatar-anchor='phase-nav-groups']",
                "scroll": False,
            },
            {
                "text": "Estat i snapshot controlen quan es congelen places i quan la fase queda disponible o tancada.",
                "panel": "status",
                "highlight": "[data-avatar-anchor='phase-nav-status']",
                "scroll": False,
            },
        ],
        "actions": [],
    },
    "phase_origin_cut": {
        "id": "phase_origin_cut",
        "title": "Origen i tall",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "La recepta tria la classificacio font i la regla que fara passar participants, equips o grups a aquesta fase.",
                "panel": "origin",
                "highlight": "[data-avatar-anchor='phase-panel-origin']",
                "scroll": False,
            },
            {
                "text": "Els classificats i reserves defineixen quantes places entren al snapshot i quines queden disponibles per substitucions.",
                "panel": "origin",
                "highlight": "[data-avatar-anchor='phase-source-cut-form']",
                "scroll": False,
            },
            {
                "text": "Pots crear les fases primer i tornar a aquesta pantalla a configurar l'origen i el tall quan hagis creat les classificaicions.",
                "panel": "origin",
                "highlight": "[data-avatar-anchor='phase-source-cut-form']",
                "scroll": False,
            },
        ],
        "actions": [],
    },
    "phase_groups": {
        "id": "phase_groups",
        "title": "Grups i unitats",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "El pla de grups prepara l'estructura de blocs programables de la fase.",
                "panel": "groups",
                "highlight": "[data-avatar-anchor='phase-panel-groups']",
                "scroll": False,
            },
            {
                "text": "La previsualitzacio permet comprovar quantes unitats i places es crearan abans d'aplicar el pla.",
                "panel": "groups",
                "highlight": "[data-avatar-anchor='phase-group-plan-form']",
                "scroll": False,
            },
        ],
        "actions": [],
    },
    "phase_status_snapshot": {
        "id": "phase_status_snapshot",
        "title": "Estat i snapshot",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "El snapshot omple les unitats existents amb els classificats segons la recepta actual.",
                "panel": "status",
                "highlight": "[data-avatar-anchor='phase-qualification']",
                "scroll": False,
            },
            {
                "text": "L'estat de la fase controla si encara es prepara, si ja es publica o si queda tancada.",
                "panel": "status",
                "highlight": "[data-avatar-anchor='phase-status-form']",
                "scroll": False,
            },
            {
                "text": "La lectura rapida mostra avisos de font canviada, snapshot pendent, grups a revisar o rotacions pendents.",
                "panel": "status",
                "highlight": "[data-avatar-anchor='phase-status-summary']",
                "scroll": False,
            },
        ],
        "actions": [],
    },
}
