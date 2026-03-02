GLOBAL_AUTH_GROUPS = {
    "platform_admin": "Administracio global de la plataforma",
    "competicions_manager": "Gestio global del modul de competicions",
    "designacions_manager": "Gestio global del modul de designacions",
    "informes_manager": "Gestio global del modul d'informes",
    "calendar_manager": "Gestio global del calendari intern",
    "readonly_backoffice": "Acces de lectura al backoffice",
}


def global_auth_group_names():
    return tuple(GLOBAL_AUTH_GROUPS.keys())
