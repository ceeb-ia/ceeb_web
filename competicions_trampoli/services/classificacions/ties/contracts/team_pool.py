from .base import TieContractBase


class TeamPoolTieContract(TieContractBase):
    name = "team_pool"
    removed_pipeline_keys = (
        "exercicis",
        "mode_seleccio_exercicis",
        "exercicis_per_aparell",
        "agregacio_exercicis_per_aparell",
        "agregacio_exercicis",
        "participants",
        "agregacio_participants",
    )


TEAM_POOL_TIE_CONTRACT = TeamPoolTieContract()
