EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


AVATAR_MESSAGES = {
    "multimedia_workspace": {
        "id": "multimedia_workspace",
        "title": "Gestor de multimedia",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Aquest gestor serveix per associar fitxers multimedia a les inscripcions de la competicio."
            },
            {
                "text": "Pots carregar una carpeta, calcular un match assistit, revisar la previsualitzacio i aplicar assignacions."
            },
            {
                "text": "El workspace es divideix en univers de fitxers, configuracio de match, previsualitzacio, assignacions actuals i detall."
            },
        ],
        "actions": [],
    },
    "multimedia_quick_match": {
        "id": "multimedia_quick_match",
        "title": "Match assistit rapid",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "La franja rapida permet carregar una carpeta i calcular una preview sense entrar encara en tot el detall del gestor."
            },
            {
                "text": "Els badges resumeixen quants fitxers hi ha i quants han quedat com Auto, Review o Sense match."
            },
            {
                "text": "La preview no aplica canvis per si sola: nomes prepara una revisio de possibles assignacions."
            },
        ],
        "actions": [],
    },
    "multimedia_file_universe": {
        "id": "multimedia_file_universe",
        "title": "Univers de fitxers",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "L'univers de fitxers es el punt on selecciones la carpeta local amb audios, videos o imatges."
            },
            {
                "text": "Amb Previsualitzar match, IA Score compara els noms dels fitxers amb les dades de les inscripcions."
            },
            {
                "text": "Refrescar workspace torna a carregar l'estat d'assignacions sense canviar la carpeta seleccionada."
            },
        ],
        "actions": [],
    },
    "multimedia_match_config": {
        "id": "multimedia_match_config",
        "title": "Configuracio de match",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "La configuracio de match decideix quins camps de la inscripcio pesen mes quan IA Score compara un fitxer amb una candidata."
            },
            {
                "text": "Els pesos de nom, categoria, subcategoria, entitat i sexe modulen quina informacio es considera mes rellevant."
            },
            {
                "text": "Els llindars Auto i Review separen els matches clars dels que convindria revisar manualment."
            },
            {
                "text": "El marge auto ajuda a evitar assignacions massa ajustades quan hi ha dues candidates semblants."
            },
        ],
        "actions": [],
    },
    "multimedia_match_preview": {
        "id": "multimedia_match_preview",
        "title": "Previsualitzacio de match",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "La previsualitzacio mostra les associacions proposades entre fitxers i inscripcions abans d'aplicar res."
            },
            {
                "text": "Pots filtrar per estat, confianca, marge, camp que ha fet match o si hi ha candidat detectat."
            },
            {
                "text": "Auto indica matches prou clars, Review indica casos que convindria mirar, i Sense match indica fitxers sense candidata fiable."
            },
        ],
        "actions": [],
    },
    "multimedia_apply_assignments": {
        "id": "multimedia_apply_assignments",
        "title": "Aplicar assignacions",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "warning",
        "steps": [
            {
                "text": "Aplicar assignacions confirma els matches seleccionats i vincula els fitxers a les inscripcions."
            },
            {
                "text": "Abans d'aplicar, revisa especialment els casos Review i Sense match per evitar assignacions incorrectes."
            },
            {
                "text": "Despres d'aplicar, pots revisar el resultat a Assignacions actuals i al Detall de cada inscripcio."
            },
        ],
        "actions": [],
    },
    "multimedia_current_assignments": {
        "id": "multimedia_current_assignments",
        "title": "Assignacions actuals",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Aquesta zona mostra l'estat multimedia de les inscripcions de la competicio."
            },
            {
                "text": "Treballa sobre l'univers global d'inscripcions, no nomes sobre els fitxers carregats a la preview."
            },
            {
                "text": "Pots cercar i filtrar per estat, origen, tipus de fitxer o ID d'inscripcio."
            },
            {
                "text": "Selecciona una assignacio del llistat per obrir-ne el detall lateral."
            },
        ],
        "actions": [],
    },
    "multimedia_assignment_actions": {
        "id": "multimedia_assignment_actions",
        "title": "Accions sobre fitxers assignats",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Cada fitxer assignat pot tenir accions com obrir-lo, marcar-lo com a principal, reassignar-lo o eliminar-lo."
            },
            {
                "text": "El fitxer principal es el recurs preferent quan una inscripcio te mes d'un fitxer associat."
            },
            {
                "text": "Reassignar mou el fitxer a una altra inscripcio. Eliminar treu l'assignacio i el fitxer associat segons la gestio del sistema."
            },
        ],
        "actions": [],
    },
    "multimedia_detail": {
        "id": "multimedia_detail",
        "title": "Detall multimedia",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "El detall mostra una inscripcio concreta i els fitxers multimedia que te vinculats."
            },
            {
                "text": "Des d'aqui pots pujar un fitxer manualment quan necessites completar o corregir una assignacio."
            },
            {
                "text": "Tambe pots revisar metadades, obrir el fitxer principal i refrescar el resultat despres de fer canvis."
            },
        ],
        "actions": [],
    },
}
