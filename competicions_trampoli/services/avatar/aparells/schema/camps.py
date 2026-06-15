from .overview import info_topic


AVATAR_MESSAGES = {
    "fields_overview": info_topic(
        "fields_overview",
        "Camps",
        [
            {
                "text": "A Camps defineixes els valors que el jurat haura d'omplir durant la puntuacio d'aquest aparell.",
                "highlight": "#tab-fields",
            },
            {
                "text": "Cada camp representa una dada crua de puntuacio: una nota, una penalitzacio, una valoracio o qualsevol altre valor que despres IA Score podra utilitzar en les formules.",
                "highlight": "#fieldsTable",
            },
        ],
    ),
    "field_identity": info_topic(
        "field_identity",
        "Etiqueta, Code i Var",
        [
            {
                "text": "Quan configures un camp, el primer que has d'indicar es l'Etiqueta.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "L'Etiqueta es el nom visible del camp: el titol que veuran els jutges quan hagin d'introduir aquesta puntuacio.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "Tambe has de definir el Code i la Var.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "El Code serveix com a alies intern del camp, i la Var es la variable que podras utilitzar mes endavant dins de les formules.",
                "highlight": "#fieldsTable",
            },
        ],
    ),
    "field_scope": info_topic(
        "field_scope",
        "Abast",
        [
            {
                "text": "L'Abast indica a qui pertany aquell valor de puntuacio.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "En aparells individuals, l'abast queda restringit a individual, perque cada nota correspon a una inscripcio.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "En aparells d'equip, l'abast pot ser individual o compartit.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "Si l'abast es individual, el camp recull una nota d'un membre de l'equip. Si es compartit, recull una nota del conjunt de l'equip.",
                "highlight": "#fieldsTable",
            },
        ],
    ),
    "field_matrix_shape": info_topic(
        "field_matrix_shape",
        "Jutges i Items",
        [
            {
                "text": "A Jutges indiques quants jutges puntuaran aquest mateix camp.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "Aixo permet que un mateix valor sigui introduit per diversos jutges i despres pugui ser tractat a les formules segons el criteri que configuris.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "A Items defineixes en quants valors es desglossa aquest camp per cada jutge.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "Per exemple, en una rutina amb diversos elements, un camp com Execucio pot tenir un item per cada element valorat.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "Tambe pots aplicar aquesta logica a altres camps, com Dificultat o qualsevol valor que necessiti diversos registres dins del mateix exercici.",
                "highlight": "#fieldsTable",
            },
        ],
    ),
    "field_limits": info_topic(
        "field_limits",
        "Limits i decimals",
        [
            {
                "text": "Min i Max defineixen els limits del valor que pot introduir el jutge.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "Si els especifiques, IA Score ajustara el valor introduit quan superi aquests limits.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "Decimals indica la precisio del camp.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "Amb 0 decimals es treballa amb valors enters, amb 1 decimal amb decimes, amb 2 decimals amb centesimes, i aixi successivament.",
                "highlight": "#fieldsTable",
            },
        ],
    ),
    "field_crash": info_topic(
        "field_crash",
        "Crash",
        [
            {
                "text": "Finalment, Crash indica que el jutge pot marcar una interrupcio de l'exercici en un item concret.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "Quan es marca Crash, el motor deixa de considerar els items posteriors d'aquell camp per a aquell exercici.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "Aixo es util en modalitats on, si l'esportista interromp l'exercici, els elements seguents ja no han de comptar en el calcul.",
                "highlight": "#fieldsTable",
            },
        ],
    ),
    "fields_interpretation": info_topic(
        "fields_interpretation",
        "Com s'interpreta un camp",
        [
            {
                "text": "Abans de configurar camps, es important entendre com IA Score interpreta cada camp de puntuacio.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "Un camp no sempre es una sola nota. Pot ser una petita taula de valors, formada pels jutges que puntuen i pels items que cada jutge omple.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "Pensa-hi com una taula: cada fila es un jutge i cada columna es un item de puntuacio.",
                "highlight": "#fieldsTable",
            },
        ],
    ),
    "fields_example_execution": info_topic(
        "fields_example_execution",
        "Exemple d'Execucio",
        [
            {
                "text": "Per exemple, imagina que crees un camp anomenat Execucio.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "Aquest camp podria tenir el code Ex i la variable e, que despres podras utilitzar a les formules.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "Si Execucio la puntuen 3 jutges i cada jutge valora 10 items, IA Score guardara una taula de 3 jutges per 10 items.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "Aixo vol dir que el camp Execucio no sera encara una nota final unica, sino un conjunt de valors introduits pels jutges.",
                "highlight": "#fieldsTable",
            },
            {
                "text": "En aquest cas, el jutge 1 tindra 10 valors d'execucio, el jutge 2 en tindra 10 mes i el jutge 3 tambe en tindra 10.",
                "highlight": "#fieldsTable",
            },
        ],
    ),
    "fields_to_formulas": info_topic(
        "fields_to_formulas",
        "De Camps a Formules",
        [
            {
                "text": "Despres, a Formules, indicaras com s'han de seleccionar i agrupar aquests valors.",
                "highlight": "#tab-formules",
                "scroll": "#tab-formules",
            },
            {
                "text": "Pots decidir, per exemple, com combinar els items de cada jutge, com combinar els jutges entre ells o com obtenir una nota final d'Execucio.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "L'objectiu final sempre es arribar a una nota escalar: un unic valor numeric que IA Score pugui utilitzar en classificacions, desempats o resultats.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "Per aixo, els Camps defineixen que introdueixen els jutges, i les Formules defineixen com aquests valors es converteixen en una nota final utilitzable.",
                "highlight": ".schema-workflow-tabs",
            },
        ],
    ),
}
