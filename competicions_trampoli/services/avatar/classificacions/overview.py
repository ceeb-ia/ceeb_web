EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


AVATAR_MESSAGES = {
    "competition_classifications": {
        "id": "competition_classifications",
        "title": "Classificacions",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "A la pantalla de Classificacions treballaràs amb el tractament de les notes que els jutges introdueixen als diferents aparells i fases de la competició.",
                "highlight": "[data-avatar-anchor='classifications-header']",
            },
            {
                "text": "Aquí pots crear tantes classificacions com necessitis, segons com vulguis interpretar, ordenar o agrupar els resultats.",
                "highlight": "[data-avatar-anchor='classifications-config-list']",
            },
            {
                "text": "Cada classificació pot tenir la seva pròpia configuració, la seva visibilitat de cara al públic i el seu estat actiu o inactiu.",
                "highlight": "[data-avatar-anchor='classifications-metadata-section']",
            },
            {
                "text": "La pantalla està organitzada en 3 columnes: Classificacions, Secció i Detall.",
                "highlight": "[data-avatar-anchor='classifications-workspace']",
            },
        ],
        "actions": [],
    },
    "classifications_config_list": {
        "id": "classifications_config_list",
        "title": "Columna Classificacions",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "A la columna Classificacions trobaràs el llistat de totes les classificacions existents.",
                "highlight": "[data-avatar-anchor='classifications-config-list']",
            },
            {
                "text": "Des d’aquesta columna també pots crear una nova classificació amb el botó Afegir.",
                "highlight": "[data-avatar-anchor='classifications-add-button']",
            },
        ],
        "actions": [],
    },
    "classifications_section_flow": {
        "id": "classifications_section_flow",
        "title": "Columna Secció",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Quan selecciones una classificació, la columna Secció et mostra els passos de configuració en un ordre natural.",
                "highlight": "[data-avatar-anchor='classifications-section-nav']",
            },
            {
                "text": "Aquest ordre t’ajuda a construir la classificació pas a pas, sense haver de configurar-ho tot de cop.",
                "highlight": "[data-avatar-anchor='classifications-section-nav']",
            },
        ],
        "actions": [],
    },
    "classifications_detail_flow": {
        "id": "classifications_detail_flow",
        "title": "Columna Detall",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Finalment, a la columna Detall es desplega la configuració específica de la secció que tinguis seleccionada.",
                "highlight": "[data-avatar-anchor='classifications-detail-pane']",
            },
            {
                "text": "Pensa en aquesta pantalla com un flux jeràrquic d’esquerra a dreta: primer tries la classificació, després la secció, i finalment ajustes el detall.",
                "highlight": "[data-avatar-anchor='classifications-workspace']",
            },
        ],
        "actions": [],
    },
}
