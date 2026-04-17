from .base import TieContractBase


class PerMemberTieContract(TieContractBase):
    name = "per_member"
    removed_pipeline_keys = ()


PER_MEMBER_TIE_CONTRACT = PerMemberTieContract()
