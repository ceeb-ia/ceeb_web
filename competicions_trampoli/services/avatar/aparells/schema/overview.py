EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


def info_topic(topic_id, title, steps):
    return {
        "id": topic_id,
        "title": title,
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": steps,
        "actions": [],
    }


AVATAR_MESSAGES = {
    "welcome": info_topic(
        "welcome",
        "Configuracio de puntuacio",
        [
            {
                "text": "Aquesta es la vista de configuracio de puntuacio dels aparells.",
                "highlight": ".schema-heading",
            },
            {
                "text": "Es una part molt important d'IA Score, perque permet adaptar el programa a una gran diversitat d'esports, modalitats i sistemes de puntuacio.",
                "highlight": ".schema-heading",
            },
            {
                "text": "Aqui configures com es puntua un aparell dins d'una competicio: quins valors introdueixen els jutges, com es combinen i quines notes finals es generen.",
                "highlight": ".schema-builder-surface",
            },
            {
                "text": "La pantalla es divideix en 3 parts principals: Camps, Formules i JSON avancat.",
                "highlight": ".schema-workflow-tabs",
            },
        ],
    ),
    "schema_sections": info_topic(
        "schema_sections",
        "Parts de la pantalla",
        [
            {
                "text": "A Camps defineixes els camps crus de puntuacio, es a dir, els valors que els jutges introduiran directament durant la competicio.",
                "highlight": "#tab-fields",
            },
            {
                "text": "A Formules configures les operacions que es fan amb aquests camps: com es combinen, com s'operen entre ells i quins resultats finals se'n deriven.",
                "highlight": "#tab-formules",
                "scroll": "#tab-formules",
            },
            {
                "text": "A JSON avancat pots editar la configuracio de manera mes tecnica, pensada nomes per a casos avancats o configuracions especials.",
                "highlight": "#tab-advanced",
                "scroll": "#tab-advanced",
            },
        ],
    ),
    "schema_json": info_topic(
        "schema_json",
        "JSON avancat",
        [
            {
                "text": "A JSON avancat pots editar la configuracio de manera mes tecnica, pensada nomes per a casos avancats o configuracions especials.",
                "highlight": "#advancedJson",
            },
        ],
    ),
    "schema_language_summary": info_topic(
        "schema_language_summary",
        "Llenguatge de puntuacio",
        [
            {
                "text": "En resum, aquesta vista defineix el llenguatge de puntuacio de cada aparell: que es demana als jutges i com IA Score transforma aquestes dades en resultats.",
                "highlight": ".schema-builder-surface",
            },
        ],
    ),
}
