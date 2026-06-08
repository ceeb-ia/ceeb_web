from .groups_workspace import AVATAR_MESSAGES as GROUPS_WORKSPACE_MESSAGES
from .menu_lateral import AVATAR_MESSAGES as MENU_LATERAL_MESSAGES
from .multimedia import AVATAR_MESSAGES as MULTIMEDIA_MESSAGES
from .overview import AVATAR_MESSAGES as OVERVIEW_MESSAGES
from .series_workspace import AVATAR_MESSAGES as SERIES_WORKSPACE_MESSAGES
from .teams_workspace import AVATAR_MESSAGES as TEAMS_WORKSPACE_MESSAGES


EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


LOCAL_MESSAGES = {
    "inscriptions_divisions": {
        "id": "inscriptions_divisions",
        "title": "Divisions",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Les divisions separen la taula en pestanyes segons camps com categoria, subcategoria, entitat o altres columnes disponibles."
            },
            {
                "text": "Serveixen per revisar el llistat en blocs més petits sense canviar les inscripcions."
            },
            {
                "text": "Si actives una forquilla de data de naixement, pots definir els intervals que IA Score farà servir per crear aquestes pestanyes."
            },
            {
                "text": "La barreja aleatòria modifica l'ordre de sortida de les inscripcions visibles, així que convé revisar-la abans de continuar."
            },
        ],
        "actions": [],
    },
    "inscriptions_columns": {
        "id": "inscriptions_columns",
        "title": "Columnes",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Aquest panell controla quines columnes veus a la taula d'inscripcions i en quin ordre apareixen."
            },
            {
                "text": "Pots mostrar només els camps que necessites per al moment de treball actual i tornar a la vista per defecte quan vulguis."
            },
            {
                "text": "Les columnes natives són camps que el sistema necessita per funcionar; les columnes d'Excel provenen de les dades importades."
            },
        ],
        "actions": [],
    },
    "inscriptions_export_history": {
        "id": "inscriptions_export_history",
        "title": "Altres opcions",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "A Altres trobaràs eines complementàries del llistat, especialment l'exportació a Excel i el resum de l'historial."
            },
            {
                "text": "Abans d'exportar, pots triar quines columnes vols incloure al fitxer."
            },
            {
                "text": "L'historial t'indica si encara tens canvis que pots desfer o refer dins d'aquesta pantalla."
            },
        ],
        "actions": [],
    },
}


AVATAR_MESSAGES = {}
for catalog in (
    OVERVIEW_MESSAGES,
    MENU_LATERAL_MESSAGES,
    GROUPS_WORKSPACE_MESSAGES,
    TEAMS_WORKSPACE_MESSAGES,
    SERIES_WORKSPACE_MESSAGES,
    MULTIMEDIA_MESSAGES,
    LOCAL_MESSAGES,
):
    AVATAR_MESSAGES.update(catalog)


TOPIC_TITLES = {
    "competition_inscriptions": "Inscripcions",
    "competition_inscriptions_menu": "Menu d'accions",
    "groups_workspace": "Gestor de grups",
    "teams_workspace": "Gestor d'equips",
    "teams_workspace_context": "Context d'equips",
    "team_series_workspace": "Series d'equip",
    "multimedia_workspace": "Multimedia",
}

for topic_id, title in TOPIC_TITLES.items():
    if topic_id in AVATAR_MESSAGES:
        AVATAR_MESSAGES[topic_id] = {
            **AVATAR_MESSAGES[topic_id],
            "title": title,
        }
