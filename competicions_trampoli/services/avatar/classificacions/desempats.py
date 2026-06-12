EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


AVATAR_MESSAGES = {
    "classifications_tiebreakers": {
        "id": "classifications_tiebreakers",
        "title": "Desempats",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "A Desempats pots definir criteris addicionals per ordenar la classificació quan dues o més unitats competitives tenen la mateixa puntuació.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-section']",
            },
            {
                "text": "Aquesta secció funciona de manera semblant a Puntuació, però aplicada només als casos d’empat.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-chain']",
            },
        ],
        "actions": [],
    },
    "classifications_tiebreakers_chain": {
        "id": "classifications_tiebreakers_chain",
        "title": "Cadena de criteris",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Amb el botó Afegir desempat pots crear una cadena de criteris jeràrquics.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-actions']",
            },
            {
                "text": "IA Score aplicarà aquests criteris en ordre: primer el primer desempat, després el segon, i així successivament fins que es resolgui l’empat.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-workspace']",
            },
            {
                "text": "Cada criteri de desempat té un nom propi, perquè puguis identificar fàcilment què està comparant.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-workspace']",
            },
            {
                "text": "També has d’indicar l’ordre del score: ascendent o descendent, segons si en aquell criteri és millor tenir un valor més baix o més alt.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-workspace']",
            },
        ],
        "actions": [],
    },
    "classifications_tiebreakers_input": {
        "id": "classifications_tiebreakers_input",
        "title": "Entrada del desempat",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Com a diferència important respecte a Puntuació, aquí també has de definir l’entrada del desempat.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-workspace']",
            },
            {
                "text": "L’entrada pot prendre tots els exercicis de la unitat competitiva des de zero, o només els exercicis que han contribuït a la puntuació principal.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-workspace']",
            },
            {
                "text": "Si esculls tots els exercicis, el desempat es calcularà sobre tota la informació disponible segons els aparells, fases i camps que configuris.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-workspace']",
            },
            {
                "text": "Si esculls només els exercicis contribuïdors, el desempat partirà únicament de les notes que ja han format part del càlcul principal.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-workspace']",
            },
        ],
        "actions": [],
    },
    "classifications_tiebreakers_apparatus_flow": {
        "id": "classifications_tiebreakers_apparatus_flow",
        "title": "Aparells i tractament",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Després has de seleccionar els aparells sobre els quals vols aplicar el criteri de desempat.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-workspace']",
            },
            {
                "text": "També has d’indicar si aquests aparells es tractaran per separat o com un sac conjunt de notes.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-workspace']",
            },
            {
                "text": "Amb tractament separat, IA Score resol el criteri per cada aparell i després combina els resultats si cal.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-workspace']",
            },
            {
                "text": "Amb sac conjunt, les notes seleccionades dels aparells entren al desempat sense diferenciar de quin aparell provenen.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-workspace']",
            },
        ],
        "actions": [],
    },
    "classifications_tiebreakers_fields": {
        "id": "classifications_tiebreakers_fields",
        "title": "Camps i agregació",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Per cada aparell, pots seleccionar els camps que vols tenir en compte.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-workspace']",
            },
            {
                "text": "Aquests camps són els valors puntuables configurats dins de l’aparell, igual que a la secció de Puntuació.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-workspace']",
            },
            {
                "text": "A partir dels camps seleccionats, configures els criteris de selecció i agregació de les notes.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-workspace']",
            },
            {
                "text": "Aquesta selecció i agregació sempre es fa sobre la base d’entrada que hagis triat per al desempat.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-workspace']",
            },
        ],
        "actions": [],
    },
    "classifications_tiebreakers_final_value": {
        "id": "classifications_tiebreakers_final_value",
        "title": "Valor final",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Finalment, si la tipologia del desempat ho requereix, IA Score aplica una selecció i agregació final per obtenir el valor que servirà per comparar els empatats.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-workspace']",
            },
        ],
        "actions": [],
    },
    "classifications_tiebreakers_priority": {
        "id": "classifications_tiebreakers_priority",
        "title": "Prioritat i canvis",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Pots reordenar els criteris de desempat amb les fletxes per canviar-ne la prioritat.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-workspace']",
            },
            {
                "text": "També pots eliminar qualsevol criteri que ja no vulguis aplicar.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-workspace']",
            },
            {
                "text": "Recorda guardar sempre els canvis perquè la configuració de desempats quedi aplicada a la classificació.",
                "highlight": "[data-avatar-anchor='classifications-tiebreakers-section']",
            },
        ],
        "actions": [],
    },
}
