from __future__ import annotations

import json
import os
import random
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from ...models import (
    Aparell,
    Competicio,
    CompeticioAparell,
    CompeticioMembership,
    Equip,
    EquipContext,
    GrupCompeticio,
    Inscripcio,
    InscripcioAparellExclusio,
    InscripcioEquipAssignacio,
)
from ..shared.competition_groups import ensure_group_for_display_num
from ..teams.equip_contexts import NATIVE_EQUIP_CONTEXT_CODE, ensure_base_equip_context
from .timing import INSCRIPCIONS_TIMINGS_HEADER


DEFAULT_BENCHMARK_SEED = 20260410
BENCHMARK_USER_USERNAME = "__bench_inscripcions_user__"
BENCHMARK_USER_EMAIL = "bench.inscripcions@example.com"
BENCHMARK_USER_PASSWORD = "bench-inscripcions"
DEFAULT_OUTPUT_DIR = Path("var/benchmarks/inscripcions")

BENCHMARK_DATASET_SPECS = {
    "small": {"size": 40, "seed_offset": 11},
    "medium": {"size": 240, "seed_offset": 29},
    "large": {"size": 720, "seed_offset": 53},
}
BENCHMARK_SCENARIOS = (
    "get_list",
    "filter_values",
    "sort_apply",
    "groups_preview",
    "groups_workspace",
    "equips_workspace",
    "media_match_preview",
)
MUTATING_SCENARIOS = {"sort_apply"}
SCENARIO_LABELS = {
    "get_list": "GET llistat principal",
    "filter_values": "Valors filtre de columna",
    "sort_apply": "Aplicar ordenacio",
    "groups_preview": "Preview de grups",
    "groups_workspace": "Workspace de grups",
    "equips_workspace": "Workspace d'equips",
    "media_match_preview": "Preview media matching",
}


def dataset_competicio_name(dataset: str) -> str:
    return f"__bench_inscripcions_{dataset}__"


def get_dataset_names(selection: str) -> list[str]:
    token = str(selection or "all").strip().lower()
    if token == "all":
        return list(BENCHMARK_DATASET_SPECS.keys())
    if token not in BENCHMARK_DATASET_SPECS:
        raise ValueError(f"Dataset invalid: {selection}")
    return [token]


def get_scenario_names(selection: str) -> list[str]:
    token = str(selection or "all").strip().lower()
    if token == "all":
        return list(BENCHMARK_SCENARIOS)
    if token not in BENCHMARK_SCENARIOS:
        raise ValueError(f"Scenario invalid: {selection}")
    return [token]


def ensure_benchmark_user():
    User = get_user_model()
    user, created = User.objects.get_or_create(
        username=BENCHMARK_USER_USERNAME,
        defaults={"email": BENCHMARK_USER_EMAIL},
    )
    dirty_fields = []
    if str(getattr(user, "email", "") or "").strip() != BENCHMARK_USER_EMAIL:
        user.email = BENCHMARK_USER_EMAIL
        dirty_fields.append("email")
    if created or not user.has_usable_password():
        user.set_password(BENCHMARK_USER_PASSWORD)
        dirty_fields.append("password")
    if dirty_fields:
        user.save(update_fields=dirty_fields)
    return user


def ensure_benchmark_membership(user, competicio, *, role=CompeticioMembership.Role.OWNER):
    membership, _created = CompeticioMembership.objects.get_or_create(
        user=user,
        competicio=competicio,
        defaults={"role": role, "is_active": True},
    )
    dirty_fields = []
    if membership.role != role:
        membership.role = role
        dirty_fields.append("role")
    if not membership.is_active:
        membership.is_active = True
        dirty_fields.append("is_active")
    if dirty_fields:
        membership.save(update_fields=dirty_fields)
    return membership


