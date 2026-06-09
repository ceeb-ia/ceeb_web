from .overview import EXPLAINING_AVATARS


AVATAR_MESSAGES = {
    "phase_selected_detail": {
        "id": "phase_selected_detail",
        "title": "Detall de fase",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Aquest resum concentra l'estat de la fase seleccionada i ajuda a detectar que falta configurar.",
                "highlight": "[data-avatar-anchor='phase-detail-panel']",
            },
            {
                "text": "Origen i tall resumeix d'on sortiran els classificats i quina regla s'aplicara.",
                "highlight": "[data-avatar-anchor='phase-summary-source']",
            },
            {
                "text": "Unitats i places mostra els blocs programables que despres podran anar a rotacions.",
                "highlight": "[data-avatar-anchor='phase-summary-units']",
            },
            {
                "text": "Estat dona una lectura rapida de snapshot, grups, rotacions i reserves.",
                "highlight": "[data-avatar-anchor='phase-summary-status']",
            },
        ],
        "actions": [],
    },
}
