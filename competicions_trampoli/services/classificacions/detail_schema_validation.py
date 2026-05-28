import re


DETAIL_SECTION_TYPES = {
    "members_list",
    "members_table",
    "team_members_table",
    "team_metrics",
    "exercise_table",
    "entity_members_table",
}

DETAIL_SECTION_ALLOWED = {
    "individual": {"exercise_table"},
    "entitat": {"entity_members_table"},
    "equips:derived_from_individual": {"members_list", "members_table"},
    "equips:native_team": {"members_list", "team_metrics", "team_members_table"},
}


def validation_error_section_from_path(path: str) -> str:
    path = str(path or "").strip()
    if path.startswith("presentacio"):
        return "presentacio"
    if path.startswith("filtres"):
        return "filtres"
    if path.startswith("puntuacio"):
        return "puntuacio"
    if path.startswith("desempat"):
        return "desempat"
    if path.startswith("particions"):
        return "particions"
    if path.startswith("equips"):
        return "meta"
    return "general"


def build_validation_detail(path: str, message: str, *, section=None, severity="error") -> dict:
    clean_path = str(path or "").strip()
    return {
        "path": clean_path,
        "message": str(message or "").strip(),
        "section": str(section or validation_error_section_from_path(clean_path)).strip() or "general",
        "severity": str(severity or "error").strip() or "error",
    }


def validation_details_to_messages(details) -> list[str]:
    out = []
    for item in details or []:
        if not isinstance(item, dict):
            continue
        message = str(item.get("message") or "").strip()
        if message:
            out.append(message)
    return out


def legacy_validation_error_details(error_messages):
    details = []
    patterns = [
        (re.compile(r"^(?P<path>[A-Za-z_][\w\.\[\]']*) raw: aparell .+$"), ".source.aparell_id"),
        (re.compile(r"^(?P<path>[A-Za-z_][\w\.\[\]']*) raw: camp .+$"), ".source.camp"),
        (re.compile(r"^(?P<path>[A-Za-z_][\w\.\[\]']*) raw: exercici .+$"), ".source.exercici"),
        (re.compile(r"^(?P<path>[A-Za-z_][\w\.\[\]']*) raw: exercise_mode .+$"), ".source.exercise_mode"),
        (re.compile(r"^(?P<path>[A-Za-z_][\w\.\[\]']*) builtin: .+$"), ".key"),
        (re.compile(r"^(?P<path>[A-Za-z_][\w\.\[\]']*) tipus .+$"), ".type"),
        (re.compile(r"^(?P<path>[A-Za-z_][\w\.\[\]']*\.enabled) .*$"), ""),
        (re.compile(r"^(?P<path>[A-Za-z_][\w\.\[\]']*\.default_open) .*$"), ""),
        (re.compile(r"^(?P<path>[A-Za-z_][\w\.\[\]']*\.aparell_id): .+$"), ""),
        (re.compile(r"^(?P<path>[A-Za-z_][\w\.\[\]']*\.columns) .+$"), ""),
        (re.compile(r"^(?P<path>[A-Za-z_][\w\.\[\]']*): .+$"), ""),
    ]

    for raw in error_messages or []:
        message = str(raw or "").strip()
        if not message:
            continue
        path = ""
        for pattern, suffix in patterns:
            match = pattern.match(message)
            if not match:
                continue
            path = str(match.group("path") or "").strip()
            if suffix and not path.endswith(suffix):
                path = f"{path}{suffix}"
            break
        details.append(build_validation_detail(path, message))
    return details


def detail_section_key_for_tipus(tipus="individual", team_mode=""):
    tipus_norm = str(tipus or "").strip().lower()
    team_mode_norm = str(team_mode or "").strip().lower()
    if tipus_norm == "equips":
        return f"equips:{team_mode_norm}"
    return tipus_norm


def detail_allowed_builtin(section_type: str):
    stype = str(section_type or "").strip().lower()
    if stype == "exercise_table":
        return {"exercise_index", "aparell_nom", "participant", "entitat_nom"}
    if stype in {"members_table", "team_members_table", "entity_members_table", "team_metrics"}:
        return {"participant", "entitat_nom"}
    return set()