def ensure_benchmark_aparells(owner):
    specs = [
        ("BENCHTR", "Trampoli benchmark", Aparell.CompetitionUnit.INDIVIDUAL),
        ("BENCHDMT", "DMT benchmark", Aparell.CompetitionUnit.INDIVIDUAL),
        ("BENCHTM1", "Equip benchmark A", Aparell.CompetitionUnit.TEAM),
        ("BENCHTM2", "Equip benchmark B", Aparell.CompetitionUnit.TEAM),
    ]
    out = []
    for code, name, unit in specs:
        aparell, _created = Aparell.objects.get_or_create(
            created_by=owner,
            codi=code,
            defaults={
                "nom": name,
                "competition_unit": unit,
                "actiu": True,
            },
        )
        dirty_fields = []
        if aparell.nom != name:
            aparell.nom = name
            dirty_fields.append("nom")
        if aparell.competition_unit != unit:
            aparell.competition_unit = unit
            dirty_fields.append("competition_unit")
        if not aparell.actiu:
            aparell.actiu = True
            dirty_fields.append("actiu")
        if dirty_fields:
            aparell.save(update_fields=dirty_fields)
        out.append(aparell)
    return out


def build_benchmark_competicio_defaults(dataset: str) -> dict[str, Any]:
    del dataset
    return {
        "tipus": Competicio.Tipus.TRAMPOLI,
        "group_by_default": ["categoria", "subcategoria"],
        "tab_merges": {},
        "inscripcions_schema": {
            "columns": [
                {"code": "nivell", "label": "Nivell", "kind": "extra"},
                {"code": "delegacio", "label": "Delegacio", "kind": "extra"},
                {"code": "entrenador", "label": "Entrenador", "kind": "extra"},
            ]
        },
        "inscripcions_view": {
            "table_columns": [
                "nom_i_cognoms",
                "document",
                "sexe",
                "data_naixement",
                "entitat",
                "categoria",
                "subcategoria",
                "grup",
                "equip",
                "__aparells__",
                "__media__",
                "ordre_sortida",
                "__actions__",
            ]
        },
    }


def _upsert_competicio_aparells(competicio, apparells):
    for index, aparell in enumerate(apparells, start=1):
        CompeticioAparell.objects.update_or_create(
            competicio=competicio,
            aparell=aparell,
            defaults={
                "ordre": index,
                "actiu": True,
                "nombre_exercicis": 2 if index <= 2 else 1,
                "nombre_elements": 11,
                "te_execucio": True,
                "te_dificultat": True,
                "te_tof": index <= 2,
                "te_hd": index <= 2,
                "te_penalitzacio": True,
                "mode_execucio": "salts" if index <= 2 else "manual",
            },
        )


def _build_inscripcio_extra(index: int, categoria: str, subcategoria: str, entitat: str) -> dict[str, Any]:
    return {
        "excel__nivell": f"{categoria} / {subcategoria}",
        "excel__delegacio": f"Zona {(index % 4) + 1}",
        "excel__entrenador": f"Coach {(index % 9) + 1}",
        "entitat_ref": entitat,
    }


