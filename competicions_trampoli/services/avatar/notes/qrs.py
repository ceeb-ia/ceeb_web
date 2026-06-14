from .overview import EXPLAINING_AVATARS


AVATAR_MESSAGES = {
    "qr_admin_create_panel": {
        "id": "qr_admin_create_panel",
        "title": "Crear QRs",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Aquest panell serveix per crear nous accessos a la competició.",
                "highlight": "[data-avatar-anchor='qr-admin-create-panel']",
            },
            {
                "text": "Pots crear QRs de tipus jutge, pensats perquè els jutges introdueixin puntuacions, o QRs de tipus públic, pensats per consultar classificacions habilitades.",
                "highlight": "[data-avatar-anchor='qr-admin-create-type']",
            },
            {
                "text": "Per crear un QR només cal escollir el tipus, donar-li un nom clar i generar-lo.",
                "highlight": "[data-avatar-anchor='qr-admin-create-form']",
            },
            {
                "text": "Un bon nom t'ajudarà a identificar ràpidament per a què serveix aquell accés, sobretot si hi ha molts jutges, aparells o classificacions actives.",
                "highlight": "[data-avatar-anchor='qr-admin-create-name']",
            },
        ],
        "actions": [],
    },

    "qr_admin_existing_list": {
        "id": "qr_admin_existing_list",
        "title": "QRs existents",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Aquest llistat mostra tots els QRs creats per a la competició.",
                "highlight": "[data-avatar-anchor='qr-admin-list']",
            },
            {
                "text": "Aquí pots veure quins accessos estan actius i quins estan inactius.",
                "highlight": "[data-avatar-anchor='qr-admin-list-status']",
            },
            {
                "text": "Selecciona un QR del llistat per consultar-ne el detall i gestionar-ne els permisos o les accions disponibles.",
                "highlight": "[data-avatar-anchor='qr-admin-list-item']",
                "actions": [
                    {
                        "label": "Seleccionar QR",
                        "action": "navigate",
                        "selector": "[data-avatar-action='qr-admin-select-token']",
                    },
                ],
            },
            {
                "text": "No oblidis revocar els accés quan ja no siguin necessaris.",
            }
        ],
        "actions": [],
    },

    "qr_admin_detail": {
        "id": "qr_admin_detail",
        "title": "Detall del QR",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "El detall del QR concentra totes les accions relacionades amb l'accés seleccionat.",
                "highlight": "[data-avatar-anchor='qr-admin-detail']",
                "actions": [
                    {
                        "label": "Tornar a notes",
                        "action": "navigate",
                        "selector": "[data-avatar-action='qr-admin-back-notes']",
                    },
                    {
                        "label": "Suport jutges",
                        "action": "navigate",
                        "selector": "[data-avatar-action='qr-admin-open-support']",
                    },
                    {
                        "label": "Imprimir QRs",
                        "action": "navigate",
                        "selector": "[data-avatar-action='qr-admin-print-qrs']",
                    },
                ],
            },
            {
                "text": "Si és un QR de jutge, aquí pots configurar quins permisos tindrà: aparell, fase, camps de puntuació i número de jutge.",
                "highlight": "[data-avatar-anchor='qr-admin-judge-accesses']",
            },
            {
                "text": "També pots obrir el portal per comprovar què veurà el jutge, mostrar el QR perquè es pugui escanejar o revocar permisos quan ja no siguin necessaris.",
                "highlight": "[data-avatar-anchor='qr-admin-detail-actions']",
                "actions": [
                    {
                        "label": "Obrir portal",
                        "action": "navigate",
                        "selector": "[data-avatar-action='qr-admin-open-portal']",
                    },
                    {
                        "label": "Veure QR",
                        "action": "navigate",
                        "selector": "[data-avatar-action='qr-admin-open-qr']",
                    },
                ],
            },
            {
                "text": "Si és un QR públic, el detall et permet revisar l'accés que es farà servir per visualitzar les classificacions habilitades.",
                "highlight": "[data-avatar-anchor='qr-admin-public-detail']",
                "actions": [
                    {
                        "label": "Obrir public",
                        "action": "navigate",
                        "selector": "[data-avatar-action='qr-admin-open-public-live']",
                    },
                    {
                        "label": "Loop",
                        "action": "navigate",
                        "selector": "[data-avatar-action='qr-admin-open-public-loop']",
                    },
                    {
                        "label": "Veure QR",
                        "action": "navigate",
                        "selector": "[data-avatar-action='qr-admin-open-public-qr']",
                    },
                ],
            },
        ],
        "actions": [],
    },

    "qr_admin_judge_access": {
        "id": "qr_admin_judge_access",
        "title": "Afegir accés de jutge",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "L'apartat Afegir accés de jutge serveix per definir exactament què podrà puntuar un jutge des del seu portal.",
                "highlight": "[data-avatar-anchor='qr-admin-add-judge-access']",
            },
            {
                "text": "Primer cal escollir l'aparell i la fase on aquest jutge podrà introduir notes.",
                "highlight": "[data-avatar-anchor='qr-admin-access-apparatus-phase']",
            },
            {
                "text": "Després pots seleccionar els camps de puntuació que vols habilitar per a aquest jutge.",
                "highlight": "[data-avatar-anchor='qr-admin-access-fields']",
            },
            {
                "text": "El número de jutge ha de ser coherent amb la configuració de puntuació de l'aparell. No es poden assignar més jutges dels que l'aparell té configurats.",
                "highlight": "[data-avatar-anchor='qr-admin-access-judge-number']",
            },
            {
                "text": "Si un camp té més d'un ítem, pots limitar quins ítems puntuarà el jutge indicant un inici i una quantitat.",
                "highlight": "[data-avatar-anchor='qr-admin-access-items-limit']",
            },
            {
                "text": "Aquesta limitació és útil quan vols repartir un mateix camp entre diversos jutges o quan només cal que un jutge valori una part concreta de l'exercici.",
                "highlight": "[data-avatar-anchor='qr-admin-access-items-limit']",
            },
        ],
        "actions": [],
    },

    "qr_admin_judge_actions": {
        "id": "qr_admin_judge_actions",
        "title": "Accions del jutge",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Un cop configurat l'accés, pots obrir el portal del jutge per comprovar què veurà abans de començar la competició.",
                "highlight": "[data-avatar-anchor='qr-admin-open-portal']",
                "actions": [
                    {
                        "label": "Obrir portal",
                        "action": "navigate",
                        "selector": "[data-avatar-action='qr-admin-open-portal']",
                    },
                ],
            },
            {
                "text": "També pots mostrar el QR perquè el jutge l'escanegi des del seu dispositiu.",
                "highlight": "[data-avatar-anchor='qr-admin-open-qr']",
                "actions": [
                    {
                        "label": "Veure QR",
                        "action": "navigate",
                        "selector": "[data-avatar-action='qr-admin-open-qr']",
                    },
                ],
            },
            {
                "text": "Si un accés ja no s'ha d'utilitzar, pots revocar-ne el permís per evitar que continuï disponible.",
                "highlight": "[data-avatar-anchor='qr-admin-revoke-access']",
            },
            {
                "text": "Abans del directe, és recomanable obrir el portal i validar que cada jutge només veu els camps i exercicis que li corresponen.",
                "highlight": "[data-avatar-anchor='qr-admin-open-portal']",
                "actions": [
                    {
                        "label": "Obrir portal",
                        "action": "navigate",
                        "selector": "[data-avatar-action='qr-admin-open-portal']",
                    },
                ],
            },
        ],
        "actions": [],
    },

    "qr_admin_print_qrs": {
        "id": "qr_admin_print_qrs",
        "title": "Imprimir QRs",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "El botó d'imprimir QRs et permet preparar tots els accessos de la competició en format imprimible.",
                "highlight": "[data-avatar-anchor='qr-admin-print-qrs']",
                "actions": [
                    {
                        "label": "Imprimir QRs",
                        "action": "navigate",
                        "selector": "[data-avatar-action='qr-admin-print-qrs']",
                    },
                ],
            },
            {
                "text": "Això és útil per repartir els codis als jutges, deixar-los preparats a la taula de competició o tenir-los com a còpia de seguretat.",
                "highlight": "[data-avatar-anchor='qr-admin-print-qrs']",
                "actions": [
                    {
                        "label": "Imprimir QRs",
                        "action": "navigate",
                        "selector": "[data-avatar-action='qr-admin-print-qrs']",
                    },
                ],
            },
        ],
        "actions": [],
    },
}
