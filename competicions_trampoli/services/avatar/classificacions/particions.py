EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


AVATAR_MESSAGES = {
    "classifications_partitions": {
        "id": "classifications_partitions",
        "title": "Particions",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "A Particions configures com es divideix una classificació en blocs més petits.",
                "highlight": "[data-avatar-anchor='classifications-partitions-section']",
            },
            {
                "text": "Això serveix, per exemple, per generar una classificació separada per cada categoria sense haver de crear-les manualment una per una.",
                "highlight": "[data-avatar-anchor='classifications-partitions-fields']",
            },
            {
                "text": "En lloc de duplicar configuracions, IA Score parteix d’una sola classificació i crea automàticament les sub-classificacions segons les particions que defineixis.",
                "highlight": "[data-avatar-anchor='classifications-partitions-section']",
            },
        ],
        "actions": [],
    },
    "classifications_partitions_fields": {
        "id": "classifications_partitions_fields",
        "title": "Camps de partició",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Els camps de partició poden venir de les columnes importades de l’Excel o de camps natius del sistema.",
                "highlight": "[data-avatar-anchor='classifications-partitions-fields']",
            },
            {
                "text": "IA Score llegeix totes les inscripcions i, segons els camps escollits com a particions, crea blocs amb els diferents valors trobats.",
                "highlight": "[data-avatar-anchor='classifications-partitions-fields']",
            },
            {
                "text": "Més endavant, podràs filtrar quines inscripcions vols que es considerin en cas de voler excloure’n per aquesta classificació.",
                "highlight": "[data-avatar-anchor='classifications-partitions-fields']",
            },
            {
                "text": "Per exemple, si particiones pel camp Categoria, el sistema pot crear blocs com Aleví, Infantil, Cadet o Sènior, segons les dades existents.",
                "highlight": "[data-avatar-anchor='classifications-partitions-fields']",
            },
        ],
        "actions": [],
    },
    "classifications_partitions_order": {
        "id": "classifications_partitions_order",
        "title": "Ordre i jerarquia",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "L’ordre de les particions defineix la jerarquia de la classificació.",
                "highlight": "[data-avatar-anchor='classifications-partitions-fields']",
            },
            {
                "text": "Per exemple, pots indicar que primer es divideixi per Categoria i després per Entitat, Subcategoria o qualsevol altre camp disponible.",
                "highlight": "[data-avatar-anchor='classifications-partitions-fields']",
            },
            {
                "text": "Quan afegeixes diversos nivells de partició, els nivells fills poden aplicar-se a totes les particions anteriors o només a alguns valors concrets.",
                "highlight": "[data-avatar-anchor='classifications-partitions-custom']",
            },
            {
                "text": "Per exemple, pots fer que una classificació per Subcategoria només s’apliqui a Aleví i Infantil, però no a la resta de categories.",
                "highlight": "[data-avatar-anchor='classifications-partitions-custom']",
            },
        ],
        "actions": [],
    },
    "classifications_partitions_custom": {
        "id": "classifications_partitions_custom",
        "title": "Partició personalitzada",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "També pots crear particions personalitzades quan vulguis agrupar diversos valors dins d’un mateix bloc.",
                "highlight": "[data-avatar-anchor='classifications-partitions-custom']",
            },
            {
                "text": "Això és útil si, per exemple, vols que Infantil i Cadet competeixin dins de la mateixa classificació.",
                "highlight": "[data-avatar-anchor='classifications-partitions-custom']",
            },
            {
                "text": "Per fer-ho, pots activar la partició personalitzada i crear grups de partició amb els valors que vols tractar com un únic bloc.",
                "highlight": "[data-avatar-anchor='classifications-partitions-custom']",
            },
            {
                "text": "Així pots construir classificacions molt flexibles mantenint una sola configuració principal.",
                "highlight": "[data-avatar-anchor='classifications-partitions-custom']",
            },
        ],
        "actions": [],
    },
    "classifications_partitions_teams": {
        "id": "classifications_partitions_teams",
        "title": "Particions d'equips",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Quan la classificació treballa per equips, aquest bloc afegeix opcions específiques de partició i visualització d’equips.",
                "highlight": "[data-avatar-anchor='classifications-partitions-teams']",
            },
            {
                "text": "Pots incloure participants sense equip si vols que no quedin fora d’aquesta classificació d’equips.",
                "highlight": "[data-avatar-anchor='classifications-partitions-teams']",
            },
            {
                "text": "També pots crear particions manuals d’equips per agrupar equips dins de blocs definits per tu.",
                "highlight": "[data-avatar-anchor='classifications-partitions-teams']",
            },
        ],
        "actions": [],
    },
}
