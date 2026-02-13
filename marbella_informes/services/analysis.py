from __future__ import annotations
from typing import Callable, Optional
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from .analysis_reserves import analyze_reserves
from .analysis_clients import analyze_clients
import pandas as pd
import matplotlib.pyplot as plt
from django.conf import settings
from django.db import transaction
from .specs import SPECS

from ..models import AnnualReport


# ---------- Types ----------

@dataclass
class AnalysisArtifacts:
    run_dir: str
    plots: List[Dict[str, Any]]          # paths relatius a MEDIA_ROOT
    kpis_path: str            # relatiu a MEDIA_ROOT
    warnings_path: str        # relatiu a MEDIA_ROOT


@dataclass
class AnalysisOutput:
    kpis: Dict[str, Any]
    warnings: List[str]
    artifacts: AnalysisArtifacts

ProgressCB = Callable[[int, str], None]

# ---------- Helpers ----------

def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)



def _default_run_dir(report_id: int) -> str:
    report = AnnualReport.objects.get(pk=report_id)
    year = str(report.any)
    return os.path.join(settings.MEDIA_ROOT, "marbella", year, "runs", str(report_id), _now_stamp())


def _read_excel(path: str) -> pd.DataFrame:
    # pots ajustar sheet_name si cal
    return pd.read_excel(path, engine="openpyxl")


# ---------- Core steps ----------

def load_datasets(report: AnnualReport) -> Tuple[Dict[str, pd.DataFrame], List[str]]:
    """
    Carrega tots els excels adjunts al report i retorna {tipus: df}.
    També retorna warnings no-crítics.
    """
    dfs: Dict[str, pd.DataFrame] = {}
    warnings: List[str] = []

    for ds in report.datasets.all():
        if not ds.fitxer:
            continue
        try:
            df = _read_excel(ds.fitxer.path)
            # normalitza columnes
            df.columns = [str(c).strip() for c in df.columns]
            dfs[ds.tipus] = df
        except Exception as e:
            warnings.append(f"No s'ha pogut llegir '{ds.get_tipus_display()}': {e}")

    return dfs, warnings


def validate_inputs(dfs: Dict[str, pd.DataFrame], required: Optional[List[str]] = None) -> List[str]:
    """
    Validacions mínimes: existeix dataset obligatori i columnes mínimes.
    """
    warnings: List[str] = []
    required = required or ["clients", "reserves"]

    missing = [t for t in required if t not in dfs]
    if missing:
        # això és crític; ho tirem com a warning "fort" i després pots convertir-ho a Exception si vols
        warnings.append(f"Falten datasets obligatoris: {', '.join(missing)}")

    # Exemple de columnes esperades (adapta al teu excel real)
    expected_cols = {
        "clients": ["id", "data_alta"],          # exemple
        "reserves": ["data", "espai", "hores"],  # exemple
    }

    for typ, cols in expected_cols.items():
        if typ in dfs:
            df_cols = set(dfs[typ].columns)
            miss_cols = [c for c in cols if c not in df_cols]
            if miss_cols:
                warnings.append(f"Dataset '{typ}': falten columnes {miss_cols}")

    return warnings


def compute_kpis(dfs: Dict[str, pd.DataFrame], config: Dict[str, Any]) -> Dict[str, Any]:
    """
    KPIs mínims d'exemple. Aquí hi posaràs el teu càlcul real.
    """
    kpis: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config_used": config,
    }

    if "clients" in dfs:
        kpis["clients_rows"] = int(len(dfs["clients"]))
    if "reserves" in dfs:
        kpis["reserves_rows"] = int(len(dfs["reserves"]))

        # exemple: suma hores si la col existeix
        if "hores" in dfs["reserves"].columns:
            kpis["reserves_hores_total"] = float(pd.to_numeric(dfs["reserves"]["hores"], errors="coerce").fillna(0).sum())

    return kpis




def write_artifacts(run_dir_abs: str, kpis: Dict[str, Any], warnings: List[str], plot_items: List[Dict[str, Any]]) -> AnalysisArtifacts:
    """
    Escriu kpis.json i warnings.json a run_dir i retorna metadades.
    """
    _ensure_dir(run_dir_abs)

    kpis_abs = os.path.join(run_dir_abs, "kpis.json")
    warnings_abs = os.path.join(run_dir_abs, "warnings.json")

    with open(kpis_abs, "w", encoding="utf-8") as f:
        json.dump(kpis, f, ensure_ascii=False, indent=2)
    with open(warnings_abs, "w", encoding="utf-8") as f:
        json.dump(warnings, f, ensure_ascii=False, indent=2)

    return AnalysisArtifacts(
        run_dir=_media_rel(run_dir_abs),
        plots=plot_items,
        kpis_path=_media_rel(kpis_abs),
        warnings_path=_media_rel(warnings_abs),
    )


