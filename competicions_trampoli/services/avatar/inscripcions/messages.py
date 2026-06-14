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
                "text": "Serveixen per separar el llistat en blocs més petits sense canviar les inscripcions."
            },
            {
                "text": "Si actives una forquilla de data de naixement, pots definir els intervals que IA Score farà servir per crear aquestes pestanyes."
            },
            {
                "text": "La barreja aleatòria modifica l'ordre en que apareixen les inscripcions visibles, útil quan vols partir de una distribució aleatòria per la organització de la competició."
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


def _anchor(name):
    return f"[data-avatar-anchor='{name}']"


def _anchors(*names):
    return ", ".join(_anchor(name) for name in names)


STEP_CONTEXTS = {
    "competition_inscriptions": (
        {"highlight": _anchor("inscriptions-table"), "scroll": _anchor("inscriptions-table-header")},
        {
            "highlight": "[data-avatar-action='import_excel'], [data-avatar-action='new_inscription']",
            "actions": [
                {
                    "label": "Importar Excel",
                    "action": "navigate",
                    "selector": "[data-avatar-action='import_excel']",
                },
                {
                    "label": "Nova inscripcio",
                    "action": "navigate",
                    "selector": "[data-avatar-action='new_inscription']",
                },
            ],
        },
        {"highlight": _anchor("inscriptions-table"), "scroll": _anchor("inscriptions-table-header")},
        {"highlight": _anchor("inscriptions-search")},
        {"highlight": _anchor("inscriptions-table"), "scroll": _anchor("inscriptions-table-header")},
        {"panel": "agrupacio", "highlight": _anchor("actions-sidebar"), "scroll": False},
    ),
    "competition_inscriptions_menu": (
        {"panel": "agrupacio", "highlight": _anchor("actions-sidebar"), "scroll": False},
        {"panel": "agrupacio", "highlight": _anchors("nav-divisions", "nav-columns"), "scroll": False},
        {"panel": "grups", "highlight": _anchors("nav-groups", "nav-teams", "nav-series"), "scroll": False},
        {"panel": "media", "highlight": _anchors("nav-media", "nav-other"), "scroll": False},
        {"highlight": _anchor("actions-sidebar"), "scroll": False},
    ),
    "inscriptions_divisions": (
        {"panel": "agrupacio", "highlight": _anchor("panel-divisions")},
        {"panel": "agrupacio", "highlight": _anchor("division-fields")},
        {"panel": "agrupacio", "highlight": _anchor("birth-ranges")},
        {"panel": "agrupacio", "highlight": _anchor("panel-divisions")},
    ),
    "inscriptions_columns": (
        {"panel": "columnes", "highlight": _anchor("panel-columns")},
        {"panel": "columnes", "highlight": _anchor("columns-list")},
        {"panel": "columnes", "highlight": _anchor("columns-list")},
    ),
    "inscriptions_export_history": (
        {"panel": "altres", "highlight": _anchor("panel-other")},
        {"panel": "altres", "highlight": _anchor("excel-export")},
        {"panel": "altres", "highlight": _anchor("history-summary")},
    ),
    "groups_workspace": (
        {"panel": "grups", "highlight": _anchor("groups-workspace")},
        {"panel": "grups", "highlight": _anchor("groups-board")},
        {"panel": "grups", "highlight": _anchor("groups-universe")},
        {"panel": "grups", "highlight": _anchors("groups-universe", "groups-selection-actions", "groups-board", "groups-inspector")},
    ),
    "groups_universe": (
        {"panel": "grups", "highlight": _anchor("groups-universe")},
        {"panel": "grups", "highlight": _anchor("groups-universe")},
        {"panel": "grups", "highlight": _anchor("groups-universe")},
    ),
    "groups_selection_actions": (
        {"panel": "grups", "highlight": _anchor("groups-selection-actions")},
        {"panel": "grups", "highlight": _anchor("groups-direct-actions")},
        {"panel": "grups", "highlight": _anchor("groups-selection-actions")},
    ),
    "groups_creation_strategies": (
        {"panel": "grups", "highlight": _anchor("groups-creation-strategies")},
        {"panel": "grups", "highlight": _anchor("groups-creation-strategies")},
        {"panel": "grups", "highlight": _anchor("groups-inspector")},
    ),
    "groups_buckets": (
        {"panel": "grups", "highlight": _anchor("groups-buckets")},
        {"panel": "grups", "highlight": _anchor("groups-buckets")},
        {"panel": "grups", "highlight": _anchor("groups-buckets")},
    ),
    "groups_board": (
        {"panel": "grups", "highlight": _anchor("groups-board")},
        {"panel": "grups", "highlight": _anchor("groups-board")},
        {"panel": "grups", "highlight": _anchor("groups-board")},
    ),
    "groups_order": (
        {"panel": "grups", "highlight": _anchor("groups-order-actions")},
        {"panel": "grups", "highlight": _anchor("groups-inspector")},
        {"panel": "grups", "highlight": _anchor("groups-order-actions")},
    ),
    "groups_inspector": (
        {"panel": "grups", "highlight": _anchor("groups-inspector")},
        {"panel": "grups", "highlight": _anchor("groups-inspector")},
        {"panel": "grups", "highlight": _anchor("groups-inspector")},
    ),
    "teams_workspace": (
        {"panel": "equips", "highlight": _anchor("teams-workspace")},
        {"panel": "equips", "highlight": _anchor("teams-context")},
        {"panel": "equips", "highlight": _anchors("teams-context", "teams-universe", "teams-selection-actions", "teams-board", "teams-inspector")},
    ),
    "teams_workspace_context": (
        {"panel": "equips", "highlight": _anchor("teams-context")},
        {"panel": "equips", "highlight": _anchor("teams-context")},
        {"panel": "equips", "highlight": _anchor("teams-context-details")},
        {"panel": "equips", "highlight": _anchor("teams-context")},
    ),
    "teams_context_sources": (
        {"panel": "equips", "highlight": _anchor("teams-context-sources")},
        {"panel": "equips", "highlight": _anchor("teams-context-sources")},
        {"panel": "equips", "highlight": _anchor("teams-context-sources")},
    ),
    "teams_universe": (
        {"panel": "equips", "highlight": _anchor("teams-universe")},
        {"panel": "equips", "highlight": _anchor("teams-universe")},
        {"panel": "equips", "highlight": _anchor("teams-universe")},
        {"panel": "equips", "highlight": _anchor("teams-universe")},
    ),
    "teams_selection_actions": (
        {"panel": "equips", "highlight": _anchor("teams-selection-actions")},
        {"panel": "equips", "highlight": _anchor("teams-direct-actions")},
        {"panel": "equips", "highlight": _anchor("teams-selection-actions")},
    ),
    "teams_creation_strategies": (
        {"panel": "equips", "highlight": _anchor("teams-creation-strategies")},
        {"panel": "equips", "highlight": _anchor("teams-creation-strategies")},
        {"panel": "equips", "highlight": _anchor("teams-inspector")},
    ),
    "teams_buckets": (
        {"panel": "equips", "highlight": _anchor("teams-buckets")},
        {"panel": "equips", "highlight": _anchor("teams-buckets")},
        {"panel": "equips", "highlight": _anchor("teams-buckets")},
        {"panel": "equips", "highlight": _anchor("teams-buckets")},
    ),
    "teams_board": (
        {"panel": "equips", "highlight": _anchor("teams-board")},
        {"panel": "equips", "highlight": _anchor("teams-board")},
        {"panel": "equips", "highlight": _anchor("teams-board")},
    ),
    "teams_destructive_actions": (
        {"panel": "equips", "highlight": _anchor("teams-destructive-actions")},
        {"panel": "equips", "highlight": _anchor("teams-destructive-actions")},
        {"panel": "equips", "highlight": _anchor("teams-destructive-actions")},
    ),
    "teams_inspector": (
        {"panel": "equips", "highlight": _anchor("teams-inspector")},
        {"panel": "equips", "highlight": _anchor("teams-inspector")},
        {"panel": "equips", "highlight": _anchor("teams-inspector")},
    ),
    "team_series_workspace": (
        {"panel": "series-equips", "highlight": _anchor("series-workspace")},
        {"panel": "series-equips", "highlight": _anchor("series-workspace")},
        {"panel": "series-equips", "highlight": _anchors("series-aparell", "series-universe", "series-actions", "series-board", "series-inspector")},
    ),
    "team_series_aparell": (
        {"panel": "series-equips", "highlight": _anchor("series-aparell")},
        {"panel": "series-equips", "highlight": _anchor("series-aparell")},
        {"panel": "series-equips", "highlight": _anchor("series-aparell")},
    ),
    "team_series_universe": (
        {"panel": "series-equips", "highlight": _anchor("series-universe")},
        {"panel": "series-equips", "highlight": _anchor("series-universe")},
        {"panel": "series-equips", "highlight": _anchor("series-universe")},
    ),
    "team_series_filters_selection": (
        {"panel": "series-equips", "highlight": _anchor("series-filters-selection")},
        {"panel": "series-equips", "highlight": _anchor("series-filters-selection")},
        {"panel": "series-equips", "highlight": _anchor("series-filters-selection")},
    ),
    "team_series_actions": (
        {"panel": "series-equips", "highlight": _anchor("series-actions")},
        {"panel": "series-equips", "highlight": _anchor("series-direct-actions")},
        {"panel": "series-equips", "highlight": _anchor("series-actions")},
    ),
    "team_series_creation_strategies": (
        {"panel": "series-equips", "highlight": _anchor("series-creation-strategies")},
        {"panel": "series-equips", "highlight": _anchor("series-creation-strategies")},
        {"panel": "series-equips", "highlight": _anchor("series-inspector")},
    ),
    "team_series_board": (
        {"panel": "series-equips", "highlight": _anchor("series-board")},
        {"panel": "series-equips", "highlight": _anchor("series-board")},
        {"panel": "series-equips", "highlight": _anchor("series-board")},
    ),
    "team_series_detail": (
        {"panel": "series-equips", "highlight": _anchor("series-inspector")},
        {"panel": "series-equips", "highlight": _anchor("series-inspector")},
        {"panel": "series-equips", "highlight": _anchor("series-inspector")},
    ),
    "team_series_preview": (
        {"panel": "series-equips", "highlight": _anchor("series-preview")},
        {"panel": "series-equips", "highlight": _anchor("series-preview")},
        {"panel": "series-equips", "highlight": _anchor("series-preview")},
    ),
    "multimedia_workspace": (
        {"panel": "media", "highlight": _anchor("media-workspace")},
        {"panel": "media", "highlight": _anchors("media-file-universe", "media-match-preview", "media-current-assignments")},
        {"panel": "media", "highlight": _anchor("media-workspace")},
    ),
    "multimedia_quick_match": (
        {"panel": "media", "highlight": _anchor("media-quick-match")},
        {"panel": "media", "highlight": _anchor("media-quick-match")},
        {"panel": "media", "highlight": _anchor("media-match-preview")},
    ),
    "multimedia_file_universe": (
        {"panel": "media", "highlight": _anchor("media-file-universe")},
        {"panel": "media", "highlight": _anchor("media-folder-loader")},
        {"panel": "media", "highlight": _anchor("media-folder-loader")},
    ),
    "multimedia_match_config": (
        {"panel": "media", "highlight": _anchor("media-match-config")},
        {"panel": "media", "highlight": _anchor("media-match-config")},
        {"panel": "media", "highlight": _anchor("media-match-config")},
        {"panel": "media", "highlight": _anchor("media-match-config")},
    ),
    "multimedia_match_preview": (
        {"panel": "media", "highlight": _anchor("media-match-preview")},
        {"panel": "media", "highlight": _anchor("media-match-preview")},
        {"panel": "media", "highlight": _anchor("media-match-preview")},
    ),
    "multimedia_apply_assignments": (
        {"panel": "media", "highlight": _anchor("media-folder-loader")},
        {"panel": "media", "highlight": _anchor("media-match-preview")},
        {"panel": "media", "highlight": _anchor("media-current-assignments")},
    ),
    "multimedia_current_assignments": (
        {"panel": "media", "highlight": _anchor("media-current-assignments")},
        {"panel": "media", "highlight": _anchor("media-current-assignments")},
        {"panel": "media", "highlight": _anchor("media-current-assignments")},
        {"panel": "media", "highlight": _anchor("media-detail")},
    ),
    "multimedia_assignment_actions": (
        {"panel": "media", "highlight": _anchor("media-assignment-actions")},
        {"panel": "media", "highlight": _anchor("media-assignment-actions")},
        {"panel": "media", "highlight": _anchor("media-assignment-actions")},
    ),
    "multimedia_detail": (
        {"panel": "media", "highlight": _anchor("media-detail")},
        {"panel": "media", "highlight": _anchor("media-detail")},
        {"panel": "media", "highlight": _anchor("media-detail")},
    ),
}


for topic_id, step_contexts in STEP_CONTEXTS.items():
    topic = AVATAR_MESSAGES.get(topic_id) or {}
    steps = topic.get("steps")
    if not isinstance(steps, list):
        continue
    for index, step_context in enumerate(step_contexts):
        if index >= len(steps) or not step_context or not isinstance(steps[index], dict):
            continue
        steps[index] = {
            **steps[index],
            **step_context,
        }


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
