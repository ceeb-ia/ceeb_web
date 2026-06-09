from .overview import EXPLAINING_AVATARS


AVATAR_MESSAGES = {
    "phase_tree": {
        "id": "phase_tree",
        "title": "Arbre de fases",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "L'arbre mostra el recorregut competitiu de l'aparell: la preliminar implicita i les fases filles que vas creant.",
                "highlight": "[data-avatar-anchor='phase-tree']",
            },
            {
                "text": "La preliminar implicita es l'arrel visual. No es desa com una fase avancada, pero es el punt de partida del flux.",
                "highlight": "[data-avatar-anchor='phase-base-node']",
            },
            {
                "text": "Crear fase filla serveix per preparar una nova ronda que penja de la preliminar o d'una altra fase.",
                "highlight": "[data-avatar-anchor='phase-child-create']",
            },
        ],
        "actions": [],
    },
    "phase_base": {
        "id": "phase_base",
        "title": "Preliminar implicita",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "La preliminar representa la base de participacióo i puntuacio de l'aparell abans de crear rondes posteriors.",
                "highlight": "[data-avatar-anchor='phase-base-detail']",
            },
            {
                "text": "La configuracio base indica quants exercicis te la preliminar i et dona acces a la puntuacio de l'aparell.",
                "highlight": "[data-avatar-anchor='phase-base-scoring']",
            },
            {
                "text": "El seguent pas natural es crear una fase filla o revisar la participacióo de l'aparell.",
                "highlight": "[data-avatar-anchor='phase-base-next-step']",
            },
        ],
        "actions": [],
    },
}