def _build_benchmark_inscripcions(size: int, dataset: str, competicio, groups_by_num: dict[int, GrupCompeticio]) -> list[Inscripcio]:
    categories = ["Base", "Promocio", "Absolut"]
    subcategories = ["A", "B", "C", "D"]
    entities = [
        "Club Alpha",
        "Club Beta",
        "Club Gamma",
        "Club Delta",
        "Club Epsilon",
        "Club Sigma",
        "Club Zeta",
    ]
    first_names = ["Anna", "Berta", "Carla", "Dani", "Eric", "Ferran", "Gina", "Helena", "Iris", "Jordi"]
    last_names = ["Serra", "Roca", "Marti", "Pons", "Costa", "Sole", "Puig", "Ribas", "Vidal", "Ferrer"]

    assigned_group_limit = int(size * 0.65)
    group_size = 6
    rows = []
    for index in range(size):
        categoria = categories[index % len(categories)]
        subcategoria = subcategories[(index // 2) % len(subcategories)]
        entitat = entities[(index * 7 + index // 5) % len(entities)]
        first_name = first_names[index % len(first_names)]
        last_name = last_names[(index * 3) % len(last_names)]
        display_group_num = (index // group_size) + 1 if index < assigned_group_limit else None
        group = groups_by_num.get(display_group_num) if display_group_num else None
        rows.append(
            Inscripcio(
                competicio=competicio,
                nom_i_cognoms=f"{first_name} {last_name} {dataset.upper()} {index + 1:04d}",
                categoria=categoria,
                subcategoria=subcategoria,
                entitat=entitat,
                document=f"{dataset[:1].upper()}{index + 1:07d}",
                sexe="F" if index % 2 == 0 else "M",
                data_naixement=date(2000 + (index % 9), ((index % 12) + 1), ((index % 28) + 1)),
                ordre_sortida=index + 1,
                grup=display_group_num,
                grup_competicio=group,
                ordre_competicio=(index % group_size) + 1 if group else None,
                extra=_build_inscripcio_extra(index, categoria, subcategoria, entitat),
                dedupe_key=f"bench-{dataset}-{index + 1:04d}",
            )
        )
    return rows


def create_or_replace_benchmark_dataset(dataset: str, *, replace: bool = False, seed: int = DEFAULT_BENCHMARK_SEED):
    dataset = str(dataset).strip().lower()
    if dataset not in BENCHMARK_DATASET_SPECS:
        raise ValueError(f"Dataset invalid: {dataset}")

    if replace:
        Competicio.objects.filter(nom=dataset_competicio_name(dataset)).delete()

    competicio, created = Competicio.objects.get_or_create(
        nom=dataset_competicio_name(dataset),
        defaults=build_benchmark_competicio_defaults(dataset),
    )
    defaults = build_benchmark_competicio_defaults(dataset)
    dirty_fields = []
    for field_name, value in defaults.items():
        if getattr(competicio, field_name) != value:
            setattr(competicio, field_name, value)
            dirty_fields.append(field_name)
    if dirty_fields:
        competicio.save(update_fields=dirty_fields)

    benchmark_user = ensure_benchmark_user()
    ensure_benchmark_membership(benchmark_user, competicio)
    apparells = ensure_benchmark_aparells(benchmark_user)
    _upsert_competicio_aparells(competicio, apparells)

    if created or replace or not Inscripcio.objects.filter(competicio=competicio).exists():
        InscripcioEquipAssignacio.objects.filter(competicio=competicio).delete()
        Equip.objects.filter(competicio=competicio).delete()
        EquipContext.objects.filter(competicio=competicio).delete()
        InscripcioAparellExclusio.objects.filter(inscripcio__competicio=competicio).delete()
        Inscripcio.objects.filter(competicio=competicio).delete()
        GrupCompeticio.objects.filter(competicio=competicio).delete()

        spec = BENCHMARK_DATASET_SPECS[dataset]
        size = int(spec["size"])
        rng = random.Random(int(seed) + int(spec["seed_offset"]))

        group_count = max(3, (size // 12) + 1)
        groups_by_num = {}
        for display_num in range(1, group_count + 1):
            group = ensure_group_for_display_num(competicio, display_num, name=f"Bloc {display_num}")
            groups_by_num[display_num] = group

        inscripcions = _build_benchmark_inscripcions(size, dataset, competicio, groups_by_num)
        Inscripcio.objects.bulk_create(inscripcions, batch_size=500)
        created_rows = list(Inscripcio.objects.filter(competicio=competicio).order_by("ordre_sortida", "id"))

        native_ctx = ensure_base_equip_context(competicio)
        team_keys = []
        for inscripcio in created_rows[: max(8, int(size * 0.55))]:
            key = (str(inscripcio.entitat or "").strip(), str(inscripcio.categoria or "").strip())
            if key not in team_keys:
                team_keys.append(key)
            if len(team_keys) >= min(10, max(4, size // 40 + 3)):
                break

        teams_by_key = {}
        for entity, category in team_keys:
            team = Equip.objects.create(
                competicio=competicio,
                context=native_ctx,
                nom=f"{entity} | {category}",
                origen=Equip.Origen.AUTO,
                criteri={"source": "benchmark"},
            )
            teams_by_key[(entity, category)] = team

        assignacions = []
        equip_updates = []
        for index, inscripcio in enumerate(created_rows):
            if index >= int(size * 0.55):
                break
            key = (str(inscripcio.entitat or "").strip(), str(inscripcio.categoria or "").strip())
            team = teams_by_key.get(key)
            if team is None:
                continue
            assignacions.append(
                InscripcioEquipAssignacio(
                    competicio=competicio,
                    context=native_ctx,
                    inscripcio=inscripcio,
                    equip=team,
                    origen=InscripcioEquipAssignacio.Origen.AUTO,
                    criteri={"source": "benchmark"},
                )
            )
            inscripcio.equip = team
            equip_updates.append(inscripcio)
        if assignacions:
            InscripcioEquipAssignacio.objects.bulk_create(assignacions, batch_size=500)
        if equip_updates:
            Inscripcio.objects.bulk_update(equip_updates, ["equip"], batch_size=500)

        comp_aparells = list(CompeticioAparell.objects.filter(competicio=competicio).order_by("ordre", "id"))
        exclusions = []
        for index, inscripcio in enumerate(created_rows):
            if comp_aparells and index % 9 == 0:
                exclusions.append(
                    InscripcioAparellExclusio(
                        inscripcio=inscripcio,
                        comp_aparell=comp_aparells[0],
                        motiu="Benchmark exclusion A",
                    )
                )
            if len(comp_aparells) > 1 and index % 15 == 0:
                exclusions.append(
                    InscripcioAparellExclusio(
                        inscripcio=inscripcio,
                        comp_aparell=comp_aparells[1],
                        motiu="Benchmark exclusion B",
                    )
                )
            if rng.random() < 0.02 and len(comp_aparells) > 2:
                exclusions.append(
                    InscripcioAparellExclusio(
                        inscripcio=inscripcio,
                        comp_aparell=comp_aparells[2],
                        motiu="Benchmark exclusion random",
                    )
                )
        if exclusions:
            InscripcioAparellExclusio.objects.bulk_create(exclusions, batch_size=500)

    return Competicio.objects.get(pk=competicio.pk)


def get_benchmark_competicio(dataset: str):
    return Competicio.objects.filter(nom=dataset_competicio_name(dataset)).first()


def ensure_benchmark_datasets(dataset_names: list[str], *, replace: bool = False, seed: int = DEFAULT_BENCHMARK_SEED):
    return [
        create_or_replace_benchmark_dataset(dataset_name, replace=replace, seed=seed)
        for dataset_name in dataset_names
    ]


def build_benchmark_metadata(*, datasets: list[str], scenarios: list[str], warmup: int, repeats: int) -> dict[str, Any]:
    db_settings = settings.DATABASES.get("default", {})
    return {
        "generated_at": timezone.now().isoformat(),
        "app_env": str(getattr(settings, "APP_ENV", "") or os.getenv("APP_ENV", "") or "dev"),
        "debug": bool(getattr(settings, "DEBUG", False)),
        "database_vendor": str(connection.vendor or ""),
        "database_engine": str(db_settings.get("ENGINE") or ""),
        "database_name": str(db_settings.get("NAME") or ""),
        "service_hostname": str(os.getenv("HOSTNAME") or ""),
        "warmup": int(warmup),
        "repeats": int(repeats),
        "datasets": list(datasets or []),
        "scenarios": list(scenarios or []),
    }


def _build_media_preview_files(competicio) -> list[dict[str, Any]]:
    rows = list(
        Inscripcio.objects.filter(competicio=competicio)
        .order_by("ordre_sortida", "id")
        .only("id", "nom_i_cognoms", "entitat")
    )
    files = []
    for index, row in enumerate(rows, start=1):
        base_name = str(row.nom_i_cognoms or f"INSCRIPCIO {row.id}").strip().upper()
        entity = str(row.entitat or "").strip().upper()
        filename = f"{index:04d} - {base_name}"
        if entity:
            filename = f"{filename} - {entity}"
        files.append(
            {
                "key": f"media-{index}",
                "filename": f"{filename}.mp3",
                "relative_path": f"audio/{filename}.mp3",
                "size": 4096 + ((index * 137) % 8192),
            }
        )
    return files


def build_scenario_request(competicio, scenario: str) -> dict[str, Any]:
    scenario = str(scenario or "").strip().lower()
    if scenario == "get_list":
        base_url = reverse("inscripcions_list", kwargs={"pk": competicio.id})
        group_by = [str(code).strip() for code in (competicio.group_by_default or []) if str(code).strip()]
        url = f"{base_url}?{urlencode({'group_by': group_by}, doseq=True)}" if group_by else base_url
        return {"method": "get", "url": url, "data": None, "content_type": None}
    if scenario == "filter_values":
        return {
            "method": "post",
            "url": reverse("inscripcions_filter_values", kwargs={"pk": competicio.id}),
            "data": {"column_code": "entitat", "filters": {}},
            "content_type": "application/json",
        }
    if scenario == "sort_apply":
        return {
            "method": "post",
            "url": reverse("inscripcions_sort_apply", kwargs={"pk": competicio.id}),
            "data": {
                "sort_key": "entitat",
                "sort_dir": "asc",
                "scope": "all",
                "filters": {},
                "group_by": [],
            },
            "content_type": "application/json",
        }
    if scenario == "groups_preview":
        return {
            "method": "post",
            "url": reverse("groups_preview", kwargs={"pk": competicio.id}),
            "data": {"action": "create", "scope": "filtered", "filters": {}, "selected_ids": []},
            "content_type": "application/json",
        }
    if scenario == "groups_workspace":
        return {
            "method": "post",
            "url": reverse("groups_workspace", kwargs={"pk": competicio.id}),
            "data": {"filters": {}, "page": 1, "page_size": 40},
            "content_type": "application/json",
        }
    if scenario == "equips_workspace":
        return {
            "method": "post",
            "url": reverse("inscripcions_equips_workspace", kwargs={"pk": competicio.id}),
            "data": {"context_code": NATIVE_EQUIP_CONTEXT_CODE, "filters": {}, "page": 1, "page_size": 40},
            "content_type": "application/json",
        }
    if scenario == "media_match_preview":
        return {
            "method": "post",
            "url": reverse("inscripcions_media_match_preview", kwargs={"pk": competicio.id}),
            "data": {"files": _build_media_preview_files(competicio)},
            "content_type": "application/json",
        }
    raise ValueError(f"Scenario invalid: {scenario}")


def measure_client_request(client: Client, request_spec: dict[str, Any]) -> dict[str, Any]:
    method = str(request_spec.get("method") or "get").strip().lower()
    url = request_spec["url"]
    payload = request_spec.get("data")
    content_type = request_spec.get("content_type")
    headers = request_spec.get("headers") or {}
    request_kwargs = {
        "HTTP_HOST": "localhost",
        "HTTP_X_REQUESTED_WITH": "XMLHttpRequest",
        "HTTP_X_INSCRIPCIONS_TIMINGS": "1",
        **headers,
    }

    if method == "get":
        if payload:
            request_kwargs["data"] = payload
    else:
        if payload is not None:
            request_kwargs["data"] = json.dumps(payload) if content_type == "application/json" else payload
        if content_type:
            request_kwargs["content_type"] = content_type

    with CaptureQueriesContext(connection) as captured:
        started_at = perf_counter()
        response = getattr(client, method)(url, **request_kwargs)
        elapsed_ms = round((perf_counter() - started_at) * 1000.0, 3)

    try:
        response_bytes = len(response.content)
    except Exception:
        response_bytes = 0

    timings = None
    timings_raw = getattr(getattr(response, "headers", {}), "get", lambda *_args, **_kwargs: "")(INSCRIPCIONS_TIMINGS_HEADER, "")
    if timings_raw:
        try:
            timings = json.loads(timings_raw)
        except Exception:
            timings = {"raw": str(timings_raw)}

    sql_time_ms = 0.0
    for row in captured.captured_queries:
        try:
            sql_time_ms += float(row.get("time") or 0.0) * 1000.0
        except Exception:
            continue
    return {
        "elapsed_ms": elapsed_ms,
        "sql_count": len(captured.captured_queries),
        "sql_time_ms": round(sql_time_ms, 3),
        "response_bytes": int(response_bytes),
        "status_code": int(getattr(response, "status_code", 0) or 0),
        "url": str(url),
        "timings": timings,
    }


def _competition_copy_name(source_competicio, *, scenario: str, run_index: int) -> str:
    timestamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
    return f"{source_competicio.nom}__work__{scenario}__r{run_index}__{timestamp}"


def clone_competicio_for_work(source_competicio, *, benchmark_user, scenario: str, run_index: int):
    clone = Competicio.objects.create(
        nom=_competition_copy_name(source_competicio, scenario=scenario, run_index=run_index),
        data=source_competicio.data,
        tipus=source_competicio.tipus,
        group_by_default=list(source_competicio.group_by_default or []),
        tab_merges=json.loads(json.dumps(source_competicio.tab_merges or {})),
        inscripcions_schema=json.loads(json.dumps(source_competicio.inscripcions_schema or {})),
        inscripcions_view=json.loads(json.dumps(source_competicio.inscripcions_view or {})),
    )
    ensure_benchmark_membership(benchmark_user, clone)

    source_contexts = {
        context.id: context
        for context in EquipContext.objects.filter(competicio=source_competicio).order_by("id")
    }

    group_map = {}
    for group in GrupCompeticio.objects.filter(competicio=source_competicio).order_by("display_num", "id"):
        group_map[group.id] = GrupCompeticio.objects.create(
            competicio=clone,
            legacy_num=group.legacy_num,
            display_num=group.display_num,
            nom=group.nom,
            actiu=group.actiu,
        )

    for context in source_contexts.values():
        EquipContext.objects.create(
            competicio=clone,
            code=context.code,
            nom=context.nom,
            description=context.description,
        )
    ensure_base_equip_context(clone)
    context_map = {
        context.code: context
        for context in EquipContext.objects.filter(competicio=clone).order_by("id")
    }

    team_map = {}
    for team in Equip.objects.filter(competicio=source_competicio).order_by("id"):
        source_context = source_contexts.get(team.context_id)
        target_context = context_map.get(str(getattr(source_context, "code", "") or NATIVE_EQUIP_CONTEXT_CODE))
        if target_context is None:
            target_context = ensure_base_equip_context(clone)
        team_map[team.id] = Equip.objects.create(
            competicio=clone,
            context=target_context,
            nom=team.nom,
            origen=team.origen,
            criteri=json.loads(json.dumps(team.criteri or {})),
        )

    comp_aparell_map = {}
    for comp_aparell in CompeticioAparell.objects.filter(competicio=source_competicio).order_by("ordre", "id"):
        comp_aparell_map[comp_aparell.id] = CompeticioAparell.objects.create(
            competicio=clone,
            aparell=comp_aparell.aparell,
            nom_local=comp_aparell.nom_local,
            codi_local=comp_aparell.codi_local,
            nombre_exercicis=comp_aparell.nombre_exercicis,
            ordre=comp_aparell.ordre,
            nombre_elements=comp_aparell.nombre_elements,
            te_execucio=comp_aparell.te_execucio,
            te_dificultat=comp_aparell.te_dificultat,
            te_tof=comp_aparell.te_tof,
            te_hd=comp_aparell.te_hd,
            te_penalitzacio=comp_aparell.te_penalitzacio,
            mode_execucio=comp_aparell.mode_execucio,
            participation_config=json.loads(json.dumps(comp_aparell.participation_config or {})),
            actiu=comp_aparell.actiu,
        )

    inscripcio_map = {}
    source_rows = list(Inscripcio.objects.filter(competicio=source_competicio).order_by("ordre_sortida", "id"))
    clone_rows = []
    for source_row in source_rows:
        clone_rows.append(
            Inscripcio(
                competicio=clone,
                nom_i_cognoms=source_row.nom_i_cognoms,
                categoria=source_row.categoria,
                subcategoria=source_row.subcategoria,
                entitat=source_row.entitat,
                document=source_row.document,
                sexe=source_row.sexe,
                data_naixement=source_row.data_naixement,
                ordre_sortida=source_row.ordre_sortida,
                group_by_default=list(source_row.group_by_default or []),
                grup=source_row.grup,
                grup_competicio=group_map.get(source_row.grup_competicio_id),
                ordre_competicio=source_row.ordre_competicio,
                equip=team_map.get(source_row.equip_id),
                extra=json.loads(json.dumps(source_row.extra or {})),
                dedupe_key=source_row.dedupe_key,
            )
        )
    Inscripcio.objects.bulk_create(clone_rows, batch_size=500)
    created_rows = list(Inscripcio.objects.filter(competicio=clone).order_by("ordre_sortida", "id"))
    for source_row, target_row in zip(source_rows, created_rows):
        inscripcio_map[source_row.id] = target_row

    assignacions = []
    for assignacio in InscripcioEquipAssignacio.objects.filter(competicio=source_competicio).order_by("context_id", "inscripcio_id"):
        source_context = source_contexts.get(assignacio.context_id)
        target_context = context_map.get(str(getattr(source_context, "code", "") or NATIVE_EQUIP_CONTEXT_CODE))
        target_inscripcio = inscripcio_map.get(assignacio.inscripcio_id)
        target_team = team_map.get(assignacio.equip_id)
        if target_context is None or target_inscripcio is None or target_team is None:
            continue
        assignacions.append(
            InscripcioEquipAssignacio(
                competicio=clone,
                context=target_context,
                inscripcio=target_inscripcio,
                equip=target_team,
                origen=assignacio.origen,
                criteri=json.loads(json.dumps(assignacio.criteri or {})),
            )
        )
    if assignacions:
        InscripcioEquipAssignacio.objects.bulk_create(assignacions, batch_size=500)

    exclusions = []
    for exclusion in InscripcioAparellExclusio.objects.filter(inscripcio__competicio=source_competicio).order_by("inscripcio_id", "comp_aparell_id"):
        target_inscripcio = inscripcio_map.get(exclusion.inscripcio_id)
        target_comp_aparell = comp_aparell_map.get(exclusion.comp_aparell_id)
        if target_inscripcio is None or target_comp_aparell is None:
            continue
        exclusions.append(
            InscripcioAparellExclusio(
                inscripcio=target_inscripcio,
                comp_aparell=target_comp_aparell,
                motiu=exclusion.motiu,
            )
        )
    if exclusions:
        InscripcioAparellExclusio.objects.bulk_create(exclusions, batch_size=500)

    return clone


def cleanup_work_competicio(competicio):
    if competicio is not None:
        Competicio.objects.filter(pk=getattr(competicio, "pk", None)).delete()


def aggregate_benchmark_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = defaultdict(list)
    for row in results or []:
        if row.get("is_warmup"):
            continue
        grouped[(str(row.get("dataset") or ""), str(row.get("scenario") or ""))].append(row)

    out = []
    for (dataset, scenario), rows in sorted(grouped.items()):
        elapsed_values = [float(row.get("elapsed_ms") or 0.0) for row in rows]
        sql_count_values = [int(row.get("sql_count") or 0) for row in rows]
        sql_time_values = [float(row.get("sql_time_ms") or 0.0) for row in rows]
        response_bytes_values = [int(row.get("response_bytes") or 0) for row in rows]
        out.append(
            {
                "dataset": dataset,
                "scenario": scenario,
                "scenario_label": SCENARIO_LABELS.get(scenario, scenario),
                "runs": len(rows),
                "status_codes": sorted({int(row.get("status_code") or 0) for row in rows}),
                "elapsed_ms_min": round(min(elapsed_values), 3),
                "elapsed_ms_mean": round(mean(elapsed_values), 3),
                "elapsed_ms_median": round(median(elapsed_values), 3),
                "elapsed_ms_max": round(max(elapsed_values), 3),
                "sql_count_min": min(sql_count_values),
                "sql_count_mean": round(mean(sql_count_values), 3),
                "sql_count_median": round(median(sql_count_values), 3),
                "sql_count_max": max(sql_count_values),
                "sql_time_ms_min": round(min(sql_time_values), 3),
                "sql_time_ms_mean": round(mean(sql_time_values), 3),
                "sql_time_ms_median": round(median(sql_time_values), 3),
                "sql_time_ms_max": round(max(sql_time_values), 3),
                "response_bytes_min": min(response_bytes_values),
                "response_bytes_mean": round(mean(response_bytes_values), 3),
                "response_bytes_median": round(median(response_bytes_values), 3),
                "response_bytes_max": max(response_bytes_values),
            }
        )
    return out


def format_summary_table(summary_rows: list[dict[str, Any]]) -> str:
    headers = [
        ("dataset", "dataset"),
        ("scenario", "scenario"),
        ("elapsed_ms_mean", "elapsed_ms_mean"),
        ("sql_count_mean", "sql_count_mean"),
        ("sql_time_ms_mean", "sql_time_ms_mean"),
        ("response_bytes_mean", "response_bytes_mean"),
        ("status_codes", "status_codes"),
    ]
    prepared = []
    widths = {label: len(label) for label, _key in headers}
    for row in summary_rows or []:
        prepared_row = {}
        for label, key in headers:
            value = row.get(key)
            text = ",".join(str(item) for item in value) if isinstance(value, list) else str(value)
            prepared_row[label] = text
            widths[label] = max(widths[label], len(text))
        prepared.append(prepared_row)

    def render_line(cells):
        return " | ".join(cells[label].ljust(widths[label]) for label, _key in headers)

    header_cells = {label: label for label, _key in headers}
    separator_cells = {label: "-" * widths[label] for label, _key in headers}
    lines = [render_line(header_cells), render_line(separator_cells)]
    for row in prepared:
        lines.append(render_line(row))
    return "\n".join(lines)


def build_markdown_snippet(metadata: dict[str, Any], summary_rows: list[dict[str, Any]]) -> str:
    lines = [
        "## Baseline snapshot",
        "",
        f"- Generated at: `{metadata.get('generated_at')}`",
        f"- App env: `{metadata.get('app_env')}`",
        f"- DB vendor: `{metadata.get('database_vendor')}`",
        f"- Warmup: `{metadata.get('warmup')}`",
        f"- Repeats: `{metadata.get('repeats')}`",
        "",
        "| Dataset | Scenario | Mean ms | Mean SQL count | Mean SQL ms | Mean response bytes | Status |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summary_rows or []:
        lines.append(
            "| {dataset} | {scenario} | {elapsed:.3f} | {sql_count:.3f} | {sql_time:.3f} | {response:.3f} | {status} |".format(
                dataset=row.get("dataset"),
                scenario=row.get("scenario"),
                elapsed=float(row.get("elapsed_ms_mean") or 0.0),
                sql_count=float(row.get("sql_count_mean") or 0.0),
                sql_time=float(row.get("sql_time_ms_mean") or 0.0),
                response=float(row.get("response_bytes_mean") or 0.0),
                status=",".join(str(code) for code in (row.get("status_codes") or [])),
            )
        )
    return "\n".join(lines)


def build_results_payload(metadata: dict[str, Any], raw_results: list[dict[str, Any]], summary_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"metadata": metadata, "results": list(raw_results or []), "summary": list(summary_rows or [])}


def ensure_output_dir(path_value: str | Path | None) -> Path:
    path = Path(path_value or DEFAULT_OUTPUT_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_output_file_path(output_dir: str | Path | None, *, extension: str = "json") -> Path:
    base_dir = ensure_output_dir(output_dir)
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    return base_dir / f"{timestamp}.{extension}"


def run_benchmark_scenario(*, dataset: str, scenario: str, run_index: int, is_warmup: bool, benchmark_user) -> dict[str, Any]:
    source_competicio = get_benchmark_competicio(dataset)
    if source_competicio is None:
        raise ValueError(f"Dataset no trobat: {dataset}")

    work_competicio = None
    try:
        if scenario in MUTATING_SCENARIOS:
            work_competicio = clone_competicio_for_work(
                source_competicio,
                benchmark_user=benchmark_user,
                scenario=scenario,
                run_index=run_index,
            )
            target_competicio = work_competicio
        else:
            target_competicio = source_competicio

        client = Client()
        client.force_login(benchmark_user)
        request_spec = build_scenario_request(target_competicio, scenario)
        measured = measure_client_request(client, request_spec)
        return {
            "dataset": dataset,
            "scenario": scenario,
            "run_index": int(run_index),
            "is_warmup": bool(is_warmup),
            **measured,
        }
    finally:
        if work_competicio is not None:
            cleanup_work_competicio(work_competicio)
