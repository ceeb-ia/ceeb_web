EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


AVATAR_MESSAGES = {
    "scores_qrs_overview": {
        "id": "scores_qrs_overview",
        "title": "Notes i QRs",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Benvingut a Notes i QRs. Aquesta pantalla et permet seguir i gestionar les notes que els jutges van enviant durant la competició.",
                "highlight": "[data-avatar-anchor='scores-qrs-header']",
            },
            {
                "text": "Les notes arriben a través dels QRs i dels enllaços que has habilitat des de l'administrador de QRs. Cada jutge pot introduir les puntuacions des del seu dispositiu.",
                "highlight": "[data-avatar-anchor='scores-qrs-top-actions']",
            },
            {
                "text": "A la part superior tens filtres per trobar ràpidament el que necessites: franja competitiva, unitat, aparell, fase, participant i altres criteris de cerca.",
                "highlight": "[data-avatar-anchor='scores-qrs-filters']",
            },
            {
                "text": "Aquests filtres només canvien el que veus a la taula de resultats. Són especialment útils quan hi ha molts aparells, grups o exercicis actius alhora.",
                "highlight": "[data-avatar-anchor='scores-qrs-results']",
            },
            {
                "text": "Les taules apareixen plegades inicialment per carregar la pantalla més ràpidament. Pots anar expandint els blocs que vulguis revisar i veure com es van omplint les puntuacions.",
                "highlight": "[data-avatar-anchor='scores-qrs-collapsed-tables']",
            },
            {
                "text": "Quan els jutges envien una nota, la pantalla s'actualitza automàticament. Això et permet seguir el directe sense haver de refrescar manualment.",
                "highlight": "[data-avatar-anchor='scores-qrs-live-status']",
            },
            {
                "text": "Recorda que les notes només les poden modificar els jutges o els usuaris d'organització amb els permisos corresponents.",
                "highlight": "[data-avatar-anchor='scores-qrs-permissions']",
            },
            {
                "text": "Des dels botons superiors també pots obrir les classificacions públiques, activar el bucle automàtic de classificacions, entrar a l'administrador de QRs o contactar amb el suport de jutges.",
                "highlight": "[data-avatar-anchor='scores-qrs-top-actions']",
                "actions": [
                    {
                        "label": "Classificacions live",
                        "action": "navigate",
                        "selector": "[data-avatar-action='scores-qrs-open-live']",
                    },
                    {
                        "label": "Loop públic",
                        "action": "navigate",
                        "selector": "[data-avatar-action='scores-qrs-open-loop']",
                    },
                    {
                        "label": "Administrador QRs",
                        "action": "navigate",
                        "selector": "[data-avatar-action='scores-qrs-open-qr-admin']",
                    },
                    {
                        "label": "Suport jutges",
                        "action": "navigate",
                        "selector": "[data-avatar-action='scores-qrs-open-support']",
                    },
                ],
            },
        ],
        "actions": [],
    },
}
