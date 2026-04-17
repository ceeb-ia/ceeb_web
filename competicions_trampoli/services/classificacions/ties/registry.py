from .context import TIE_CONTRACT_PER_MEMBER, TIE_CONTRACT_TEAM_POOL
from .contracts.per_member import PER_MEMBER_TIE_CONTRACT
from .contracts.team_pool import TEAM_POOL_TIE_CONTRACT


CONTRACTS = {
    TIE_CONTRACT_PER_MEMBER: PER_MEMBER_TIE_CONTRACT,
    TIE_CONTRACT_TEAM_POOL: TEAM_POOL_TIE_CONTRACT,
}


def get_tie_contract(contract_name):
    name = str(contract_name or "").strip().lower() or TIE_CONTRACT_PER_MEMBER
    return CONTRACTS.get(name, PER_MEMBER_TIE_CONTRACT)


def resolve_tie_contract(context):
    return get_tie_contract(getattr(context, "contract_name", None))
