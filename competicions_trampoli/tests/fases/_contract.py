from importlib import import_module

from django.apps import apps


PHASE_MODEL_NAME = "CompeticioAparellFase"
DEFAULT_PHASE_HELPER_NAME = "ensure_default_phase_for_comp_aparell"


def get_phase_model():
    try:
        return apps.get_model("competicions_trampoli", PHASE_MODEL_NAME)
    except LookupError as exc:
        raise AssertionError(
            "Fase 2 must register model competicions_trampoli.CompeticioAparellFase"
        ) from exc


def get_default_phase_helper():
    candidate_modules = (
        "competicions_trampoli.services.fases",
        "competicions_trampoli.services.fases.default_phase",
        "competicions_trampoli.services.fases.lifecycle",
    )
    for module_path in candidate_modules:
        try:
            module = import_module(module_path)
        except ModuleNotFoundError:
            continue
        helper = getattr(module, DEFAULT_PHASE_HELPER_NAME, None)
        if helper is not None:
            return helper
    raise AssertionError(
        "Fase 2 must expose ensure_default_phase_for_comp_aparell from "
        "competicions_trampoli.services.fases or a dedicated submodule."
    )
