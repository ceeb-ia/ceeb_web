from .overview import info_topic


AVATAR_MESSAGES = {
    "formulas_overview": info_topic(
        "formulas_overview",
        "Formules",
        [
            {
                "text": "A Formules defineixes com IA Score transforma els camps introduits pels jutges en resultats calculats.",
                "highlight": "#tab-formules",
                "scroll": "#tab-formules",
            },
            {
                "text": "Aquesta seccio es especialment important, perque es on decideixes com es tracten les taules de valors que s'han creat a Camps.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "Recorda que un camp pot contenir diversos jutges i diversos items. Les formules indiquen com convertir aquests valors en una nota utilitzable.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
        ],
    ),
    "formula_row_identity": info_topic(
        "formula_row_identity",
        "Fila de formula",
        [
            {
                "text": "La taula de Formules es semblant a la de Camps: cada fila te una Etiqueta, un Code i una Var.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "L'Etiqueta es el nom visible de la formula, el Code es el seu identificador intern i la Var es la variable que podras reutilitzar en altres formules.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "La diferencia principal es el camp Formula, que indica quin tipus de calcul o tractament s'aplicara.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
        ],
    ),
    "formula_detail_panel": info_topic(
        "formula_detail_panel",
        "Detall de formula",
        [
            {
                "text": "Quan selecciones una fila de formula, s'obre el detall de configuracio, on pots ajustar com es fara exactament aquell calcul.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
        ],
    ),
    "formula_manual": info_topic(
        "formula_manual",
        "Formula manual",
        [
            {
                "text": "La formula manual es la mes senzilla d'entendre: et permet escriure directament una operacio amb text simple.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Per exemple, si tens una variable e per Execucio i una variable d per Dificultat, podries escriure una formula com e * 2 + d / 10.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
            {
                "text": "Aquest tipus de formula es util quan els valors que utilitzes ja son notes simples o resultats que IA Score pot combinar directament.",
                "highlight": "#computedTable .formula-detail-row:not(.d-none)",
                "scroll": False,
            },
        ],
    ),
    "formula_scalar_warning": info_topic(
        "formula_scalar_warning",
        "Resultat escalar",
        [
            {
                "text": "Es important recordar que el resultat final d'una formula ha de ser un unic valor numeric.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "Si una formula retorna encara una taula de valors, per exemple diversos jutges o diversos items sense agregar, el validador avisara que la configuracio no es correcta.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
            {
                "text": "Per aixo, abans d'utilitzar una formula manual, assegura't que les variables que combines ja s'han resolt fins a una nota escalar.",
                "highlight": "#computedTable",
                "scroll": "#tab-formules",
            },
        ],
    ),
    "formulas_summary": info_topic(
        "formulas_summary",
        "Resum de formules",
        [
            {
                "text": "En resum: Camps recull el que introdueixen els jutges, i Formules decideix com aquests valors es tracten fins arribar a una o diverses notes finals de l'aparell.",
                "highlight": ".schema-workflow-tabs",
            },
        ],
    ),
}
