from .overview import EXPLAINING_AVATARS


AVATAR_MESSAGES = {
    "judge_support_overview": {
        "id": "judge_support_overview",
        "title": "Suport de jutges",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {
                "text": "Suport de jutges és el canal directe entre cada jutge i la taula d'organització durant el directe de la competició.",
                "highlight": "[data-avatar-anchor='judge-support-header']",
                "actions": [
                    {
                        "label": "Tornar a notes",
                        "action": "navigate",
                        "selector": "[data-avatar-action='judge-support-back-notes']",
                    },
                    {
                        "label": "Administrador QRs",
                        "action": "navigate",
                        "selector": "[data-avatar-action='judge-support-open-qr-admin']",
                    },
                ],
            },
            {
                "text": "Aquest espai serveix per gestionar incidències, dubtes o avisos que puguin aparèixer mentre els jutges estan puntuant.",
                "highlight": "[data-avatar-anchor='judge-support-overview']",
            },
            {
                "text": "Els jutges poden obrir aquest canal des del botó SOS del seu portal i iniciar un xat amb la taula d'organització.",
                "highlight": "[data-avatar-anchor='judge-support-sos']",
            },
            {
                "text": "Des de la pantalla d'organització pots veure tots els jutges habilitats i obrir una conversa directa amb qualsevol d'ells.",
                "highlight": "[data-avatar-anchor='judge-support-judge-list']",
            },
            {
                "text": "Cada conversa permet coordinar ràpidament qualsevol assumpte relacionat amb el directe, com una incidència tècnica, un dubte de puntuació o una revisió puntual.",
                "highlight": "[data-avatar-anchor='judge-support-chat']",
            },
            {
                "text": "Quan una petició ja està solucionada, la pots marcar com a resolta per mantenir el suport ordenat i saber què queda pendent.",
                "highlight": "[data-avatar-anchor='judge-support-resolve']",
            },
        ],
        "actions": [],
    },
}