def _media_rel(abs_path: str) -> str:
    rel = os.path.relpath(abs_path, settings.MEDIA_ROOT)
    return rel.replace("\\", "/")


def validate_dataset(df: pd.DataFrame, dataset_type: str) -> list[str]:
    spec = SPECS.get(dataset_type)
    if not spec:
        return []

    errors = []
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in spec.required_cols if c not in df.columns]
    if missing:
        errors.append(f"{dataset_type}: falten columnes {missing}")
        return errors

    if spec.custom_validator:
        errors += spec.custom_validator(df)

    return errors

# ---------- Public API ----------

@transaction.atomic
def run_analysis(
    report_id: int,
    persist: bool = False,
    out_dir: Optional[str] = None,
    verbose: bool = True,
    progress_cb: Optional[ProgressCB] = None,
) -> AnalysisOutput:
    report = AnnualReport.objects.prefetch_related("datasets").get(pk=report_id)

    def _p(pct: int, status: str) -> None:
        if progress_cb:
            progress_cb(int(pct), status)

    _p(2, "loading_datasets")
    run_dir_abs = out_dir or _default_run_dir(report_id)
    plots_dir_abs = os.path.join(run_dir_abs, "plots")
    _ensure_dir(plots_dir_abs)

    dfs, warnings = load_datasets(report)

    _p(10, "validating")
    errors = []
    if "reserves" in dfs:
        errors += validate_dataset(dfs["reserves"], "reserves")
    if "clients" in dfs:
        warnings += validate_dataset(dfs["clients"], "clients")
    if errors:
        warnings += errors

    kpis: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config_used": report.config or {},
    }
    plot_items: List[Dict[str, Any]] = []


    # ----- CLIENTS -----
    if "clients" in dfs:
        _p(25, "analyzing_clients")
        clients_kpis, clients_warnings, clients_plot_abs = analyze_clients(
            dfs["clients"],
            plots_dir_abs=plots_dir_abs,
            year=report.any,
        )
        kpis["clients"] = clients_kpis
        warnings += clients_warnings
        for item in clients_plot_abs:  # (ara serà "items", tot i que el nom variable el canviaràs)
            plot_items.append({
                "key": item["key"],
                "kind": item.get("kind", "image"),
                "title": item.get("title") or item["key"],
                "file": _media_rel(item["file_abs"]),
                "params": item.get("params") or {},
                "source": "clients",
            })
    # ----- RESERVES -----
    if "reserves" in dfs:
        _p(55, "analyzing_reserves")
        reserves_kpis, reserves_warnings, reserves_plot_abs = analyze_reserves(
            dfs["reserves"],
            plots_dir_abs=plots_dir_abs,
            year=report.any,
        )
        kpis["reserves"] = reserves_kpis
        warnings += reserves_warnings
        for item in reserves_plot_abs:
            plot_items.append({
                "key": item["key"],
                "kind": item.get("kind", "image"),
                "title": item.get("title") or item["key"],
                "file": _media_rel(item["file_abs"]),
                "params": item.get("params") or {},
                "source": "reserves",
            })
    _p(90, "writing_artifacts")
    artifacts = write_artifacts(run_dir_abs, kpis, warnings, plot_items)

    if persist:
        _p(95, "persisting")
        analysis_output={
            "kpis": kpis,
            "artifacts": {
                "run_dir": artifacts.run_dir,
                "kpis_path": artifacts.kpis_path,
                "warnings_path": artifacts.warnings_path,
                "plots": artifacts.plots,
            },
        }
        report.analysis_result = analysis_output
        report.save(update_fields=["analysis_result"])

    _p(100, "done")

    if verbose:
        print(f"[run_analysis] report={report_id} run_dir={artifacts.run_dir}")
        print(f"[run_analysis] warnings={len(warnings)} plots={len(plot_items)}")

    return AnalysisOutput(kpis=kpis, warnings=warnings, artifacts=artifacts)
