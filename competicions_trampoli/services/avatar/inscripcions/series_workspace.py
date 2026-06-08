EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


AVATAR_MESSAGES = {
    "team_series_workspace": {
        "id": "team_series_workspace",
        "title": "Gestor de series d'equip",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Aquest gestor organitza equips en series per poder-los portar despres al programa de competicio."
            },
            {
                "text": "Una serie d'equip es l'equivalent a un grup, pero aplicada a unitats competitives d'equip en comptes d'inscripcions individuals."
            },
            {
                "text": "El workspace es divideix en zones: aparell d'equip, univers de candidates, accions sobre la seleccio, series creades i inspector lateral."
            },
        ],
        "actions": [],
    },
    "team_series_aparell": {
        "id": "team_series_aparell",
        "title": "Aparell d'equip",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Les series sempre es creen dins d'un aparell d'equip concret."
            },
            {
                "text": "Quan canvies d'aparell, IA Score recarrega els contextos vinculats, les candidates, les series i les previsualitzacions."
            },
            {
                "text": "La start list exporta la llista de sortida de l'aparell d'equip seleccionat."
            },
        ],
        "actions": [],
    },
    "team_series_universe": {
        "id": "team_series_universe",
        "title": "Univers de candidates",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "L'univers mostra les unitats competitives que poden formar series per a l'aparell seleccionat."
            },
            {
                "text": "Aquestes candidates no son inscripcions individuals: son equips construits des dels contextos d'equip vinculats a l'aparell."
            },
            {
                "text": "Si un aparell no te contextos font o els equips no tenen membres, el gestor mostra incidencies per indicar que cal revisar el gestor d'equips."
            },
        ],
        "actions": [],
    },
    "team_series_filters_selection": {
        "id": "team_series_filters_selection",
        "title": "Filtres i seleccio",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Pots cercar per equip, context o membres i filtrar per context, estat o serie actual."
            },
            {
                "text": "Amb Afegir incorpores les candidates visibles a la seleccio activa. Amb Netejar buides aquesta seleccio."
            },
            {
                "text": "Les accions del workspace treballen sobre aquesta seleccio, no sobre totes les candidates filtrades."
            },
        ],
        "actions": [],
    },
    "team_series_actions": {
        "id": "team_series_actions",
        "title": "Accions sobre la seleccio",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Aquesta zona aplica operacions directes sobre les unitats seleccionades."
            },
            {
                "text": "Pots crear una serie nova, assignar la seleccio a una serie existent o deixar aquestes unitats sense serie."
            },
            {
                "text": "La baixa d'una serie nomes es pot completar si la serie es buida i no esta programada."
            },
        ],
        "actions": [],
    },
    "team_series_creation_strategies": {
        "id": "team_series_creation_strategies",
        "title": "Estrategies de creacio",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Les estrategies reparteixen la seleccio activa en diverses series sense fer-ho manualment."
            },
            {
                "text": "Pots crear un nombre concret de series, series d'una mida fixa o equilibrada, o series dins d'una forquilla min-max."
            },
            {
                "text": "Previsualitza abans de crear per revisar el repartiment i detectar unitats invalides o ja assignades."
            },
        ],
        "actions": [],
    },
    "team_series_board": {
        "id": "team_series_board",
        "title": "Series creades",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "El board mostra les series actives de l'aparell seleccionat."
            },
            {
                "text": "Pots cercar i filtrar per context, contingut o estat de programa per revisar rapidament les series."
            },
            {
                "text": "Les series amb unitats i les series buides es mostren separades. Des del menu pots exportar la llista de sortida o desactivar series buides."
            },
        ],
        "actions": [],
    },
    "team_series_detail": {
        "id": "team_series_detail",
        "title": "Detall de la serie",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "El detall mostra les unitats que formen part de la serie seleccionada sense perdre el board."
            },
            {
                "text": "Des del detall pots renombrar la serie, assignar-hi la seleccio activa, treure unitats, reordenar-les o exportar un full de treball."
            },
            {
                "text": "L'ordre de les unitats dins la serie es guarda i serveix de base quan la serie es programa mes endavant."
            },
        ],
        "actions": [],
    },
    "team_series_preview": {
        "id": "team_series_preview",
        "title": "Previsualitzacio",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "La previsualitzacio mostra quines series i unitats quedaran afectades abans de confirmar una accio."
            },
            {
                "text": "Si canvies la seleccio, l'aparell o els valors d'una estrategia, la preview queda desactualitzada i cal tornar-la a calcular."
            },
            {
                "text": "Quan la preview es valida, pots confirmar l'accio des d'aquesta mateixa pestanya."
            },
        ],
        "actions": [],
    },
}
