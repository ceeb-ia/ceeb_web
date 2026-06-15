from .overview import info_topic


AVATAR_MESSAGES = {
    "formula_between_members_overview": info_topic(
        "formula_between_members_overview",
        "Entre membres",
        [
            {
                "text": "En aparells d'equip existeix una formula especial anomenada Entre membres.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "Aquesta formula permet agafar un camp individual dels membres de l'equip i convertir-lo en un unic valor d'equip.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "Es util quan vols obtenir una nota d'equip derivada de les notes individuals dels seus membres.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "Per exemple, pots tenir una nota individual calculada per cada membre i despres seleccionar-ne les millors, sumar-les o agregar-les per obtenir una puntuacio conjunta de l'equip.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
        ],
    ),
    "formula_between_members_source": info_topic(
        "formula_between_members_source",
        "Font individual",
        [
            {
                "text": "A diferencia d'altres formules, aqui IA Score no treballa amb una matriu de jutges per items.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "La font d'aquesta formula ha de ser una llista de valors: una nota ja resolta per cada membre de l'equip.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Aixo vol dir que abans cal haver definit com es calcula la nota individual de cada membre.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Aquest calcul previ es pot fer amb les formules de tractament de camps comentades abans, com les que resolen per jutge, per item o per jutge en format de llista.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "En aparells d'equip, aquest tractament individual s'aplica a tots els membres de l'equip.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
        ],
    ),
    "formula_between_members_reduce": info_topic(
        "formula_between_members_reduce",
        "Reduccio d'equip",
        [
            {
                "text": "Un cop IA Score te una nota per cada membre, la formula Entre membres permet seleccionar quines d'aquestes notes compten.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Despres, aquestes notes seleccionades s'agreguen per obtenir un unic valor escalar d'equip.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Aquest resultat final ja es una nota 1x1 i es pot utilitzar en formules posteriors, resultats de l'aparell o classificacions.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "En resum: Entre membres serveix per passar d'un conjunt de notes individuals dels membres a una sola nota d'equip.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
        ],
    ),
}
