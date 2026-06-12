from .base import TieContractBase


class TeamPoolTieContract(TieContractBase):
    name = "team_pool"
    removed_pipeline_keys = (
        "participants",
        "agregacio_participants",
    )


TEAM_POOL_TIE_CONTRACT = TeamPoolTieContract()
