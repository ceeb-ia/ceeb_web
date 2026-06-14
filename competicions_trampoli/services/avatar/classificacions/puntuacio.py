EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


AVATAR_MESSAGES = {
    "classifications_scoring_general": {
        "id": "classifications_scoring_general",
        "title": "Puntuació",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "A Puntuació configures com IA Score transforma les notes introduïdes pels jutges en el resultat final d’una classificació.",
                "highlight": "[data-avatar-anchor='classifications-scoring-section']",
            },
            {
                "text": "És una de les seccions més importants, perquè permet crear classificacions molt diferents a partir de les mateixes notes de competició.",
                "highlight": "[data-avatar-anchor='classifications-scoring-section']",
            },
            {
                "text": "La secció es divideix en 3 grans blocs: Base i ordre, Configuració dels aparells i Resum del càlcul.",
                "highlight": "[data-avatar-anchor='classifications-scoring-flow']",
            },
        ],
        "actions": [],
    },
    "classifications_scoring_base_order": {
        "id": "classifications_scoring_base_order",
        "title": "Base i ordre",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "A Base i ordre defineixes el mètode de càlcul dels resultats i si els valors s’ordenen de manera ascendent o descendent.",
                "highlight": "[data-avatar-anchor='classifications-scoring-base-order']",
            },
            {
                "text": "El mètode Score calcula la classificació a partir de la puntuació resultant de combinar les notes introduïdes pels jutges.",
                "highlight": "[data-avatar-anchor='classifications-scoring-base-order']",
            },
            {
                "text": "El mètode Victòries compara els scores entre participants o unitats competitives i suma punts segons aquestes comparacions.",
                "highlight": "[data-avatar-anchor='classifications-scoring-victories']",
            },
        ],
        "actions": [],
    },
    "classifications_scoring_apparatus_phase": {
        "id": "classifications_scoring_apparatus_phase",
        "title": "Aparells i fase",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Després has d’escollir els aparells que formaran part de la classificació i quina fase es tindrà en compte per a cada aparell.",
                "highlight": "[data-avatar-anchor='classifications-scoring-apparatus-phase']",
            },
            {
                "text": "Pots seleccionar tants aparells com vulguis dins de la competició, però només una fase per cada aparell.",
                "highlight": "[data-avatar-anchor='classifications-scoring-apparatus-phase']",
            },
        ],
        "actions": [],
    },
    "classifications_scoring_flow": {
        "id": "classifications_scoring_flow",
        "title": "Flux del càlcul",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Finalment, has d’indicar com es tractaran les notes dels aparells: amb tractament individual per aparell o amb tractament conjunt.",
                "highlight": "[data-avatar-anchor='classifications-scoring-flow-mode']",
            },
            {
                "text": "Amb tractament individual per aparell, IA Score resol primer cada aparell per separat i després agrega els resultats dels aparells per obtenir la nota final.",
                "highlight": "[data-avatar-anchor='classifications-scoring-flow-mode']",
            },
            {
                "text": "Amb tractament conjunt, IA Score no diferencia de quin aparell ve cada nota a l’hora de calcular el resultat final.",
                "highlight": "[data-avatar-anchor='classifications-scoring-flow-mode']",
            },
        ],
        "actions": [],
    },
    "classifications_scoring_apparatus_config": {
        "id": "classifications_scoring_apparatus_config",
        "title": "Configuració dels aparells",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "A Configuració dels aparells és on defineixes exactament quines notes entren al càlcul i com es converteixen en el resultat final.",
                "highlight": "[data-avatar-anchor='classifications-scoring-apparatus-config']",
            },
            {
                "text": "La idea és resoldre la bossa de notes candidates de cada unitat competitiva i obtenir una puntuació comparable amb la resta.",
                "highlight": "[data-avatar-anchor='classifications-scoring-apparatus-config']",
            },
            {
                "text": "El primer pas és seleccionar els camps de puntuació que vols tenir en compte.",
                "highlight": "[data-avatar-anchor='classifications-scoring-apparatus-config']",
            },
            {
                "text": "Aquests camps són els que has configurat dins de l’aparell, com poden ser diferents notes, penalitzacions o valors puntuables.",
                "highlight": "[data-avatar-anchor='classifications-scoring-apparatus-config']",
            },
        ],
        "actions": [],
    },
    "classifications_scoring_fields": {
        "id": "classifications_scoring_fields",
        "title": "Camps i agregació",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Pots seleccionar un o diversos camps del llistat disponible.",
                "highlight": "[data-avatar-anchor='classifications-scoring-apparatus-config']",
            },
            {
                "text": "Si selecciones diversos camps, hauràs d’indicar com s’agreguen entre ells mitjançant l’agregació de camps.",
                "highlight": "[data-avatar-anchor='classifications-scoring-apparatus-config']",
            },
            {
                "text": "Per exemple, pots sumar diversos camps, fer-ne una mitjana o aplicar el criteri que correspongui segons la configuració de l’aparell.",
                "highlight": "[data-avatar-anchor='classifications-scoring-apparatus-config']",
            },
        ],
        "actions": [],
    },
    "classifications_scoring_exercises": {
        "id": "classifications_scoring_exercises",
        "title": "Exercicis",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Un cop seleccionats els camps, IA Score construeix la bossa de notes candidates sobre la qual treballarà la classificació.",
                "highlight": "[data-avatar-anchor='classifications-scoring-apparatus-config']",
            },
            {
                "text": "En classificacions individuals i natives d’equip, la bossa és directa: conté els exercicis de la unitat competitiva que s’està classificant.",
                "highlight": "[data-avatar-anchor='classifications-scoring-apparatus-config']",
            },
            {
                "text": "En aquests casos, només cal decidir quins exercicis compten, com se seleccionen i com s’agreguen per obtenir el resultat.",
                "highlight": "[data-avatar-anchor='classifications-scoring-shared-pool']",
            },
            {
                "text": "Per exemple, pots tenir en compte tots els exercicis, només els millors, només certs exercicis concrets o qualsevol altre criteri disponible.",
                "highlight": "[data-avatar-anchor='classifications-scoring-shared-pool']",
            },
        ],
        "actions": [],
    },
    "classifications_scoring_shared_pool": {
        "id": "classifications_scoring_shared_pool",
        "title": "Sac compartit",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Si el tractament és conjunt, IA Score ajunta les bosses dels aparells seleccionats i tracta totes les notes com un únic conjunt.",
                "highlight": "[data-avatar-anchor='classifications-scoring-shared-pool']",
            },
            {
                "text": "Després, aquestes notes seleccionades s’agreguen per obtenir la puntuació final de la inscripció o de l’equip.",
                "highlight": "[data-avatar-anchor='classifications-scoring-shared-pool']",
            },
        ],
        "actions": [],
    },
    "classifications_scoring_team_member_treatment": {
        "id": "classifications_scoring_team_member_treatment",
        "title": "Tractament de membres",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Quan la classificació és per equips derivada d’individual, IA Score mostra també el tractament de membres.",
                "highlight": "[data-avatar-anchor='classifications-scoring-flow-mode']",
            },
            {
                "text": "Aquest tractament defineix com es converteixen les notes individuals dels membres en una nota candidata per a l’equip.",
                "highlight": "[data-avatar-anchor='classifications-scoring-team-members']",
            },
            {
                "text": "En classificacions d’equips derivades d’individual, la bossa és més complexa perquè està formada per notes de diversos membres de l’equip.",
                "highlight": "[data-avatar-anchor='classifications-scoring-team-members']",
            },
            {
                "text": "En aquest cas, primer cal decidir com es tracten els membres: resolent-los individualment, posant totes les notes en una bossa comuna o separant-les per exercici.",
                "highlight": "[data-avatar-anchor='classifications-scoring-flow-mode']",
            },
        ],
        "actions": [],
    },
    "classifications_scoring_member_modes": {
        "id": "classifications_scoring_member_modes",
        "title": "Modes de membres",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "El mode Tractament per membre de l’equip resol primer cada membre per separat.",
                "highlight": "[data-avatar-anchor='classifications-scoring-flow-mode']",
            },
            {
                "text": "Això vol dir que IA Score calcula una nota per cada membre a partir dels seus propis exercicis, i després posa aquests resultats dins la bossa de l’equip.",
                "highlight": "[data-avatar-anchor='classifications-scoring-team-members']",
            },
            {
                "text": "Després, sobre aquesta bossa de resultats de membres, es fa la selecció i agregació final de l’equip.",
                "highlight": "[data-avatar-anchor='classifications-scoring-team-members']",
            },
            {
                "text": "A partir d’aquest tractament, IA Score genera la bossa final de l’equip i aplica la selecció i agregació configurades.",
                "highlight": "[data-avatar-anchor='classifications-scoring-team-members']",
            },
            {
                "text": "Així pots construir classificacions d’equip molt diferents: per suma de membres, millors contribucions, millors exercicis o altres combinacions.",
                "highlight": "[data-avatar-anchor='classifications-scoring-team-members']",
            },
        ],
        "actions": [],
    },
    "classifications_scoring_team_pool": {
        "id": "classifications_scoring_team_pool",
        "title": "Bosses d'equip",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "El mode Bossa d’equip amb totes les notes posa totes les notes individuals dels membres dins d’un mateix sac, sense separar primer per membre ni per exercici.",
                "highlight": "[data-avatar-anchor='classifications-scoring-flow-mode']",
            },
            {
                "text": "En aquest mode, totes les notes competeixen en igualtat de condicions per formar la nota de l’equip.",
                "highlight": "[data-avatar-anchor='classifications-scoring-shared-pool']",
            },
            {
                "text": "Aquest mode també pot limitar la contribució màxima de cada participant, per evitar que un sol membre aporti massa exercicis al resultat final.",
                "highlight": "[data-avatar-anchor='classifications-scoring-limits']",
            },
        ],
        "actions": [],
    },
    "classifications_scoring_team_pool_per_exercise": {
        "id": "classifications_scoring_team_pool_per_exercise",
        "title": "Bossa per exercicis",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "El mode Bossa d’equip per exercicis és útil quan vols donar un tractament específic a cada número d’exercici.",
                "highlight": "[data-avatar-anchor='classifications-scoring-flow-mode']",
            },
            {
                "text": "En aquest cas, IA Score agrupa tots els primers exercicis dels membres, tots els segons exercicis, i així successivament.",
                "highlight": "[data-avatar-anchor='classifications-scoring-flow-mode']",
            },
            {
                "text": "Cada bossa d’exercici es resol per separat, i després els resultats resolts passen a una bossa comuna per fer la selecció i agregació final de l’equip.",
                "highlight": "[data-avatar-anchor='classifications-scoring-shared-pool']",
            },
        ],
        "actions": [],
    },
    "classifications_scoring_multiple_apparatus": {
        "id": "classifications_scoring_multiple_apparatus",
        "title": "Diversos aparells",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Quan una classificació utilitza diversos aparells, IA Score aplica la configuració segons el tractament d’aparells que hagis escollit.",
                "highlight": "[data-avatar-anchor='classifications-scoring-flow-mode']",
            },
            {
                "text": "Amb tractament individual per aparell, cada aparell es resol per separat.",
                "highlight": "[data-avatar-anchor='classifications-scoring-apparatus-config']",
            },
            {
                "text": "Aquest mode és útil quan vols conservar la identitat de cada aparell fins al final del càlcul.",
                "highlight": "[data-avatar-anchor='classifications-scoring-final-apps']",
            },
            {
                "text": "Això vol dir que IA Score selecciona i agrega les notes dins de cada aparell, obté un resultat per aparell i després fa una última selecció i agregació entre aparells.",
                "highlight": "[data-avatar-anchor='classifications-scoring-final-apps']",
            },
        ],
        "actions": [],
    },
    "classifications_scoring_global_apparatus_pool": {
        "id": "classifications_scoring_global_apparatus_pool",
        "title": "Aparells en sac global",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Amb tractament conjunt, les notes dels aparells seleccionats es posen en una bossa global.",
                "highlight": "[data-avatar-anchor='classifications-scoring-shared-pool']",
            },
            {
                "text": "En aquest cas, IA Score no diferencia si una nota ve d’un aparell o d’un altre: totes les notes entren al càlcul en igualtat de condicions.",
                "highlight": "[data-avatar-anchor='classifications-scoring-shared-pool']",
            },
        ],
        "actions": [],
    },
    "classifications_scoring_team_multiple_apparatus": {
        "id": "classifications_scoring_team_multiple_apparatus",
        "title": "Equips amb diversos aparells",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Si la classificació és d’equips derivada d’individual, els modes de tractament de membres continuen existint.",
                "highlight": "[data-avatar-anchor='classifications-scoring-flow-mode']",
            },
            {
                "text": "La diferència és que els membres es poden resoldre considerant els exercicis de tots els aparells seleccionats.",
                "highlight": "[data-avatar-anchor='classifications-scoring-flow-mode']",
            },
            {
                "text": "En el mode Bossa d’equip amb totes les notes, la bossa pot incloure notes individuals de tots els membres i de tots els aparells.",
                "highlight": "[data-avatar-anchor='classifications-scoring-shared-pool']",
            },
            {
                "text": "En el mode Bossa d’equip per exercicis, IA Score resol les bosses d’exercici pròpies de cada aparell abans de portar els resultats al sac comú final.",
                "highlight": "[data-avatar-anchor='classifications-scoring-shared-pool']",
            },
            {
                "text": "Per això és important revisar el Resum del càlcul: t’ajuda a comprovar si els aparells s’estan tractant per separat o com una única bossa global.",
                "highlight": "[data-avatar-anchor='classifications-scoring-summary']",
            },
        ],
        "actions": [],
    },
    "classifications_scoring_summary": {
        "id": "classifications_scoring_summary",
        "title": "Resum del càlcul",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Una manera senzilla d’entendre-ho és imaginar cada aparell com una bossa de notes.",
                "highlight": "[data-avatar-anchor='classifications-scoring-summary']",
            },
            {
                "text": "En una classificació individual, cada aparell aporta una bossa amb les notes individuals de cada inscripció dins de la fase seleccionada.",
                "highlight": "[data-avatar-anchor='classifications-scoring-summary']",
            },
            {
                "text": "En una classificació d’equips derivada d’individual, cada aparell aporta una bossa amb les notes individuals dels membres de l’equip.",
                "highlight": "[data-avatar-anchor='classifications-scoring-summary']",
            },
            {
                "text": "En una classificació nativa d’equip, cada aparell d’equip aporta una bossa amb les notes de l’equip com a unitat competitiva.",
                "highlight": "[data-avatar-anchor='classifications-scoring-summary']",
            },
            {
                "text": "El Resum del càlcul et permet revisar la configuració final i comprovar com IA Score interpretarà la classificació abans de generar els resultats.",
                "highlight": "[data-avatar-anchor='classifications-scoring-summary']",
            },
        ],
        "actions": [],
    },
    "classifications_scoring_victories": {
        "id": "classifications_scoring_victories",
        "title": "Victòries",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "El mètode Victòries compara els scores entre participants o unitats competitives i suma punts segons aquestes comparacions.",
                "highlight": "[data-avatar-anchor='classifications-scoring-victories']",
            },
            {
                "text": "Aquesta configuració defineix si els duels es calculen sobre camps o exercicis agregats o separats.",
                "highlight": "[data-avatar-anchor='classifications-scoring-victories']",
            },
            {
                "text": "El desempat intern només s'aplica en mode Victòries i resol empats dins de cada duel d'un mateix aparell.",
                "highlight": "[data-avatar-anchor='classifications-scoring-victory-tie']",
            },
        ],
        "actions": [],
    },
}
