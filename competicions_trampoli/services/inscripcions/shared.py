import copy
import json


INSCRIPCIONS_SORT_STACK_SESSION_KEY = "inscripcions_sort_stack_v2"
INSCRIPCIONS_HISTORY_SESSION_KEY = "inscripcions_history_v2"
INSCRIPCIONS_HISTORY_DEPTH = 20


def json_clone(value):
    try:
        return json.loads(json.dumps(value))
    except Exception:
        return copy.deepcopy(value)
