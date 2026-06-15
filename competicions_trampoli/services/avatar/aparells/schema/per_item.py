from .overview import info_topic


AVATAR_MESSAGES = {
    "formula_per_item_overview": info_topic(
        "formula_per_item_overview",
        "Per item",
        [
            {
                "text": "La formula Per item serveix per tractar primer cada item entre els diferents jutges i, despres, combinar els resultats dels items.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "Es util quan vols que IA Score compari o agregui les puntuacions dels jutges per cada item abans d'arribar a una nota final.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "Pensa en el camp font com una taula de valors.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "En aquesta taula, cada fila representa un jutge i cada columna representa un item.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "La formula Per item treballa primer per columnes.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "Aixo vol dir que, per cada item, IA Score mira els valors que han introduit tots els jutges.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "Per exemple, si tens 3 jutges i 10 items, IA Score analitza primer l'item 1 amb les notes dels 3 jutges, despres l'item 2 amb les notes dels 3 jutges, i aixi successivament.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "Aquesta formula segueix un flux de 3 parts: configuracio global, fase interna i fase final.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
        ],
    ),
    "formula_per_item_global": info_topic(
        "formula_per_item_global",
        "Per item: global",
        [
            {
                "text": "A Configuracio global esculls el camp font, es a dir, la taula de valors sobre la qual vols treballar.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Tambe pots definir una operacio per item abans d'agregar res.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Aquesta operacio s'aplica als valors crus abans que IA Score comenci a seleccionar o combinar resultats.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Per exemple, pots deixar els valors tal com estan, sumar-hi un valor, restar-los d'un valor de referencia o aplicar-hi l'operacio que correspongui.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "En aquesta mateixa part pots indicar el rang d'items que vols tenir en compte amb Start i Count.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Aixo permet aplicar el calcul nomes a una part dels items, si no vols utilitzar totes les columnes de la taula.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
        ],
    ),
    "formula_per_item_internal": info_topic(
        "formula_per_item_internal",
        "Per item: fase interna",
        [
            {
                "text": "A la fase interna es resol cada item per separat.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Per cada item dins del rang configurat, IA Score recull les notes introduides pels diferents jutges.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Despres pots seleccionar quines notes dels jutges compten per aquell item.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Per exemple, pots tenir en compte totes les notes, descartar-ne alguna, quedar-te amb les millors o aplicar el criteri disponible que necessitis.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Un cop seleccionades les notes de l'item, defineixes com s'agreguen entre elles.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Aquesta agregacio converteix les notes dels jutges en un unic resultat per aquell item.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "El mateix proces s'aplica a cada item del rang, de manera que al final obtens un resultat per cada columna.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
        ],
    ),
    "formula_per_item_final": info_topic(
        "formula_per_item_final",
        "Per item: fase final",
        [
            {
                "text": "A la fase final, IA Score treballa amb aquests resultats per item.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Aqui pots seleccionar quins items resolts compten per al resultat final.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Despres defineixes com s'agreguen aquests items entre ells.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Aquest ultim pas col.lapsa els resultats dels items en una unica nota escalar.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Aquesta nota final ja es un valor 1x1 i es pot utilitzar en altres formules, resultats o classificacions.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
        ],
    ),
}
