EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


AVATAR_MESSAGES = {
    "groups_workspace": {
        "id": "groups_workspace",
        "title": "Gestor de grups",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Aquest gestor serveix per organitzar les inscripcions de la competició en grups de treball."
            },
            {
                "text": "Els grups preparen la base de l'organització competitiva: després, a 'Rotacions', ajuden a decidir qui competeix, quan competeix i en quin aparell."
            },
            {
                "text": "Una inscripció nomes pot formar part d'un grup. Si no participa en un aparell concret, simplement no apareixera quan aquell grup estigui programat en aquell aparell."
            },
            {
                "text": "El gestor es divideix en 4 zones: univers de candidates, accions sobre la seleccio, grups actuals i inspector lateral."
            },
        ],
        "actions": [],
    },
    "groups_universe": {
        "id": "groups_universe",
        "title": "Univers de candidates",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "L'univers mostra les inscripcions disponibles per preparar grups."
            },
            {
                "text": "Pots cercar per nom, document o entitat i combinar filtres com categoria, subcategoria, entitat, estat o grup actual."
            },
            {
                "text": "Amb Afegir passes les inscripcions filtrades a la selecció activa. Amb Netejar buides aquesta seleccio."
            },
        ],
        "actions": [],
    },
    "groups_selection_actions": {
        "id": "groups_selection_actions",
        "title": "Accions sobre la seleccio",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "La selecció activa es el conjunt d'inscripcions sobre el qual treballen les accions d'aquesta zona."
            },
            {
                "text": "Pots crear un grup nou amb la selecció, enviar-la a un grup existent o deixar-la sense grup."
            },
            {
                "text": "Tingues en compte que grups ja programats a 'Rotacions' no poden eliminarse, tot i que sí es poden modificar."
            },
        ],
        "actions": [],
    },
    "groups_creation_strategies": {
        "id": "groups_creation_strategies",
        "title": "Estratègies de creació",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Les estratègies creen grups a partir de la selecció activa sense haver de repartir les inscripcions manualment."
            },
            {
                "text": "Pots crear un nombre concret de grups, grups d'una mida determinada o grups equilibrats dins d'una forquilla."
            },
            {
                "text": "Previsualitza abans de crear per revisar com quedaria el repartiment."
            },
        ],
        "actions": [],
    },
    "groups_buckets": {
        "id": "groups_buckets",
        "title": "Creació per buckets",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Els 'buckets' divideixen les inscripcions en blocs segons valors de camps disponibles, com columnes importades de l'Excel."
            },
            {
                "text": "Cada combinació diferent de valors genera un bloc proposat. Aixè és útil quan les dades ja porten torns, categories o altres particions."
            },
            {
                "text": "Pots substituir la seleccio amb els buckets triats, previsualitzar-los o crear grups directament per bloc."
            },
        ],
        "actions": [],
    },
    "groups_board": {
        "id": "groups_board",
        "title": "Grups actuals",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Aquesta zona mostra els grups que ja existeixen a la competicio."
            },
            {
                "text": "Pots cercar i filtrar per localitzar grups per nom, participants, entitat, mida, estat o programa."
            },
            {
                "text": "Els grups amb participants i els grups buits es mostren separats perque puguis revisar-los i netejar els que ja no necessites."
            },
        ],
        "actions": [],
    },
    "groups_order": {
        "id": "groups_order",
        "title": "Ordre de competicio",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Cada grup pot tenir un ordre intern de competicio per als seus participants."
            },
            {
                "text": "Aquest ordre serveix de base quan mes endavant programes la competicio a Rotacions."
            },
            {
                "text": "Si veus un avis d'ordre no desat, vol dir que l'ordre que estas veient no coincideix amb l'ordre guardat per IA Score."
            },
        ],
        "actions": [],
    },
    "groups_inspector": {
        "id": "groups_inspector",
        "title": "Inspector lateral",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "L'inspector mostra el detall del grup seleccionat sense perdre la vista general del board."
            },
            {
                "text": "Al detall pots revisar els membres, filtrar-los i aplicar accions d'edicio segons el que necessitis."
            },
            {
                "text": "La pestanya Previsualitzacio mostra el resultat d'una accio abans de confirmar-la."
            },
        ],
        "actions": [],
    },
}