def detail_expected_unit(section_type: str):
    stype = str(section_type or "").strip().lower()
    if stype in {"team_metrics", "team_members_table"}:
        return "team"
    if stype in {"members_table", "entity_members_table", "exercise_table"}:
        return "individual"
    return None


def validate_detail_schema(
    raw_detail,
    *,
    detail_section_key,
    normalize_app,
    is_app_available,
    get_app_unit,
    get_scoreable_info,
    selected_apps=None,
    validate_exercise=None,
):
    details = []
    allowed_types = DETAIL_SECTION_ALLOWED.get(detail_section_key) or set()
    detail_active = bool(allowed_types)
    selected_set = None if selected_apps is None else set(selected_apps)

    def add(path, message):
        details.append(build_validation_detail(path, message))

    def normalize_positive_int(raw):
        try:
            value = int(raw)
        except Exception:
            return None
        return value if value > 0 else None

    def raw_app_values(raw_cols):
        out = []
        if not isinstance(raw_cols, list):
            return out
        for col in raw_cols:
            if not isinstance(col, dict):
                continue
            if str(col.get("type") or "builtin").strip().lower() != "raw":
                continue
            src = col.get("source") if isinstance(col.get("source"), dict) else {}
            app_value = normalize_app(src.get("aparell_id"))
            if app_value not in (None, "", 0, "0") and app_value not in out:
                out.append(app_value)
        return out

    def validate_columns(raw_cols, path_prefix, section_type, *, section_app=None):
        if not isinstance(raw_cols, list):
            add(path_prefix, f"{path_prefix} ha de ser una llista.")
            return
        for cidx, col in enumerate(raw_cols):
            col_path = f"{path_prefix}[{cidx}]"
            if not isinstance(col, dict):
                add(col_path, f"{col_path} ha de ser un objecte.")
                continue
            ctype = str(col.get("type") or "builtin").strip().lower()
            if ctype == "builtin":
                key = str(col.get("key") or "").strip()
                if key not in detail_allowed_builtin(section_type):
                    add(f"{col_path}.key", f"{col_path} builtin: clau no permesa ({key}).")
                continue
            if ctype != "raw":
                add(f"{col_path}.type", f"{col_path} tipus no valid: {ctype}.")
                continue

            src = col.get("source") if isinstance(col.get("source"), dict) else {}
            raw_app = src.get("aparell_id")
            app_value = normalize_app(raw_app)
            if app_value in (None, "", 0, "0"):
                add(f"{col_path}.source.aparell_id", f"{col_path} raw: aparell invalid.")
                continue
            if section_app is not None and app_value != section_app:
                add(
                    f"{col_path}.source.aparell_id",
                    f"{col_path} raw: l'aparell {app_value} no concorda amb presentacio.detall.sections.aparell_id={section_app}.",
                )
                continue
            if not is_app_available(app_value):
                add(
                    f"{col_path}.source.aparell_id",
                    f"{col_path} raw: aparell {app_value} no valid o no actiu.",
                )
                continue
            expected_unit = detail_expected_unit(section_type)
            app_unit = str(get_app_unit(app_value) or "").strip().lower()
            if expected_unit == "team" and app_unit != "team":
                add(
                    f"{col_path}.source.aparell_id",
                    f"{col_path} raw: en {section_type} nomes es poden mostrar aparells d'equip.",
                )
                continue
            if expected_unit == "individual" and app_unit == "team":
                add(
                    f"{col_path}.source.aparell_id",
                    f"{col_path} raw: en {section_type} no es poden mostrar aparells d'equip.",
                )
                continue
            if selected_set is not None and app_value not in selected_set:
                add(
                    f"{col_path}.source.aparell_id",
                    f"{col_path} raw: aparell {app_value} no esta seleccionat a puntuacio.",
                )
                continue
            camp = str(src.get("camp") or "").strip()
            if not camp:
                add(f"{col_path}.source.camp", f"{col_path} raw: camp obligatori.")
                continue
            info = get_scoreable_info(app_value, camp)
            if not info:
                add(
                    f"{col_path}.source.camp",
                    f"{col_path} raw: camp '{camp}' no existeix al schema de l'aparell {app_value}.",
                )
                continue
            member_dependent = bool((info or {}).get("member_dependent", False))
            if section_type == "team_members_table":
                if not bool((info or {}).get("detail_displayable", False)):
                    detail_kind = str((info or {}).get("detail_display_kind") or "none").strip().lower()
                    reason = str((info or {}).get("reason") or "").strip()
                    if detail_kind == "none" and reason:
                        reason = f" ({reason})"
                    elif detail_kind == "none":
                        reason = ""
                    else:
                        reason = f" (detail_display_kind={detail_kind})"
                    add(
                        f"{col_path}.source.camp",
                        f"{col_path} raw: camp '{camp}' no es visualitzable a team_members_table{reason}.",
                    )
                    continue
                if not member_dependent:
                    add(
                        f"{col_path}.source.camp",
                        f"{col_path} raw: en team_members_table nomes es poden mostrar camps individuals per membre.",
                    )
                    continue
            elif not bool((info or {}).get("scoreable", False)):
                add(
                    f"{col_path}.source.camp",
                    f"{col_path} raw: camp '{camp}' no es puntuable directament ({info.get('reason')}).",
                )
                continue
            if section_type == "team_metrics" and member_dependent:
                add(
                    f"{col_path}.source.camp",
                    f"{col_path} raw: en team_metrics nomes es poden mostrar camps d'equip o compartits.",
                )
                continue
            raw_exercise_mode = str(src.get("exercise_mode") or "").strip().lower()
            has_exercise_mode = "exercise_mode" in src and str(src.get("exercise_mode") or "").strip() != ""
            if section_type == "team_members_table":
                exercise_mode = raw_exercise_mode or "selected"
                if raw_exercise_mode and raw_exercise_mode not in {"selected", "fixed"}:
                    add(
                        f"{col_path}.source.exercise_mode",
                        f"{col_path} raw: exercise_mode invalid ({raw_exercise_mode}).",
                    )
                    continue
                if exercise_mode == "fixed":
                    if "exercici" not in src:
                        add(
                            f"{col_path}.source.exercici",
                            f"{col_path} raw: exercici obligatori quan exercise_mode=fixed.",
                        )
                        continue
                    if validate_exercise is not None:
                        exercise_message = validate_exercise(app_value, src.get("exercici"))
                        if exercise_message:
                            add(f"{col_path}.source.exercici", f"{col_path} raw: {exercise_message}")
                continue
            if has_exercise_mode:
                add(
                    f"{col_path}.source.exercise_mode",
                    f"{col_path} raw: exercise_mode no es compatible amb {section_type}.",
                )
                continue
            if validate_exercise is not None:
                exercise_message = validate_exercise(app_value, src.get("exercici"))
                if exercise_message:
                    add(f"{col_path}.source.exercici", f"{col_path} raw: {exercise_message}")

    if raw_detail is None:
        return details
    if not isinstance(raw_detail, dict):
        add("presentacio.detall", "presentacio.detall ha de ser un objecte.")
        return details

    detail_enabled_raw = raw_detail.get("enabled", False)
    detail_default_open_raw = raw_detail.get("default_open", False)
    if "enabled" in raw_detail and not isinstance(detail_enabled_raw, bool):
        add("presentacio.detall.enabled", "presentacio.detall.enabled ha de ser boolea.")
    if "default_open" in raw_detail and not isinstance(detail_default_open_raw, bool):
        add("presentacio.detall.default_open", "presentacio.detall.default_open ha de ser boolea.")
    if "sections_layout" in raw_detail:
        sections_layout = str(raw_detail.get("sections_layout") or "").strip().lower()
        if sections_layout not in {"tabs", "stacked"}:
            add("presentacio.detall.sections_layout", "presentacio.detall.sections_layout ha de ser tabs o stacked.")

    detail_enabled = bool(detail_enabled_raw) if isinstance(detail_enabled_raw, bool) else False
    raw_sections = raw_detail.get("sections", None)
    if raw_sections is not None and not isinstance(raw_sections, list):
        add("presentacio.detall.sections", "presentacio.detall.sections ha de ser una llista.")
        raw_sections = None
    raw_legacy_cols = raw_detail.get("columnes", None)
    if raw_legacy_cols is not None and not isinstance(raw_legacy_cols, list):
        add("presentacio.detall.columnes", "presentacio.detall.columnes ha de ser una llista.")
        raw_legacy_cols = None
    elif isinstance(raw_legacy_cols, list) and not raw_legacy_cols:
        raw_legacy_cols = None

    if detail_enabled and not detail_active:
        add(
            "presentacio.detall.enabled",
            f"presentacio.detall.enabled no es compatible amb {detail_section_key}.",
        )

    if raw_legacy_cols is not None:
        if "members_table" not in allowed_types:
            add(
                "presentacio.detall.columnes",
                f"presentacio.detall.columnes nomes es compatible amb contexts que admeten members_table ({detail_section_key}).",
            )
        else:
            if len(raw_app_values(raw_legacy_cols)) > 1:
                add(
                    "presentacio.detall.columnes",
                    "presentacio.detall.columnes barreja aparells multiples; cal dividir el detall en una seccio per aparell.",
                )
            validate_columns(raw_legacy_cols, "presentacio.detall.columnes", "members_table")

    if isinstance(raw_sections, list):
        for sidx, section in enumerate(raw_sections):
            section_path = f"presentacio.detall.sections[{sidx}]"
            if not isinstance(section, dict):
                add(section_path, f"{section_path} ha de ser un objecte.")
                continue
            section_type = str(section.get("type") or "").strip().lower()
            if section_type not in DETAIL_SECTION_TYPES:
                add(f"{section_path}.type", f"{section_path} tipus no valid: {section_type}.")
                continue
            if section_type not in allowed_types:
                add(
                    f"{section_path}.type",
                    f"{section_path} tipus no permes per {detail_section_key}: {section_type}.",
                )
                continue
            if section_type == "members_list":
                if section.get("aparell_id") not in (None, "", 0, "0"):
                    add(
                        f"{section_path}.aparell_id",
                        f"{section_path}.aparell_id no es compatible amb members_list.",
                    )
                if "columns" in section and section.get("columns") not in (None, []):
                    add(
                        f"{section_path}.columns",
                        f"{section_path}.columns no es compatible amb members_list.",
                    )
                continue

            section_app = normalize_app(section.get("aparell_id"))
            if section_app in (None, "", 0, "0"):
                section_app = None
            raw_apps = raw_app_values(section.get("columns"))
            if section_app is None and len(raw_apps) == 1:
                section_app = raw_apps[0]
            elif raw_apps and section_app is None:
                add(
                    f"{section_path}.aparell_id",
                    f"{section_path}.aparell_id es obligatori quan hi ha columnes raw.",
                )
            if len(raw_apps) > 1:
                add(
                    section_path,
                    f"{section_path} barreja aparells multiples; cal dividir el detall en una seccio per aparell.",
                )
            if section_app is not None:
                if not is_app_available(section_app):
                    add(
                        f"{section_path}.aparell_id",
                        f"{section_path}.aparell_id: aparell {section_app} no valid o no actiu.",
                    )
                else:
                    expected_unit = detail_expected_unit(section_type)
                    app_unit = str(get_app_unit(section_app) or "").strip().lower()
                    if expected_unit == "team" and app_unit != "team":
                        add(
                            f"{section_path}.aparell_id",
                            f"{section_path}.aparell_id: en {section_type} nomes es poden mostrar aparells d'equip.",
                        )
                    elif expected_unit == "individual" and app_unit == "team":
                        add(
                            f"{section_path}.aparell_id",
                            f"{section_path}.aparell_id: en {section_type} no es poden mostrar aparells d'equip.",
                        )
                    elif selected_set is not None and section_app not in selected_set:
                        add(
                            f"{section_path}.aparell_id",
                            f"{section_path}.aparell_id: aparell {section_app} no esta seleccionat a puntuacio.",
                        )
            validate_columns(
                section.get("columns"),
                f"{section_path}.columns",
                section_type,
                section_app=section_app,
            )

    if detail_enabled:
        has_sections = isinstance(raw_sections, list) and len(raw_sections) > 0
        has_legacy = isinstance(raw_legacy_cols, list)
        if not has_sections and not has_legacy:
            add(
                "presentacio.detall.enabled",
                "presentacio.detall.enabled requereix sections o columnes legacy compatibles.",
            )

    return details
