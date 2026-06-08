EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


AVATAR_MESSAGES = {
    "teams_workspace": {
        "id": "teams_workspace",
        "title": "Gestor d'equips",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Aquest gestor serveix per crear i revisar equips a partir de les inscripcions de la competicio."
            },
            {
                "text": "Els equips sempre viuen dins d'un context. El context decideix per a que serveixen aquells equips i quines inscripcions poden formar-ne part."
            },
            {
                "text": "El workspace es divideix en zones: context, univers de candidates, accions sobre la seleccio, equips actuals i inspector lateral."
            },
        ],
        "actions": [],
    },
    "teams_workspace_context": {
        "id": "teams_workspace_context",
        "title": "Context d'equips",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Un context es l'espai on IA Score interpreta quins equips existeixen i per a que serveixen dins de la competicio."
            },
            {
                "text": "Dins d'un mateix context, una inscripcio nomes pot formar part d'un equip. Aixo evita contradiccions quan es calculen resultats o participacions."
            },
            {
                "text": "Si una mateixa inscripcio ha de formar part d'equips diferents, crea contextos diferents."
            },
            {
                "text": "Un context pot servir per agrupar resultats individuals o per fer que un conjunt d'inscripcions competeixi com una sola unitat."
            },
        ],
        "actions": [],
    },
    "teams_context_sources": {
        "id": "teams_context_sources",
        "title": "Aparells d'equip del context",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Aquesta zona indica en quins aparells d'equip el context actua com a unitat competitiva."
            },
            {
                "text": "Quan un aparell queda vinculat al context, IA Score pot tractar l'equip com el participant real d'aquell aparell."
            },
            {
                "text": "Desa els aparells del context quan vulguis que aquesta configuracio quedi disponible per a la resta del flux competitiu."
            },
        ],
        "actions": [],
    },
    "teams_universe": {
        "id": "teams_universe",
        "title": "Univers de candidates",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "L'univers mostra les inscripcions disponibles per preparar equips dins del context actiu."
            },
            {
                "text": "Pots cercar per nom, document o entitat i combinar filtres com categoria, subcategoria, entitat, estat o equip actual."
            },
            {
                "text": "El filtre d'estat diferencia les inscripcions que ja tenen equip en aquest context de les que encara no en tenen."
            },
            {
                "text": "Amb Afegir passes les inscripcions filtrades a la seleccio activa. Amb Netejar buides aquesta seleccio."
            },
        ],
        "actions": [],
    },
    "teams_selection_actions": {
        "id": "teams_selection_actions",
        "title": "Accions sobre la seleccio",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "La seleccio activa es el conjunt d'inscripcions sobre el qual treballen les accions d'aquesta zona."
            },
            {
                "text": "Pots crear un equip nou, assignar la seleccio a un equip existent o deixar-la sense equip dins del context actual."
            },
            {
                "text": "Eliminar equip buit nomes te sentit quan l'equip seleccionat no te membres."
            },
        ],
        "actions": [],
    },
    "teams_creation_strategies": {
        "id": "teams_creation_strategies",
        "title": "Estrategies de creacio",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Les estrategies creen equips a partir de la seleccio activa sense haver de repartir les inscripcions manualment."
            },
            {
                "text": "Pots crear un nombre concret d'equips, equips d'una mida determinada o equips equilibrats dins d'una forquilla."
            },
            {
                "text": "Previsualitza abans de crear per revisar com quedaria el repartiment en el context actiu."
            },
        ],
        "actions": [],
    },
    "teams_buckets": {
        "id": "teams_buckets",
        "title": "Creacio per buckets",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Els buckets divideixen la seleccio activa en blocs segons els camps que triis."
            },
            {
                "text": "Cada combinacio diferent de valors genera un bucket proposat, util quan les dades ja porten divisions o torns."
            },
            {
                "text": "Pots activar buckets, substituir la seleccio, previsualitzar el resultat o crear equips directament per bucket."
            },
            {
                "text": "L'opcio Reassignar equips existents permet que la creacio actualitzi assignacions previes del context."
            },
        ],
        "actions": [],
    },
    "teams_board": {
        "id": "teams_board",
        "title": "Equips actuals",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Aquesta zona mostra els equips que existeixen dins del context actiu."
            },
            {
                "text": "Pots cercar i filtrar per localitzar equips per nom, participants, entitat, categoria, subcategoria o estat."
            },
            {
                "text": "Els equips amb membres i els equips buits es mostren separats per facilitar la revisio i la neteja."
            },
        ],
        "actions": [],
    },
    "teams_destructive_actions": {
        "id": "teams_destructive_actions",
        "title": "Eliminacio d'equips",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "warning",
        "steps": [
            {
                "text": "Aquest menu agrupa accions de neteja del context actiu."
            },
            {
                "text": "Eliminar equips buits nomes treu equips sense membres."
            },
            {
                "text": "Eliminar tots els equips es una accio mes forta: buida els equips del context i cal usar-la nomes quan vols reconstruir-los."
            },
        ],
        "actions": [],
    },
    "teams_inspector": {
        "id": "teams_inspector",
        "title": "Inspector lateral",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "L'inspector mostra el detall de l'equip seleccionat sense perdre la vista general del board."
            },
            {
                "text": "Al detall pots revisar membres, filtrar-los i aplicar accions d'edicio segons el context."
            },
            {
                "text": "La pestanya Previsualitzacio mostra el resultat d'una estrategia o accio abans de confirmar-la."
            },
        ],
        "actions": [],
    },
}
