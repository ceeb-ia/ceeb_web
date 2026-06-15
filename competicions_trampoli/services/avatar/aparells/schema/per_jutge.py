from .overview import info_topic


AVATAR_MESSAGES = {
    "formula_per_judge_overview": info_topic(
        "formula_per_judge_overview",
        "Per jutge",
        [
            {
                "text": "La formula Per jutge serveix per tractar primer els valors de cada jutge i, despres, combinar els resultats entre jutges.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "Es util quan vols resoldre cada fila de la matriu per separat abans d'arribar a una nota final.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "Pensa en la matriu del camp font com una taula: cada fila es un jutge i cada columna es un item.",
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
    "formula_per_judge_global": info_topic(
        "formula_per_judge_global",
        "Per jutge: global",
        [
            {
                "text": "A Configuracio global esculls el camp font, es a dir, la matriu de valors sobre la qual vols treballar.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Tambe pots definir una operacio per item abans d'agregar res.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Per exemple, pots deixar els valors tal com estan, sumar 1 a cada item, o restar el valor introduit a un valor de referencia.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "En aquesta mateixa part pots indicar el rang d'items que vols tenir en compte amb Start i Count.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Aixo permet aplicar el calcul nomes a una part dels items, si no vols utilitzar tota la fila.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
        ],
    ),
    "formula_per_judge_internal": info_topic(
        "formula_per_judge_internal",
        "Per jutge: fase interna",
        [
            {
                "text": "A la fase interna es resol cada jutge per separat.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Dins del rang configurat, pots seleccionar quins items compten per a cada jutge.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Despres defineixes com s'agreguen aquests items: per exemple, sumant-los, fent-ne una mitjana o aplicant el criteri que correspongui.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Opcionalment, pots aplicar una operacio final sobre el resultat de cada jutge.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "El mateix proces s'aplica a tots els jutges, de manera que al final obtens un resultat per cada fila.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
        ],
    ),
    "formula_per_judge_final": info_topic(
        "formula_per_judge_final",
        "Per jutge: fase final",
        [
            {
                "text": "A la fase final, IA Score treballa amb aquests resultats per jutge.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Aqui pots seleccionar quins jutges compten i com s'agreguen entre ells.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Aquest ultim pas col.lapsa els resultats de tots els jutges en una unica nota escalar.",
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
    "formula_per_judge_list_overview": info_topic(
        "formula_per_judge_list_overview",
        "Llistat per jutge",
        [
            {
                "text": "Aquesta formula es un cas especial: resol els valors de cada jutge, pero no els combina entre jutges.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "Per entendre-la, imagina de nou el camp font com una taula de valors.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "En aquesta taula, cada fila representa un jutge i cada columna representa un item.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "La formula treballa fila per fila: agafa els items d'un jutge, els selecciona i els agrega per obtenir un resultat per aquell jutge.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Aquest proces es repeteix per tots els jutges del camp font.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
        ],
    ),
    "formula_per_judge_list_result": info_topic(
        "formula_per_judge_list_result",
        "Resultat per jutge",
        [
            {
                "text": "La diferencia important es que aqui no hi ha una fase final d'agregacio entre jutges.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Per tant, el resultat no es una sola nota final, sino una llista de notes: una nota per cada jutge.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Per exemple, si el camp font te 3 jutges, el resultat sera una llista amb 3 valors resolts.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Aquest resultat pot ser util en configuracions avancades on vols conservar separades les notes dels jutges per tractar-les despres.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
        ],
    ),
    "formula_per_judge_list_warning": info_topic(
        "formula_per_judge_list_warning",
        "Llista no escalar",
        [
            {
                "text": "Ara be, aquesta formula no serveix directament per a una operacio simple que necessiti una nota unica.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Si vols utilitzar aquest resultat com una puntuacio final o en una classificacio, abans hauras de col.lapsar la llista entre jutges fins arribar a un unic valor.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "En resum: aquesta formula resol cada jutge per separat i conserva el resultat en format de llista, sense convertir-lo encara en una nota escalar.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
        ],
    ),
}
