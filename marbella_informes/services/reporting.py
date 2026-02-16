# services/reporting.py
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from ..models import AnnualReport

# ✅ RECOMANAT: crea aquest model per editar subseccions individualment
# from ..models import AnnualReportSection


# -------------------------
# 0) Config i helpers Ollama
# -------------------------

DEFAULT_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")


SYSTEM_PROMPT = (
    "Ets un analista que redacta informes anuals professionals.\n"
    "Normes estrictes:\n"
    "- Escriu en català formal.\n"
    "- No inventis dades.\n"
    "- Usa exclusivament els KPIs proporcionats.\n"
    "- Si falta una dada, indica-ho explícitament.\n"
    "- No introdueixis percentatges, totals o comparatives que no siguin al JSON.\n"
    "- No facis referències a 'JSON', 'payload', ni a la teva instrucció.\n"
)


def _ollama_chat(
    base_url: str,
    model: str,
    messages: list[dict],
    *,
    temperature: float = 0.1,
    timeout_s: int = 180,
) -> str:
    """
    Crida Ollama /api/chat (no streaming) i retorna text.
    """
    r = requests.post(
        f"{base_url.rstrip('/')}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "options": {"temperature": temperature},
            "stream": False,
        },
        timeout=timeout_s,
    )
    r.raise_for_status()
    data = r.json()
    return data["message"]["content"]


def _clamp_progress(p: int) -> int:
    return max(0, min(100, int(p)))


# -------------------------
# 1) Specs (seccions/subseccions)
# -------------------------

@dataclass(frozen=True)
class FigureSpec:
    """
    Identifica figures (plots) que ja tens a analysis_result['artifacts']['plots'].
    key hauria de coincidir amb p.get('key').
    """
    key: str
    label: Optional[str] = None  # "Gràfic 1", etc.
    caption: Optional[str] = None


@dataclass(frozen=True)
class KPIBlockSpec:
    """
    Identifica el bloc KPI que vols usar (path dins analysis_result['kpis']).
    Ex: ("reserves",) -> kpis['reserves'].
    """
    path: Tuple[str, ...]


@dataclass(frozen=True)
class SubsectionSpec:
    key: str
    title: str
    kpi_block: KPIBlockSpec
    figures: List[FigureSpec] = field(default_factory=list)

    # Format guiat per template (taules/estructura)
    # kpi_table: llista de files (label, value_key) que el context builder convertirà en valors “humans”
    kpi_table: List[Tuple[str, str]] = field(default_factory=list)

    # Writer function per subsecció (micro-prompt)
    prompt_fn: Optional[Callable[[Dict[str, Any]], str]] = None


@dataclass(frozen=True)
class SectionSpec:
    key: str
    title: str
    subsections: List[SubsectionSpec]


def build_specs() -> List[SectionSpec]:
    """
    Aquí reflecteixes l’estructura del teu informe real (DOCX).
    Comences per: Serveis i activitats -> Reserva d’espais.
    """
    return [
        SectionSpec(
            key="services_activities",
            title="Serveis i activitats",
            subsections=[
                SubsectionSpec(
                    key="services_activities.reserva_espais",
                    title="Reserva d’espais",
                    kpi_block=KPIBlockSpec(path=("reserves",)),
                    figures=[
                        # Ajusta aquestes keys segons els teus plots reals
                        FigureSpec(key="reserves.distribucio_hores_espais", label="Gràfic 1"),
                        FigureSpec(key="reserves.mensual_2021_2024", label="Gràfic 2"),
                    ],
                    # Taula tipo DOCX: “Entitats / Esports / Hores totals”
                    # IMPORTANT: si no tens “entitats” als KPIs, el context ho marcarà com “No disponible”
                    kpi_table=[
                        ("Entitats", "reserves_total_entitats_uniques"),
                        ("Esports", "reserves_total_esports_uniques"),
                        ("Hores totals", "reserves_total_hores"),
                    ],
                    prompt_fn=None,  # la lliguem al registry més avall
                )
            ],
        ),
        # Afegeix altres seccions/subseccions quan les tinguis:
        # SectionSpec(key="clients", title="Clients", subsections=[...]),
        # SectionSpec(key="conclusions", title="Conclusions", subsections=[...]),
    ]


# -------------------------
# 2) Plot helpers (artifacts)
# -------------------------

def _index_plots(plots: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Converteix llista de plots -> dict per key.
    Cada plot al teu sistema sol tenir: key, title, file, source.
    """
    idx = {}
    for p in plots or []:
        k = p.get("key")
        if k:
            idx[k] = p
    return idx


def _resolve_figure_context(plot_idx: Dict[str, Dict[str, Any]], fig: FigureSpec) -> Dict[str, Any]:
    p = plot_idx.get(fig.key) or {}
    # p.get("file") pot ser un path relatiu a MEDIA_ROOT o una ruta ja resolta.
    return {
        "key": fig.key,
        "label": fig.label,
        "caption": fig.caption,
        "title": p.get("title") or fig.key,
        "file": p.get("file"),      # el template farà MEDIA_URL + file
        "source": p.get("source"),
        "exists": bool(p),
    }


# -------------------------
# 3) Context builder
# -------------------------

def _get_kpi_block(kpis: Dict[str, Any], path: Tuple[str, ...]) -> Dict[str, Any]:
    cur: Any = kpis or {}
    for part in path:
        if not isinstance(cur, dict):
            return {}
        cur = cur.get(part)
        if cur is None:
            return {}
    return cur if isinstance(cur, dict) else {}


def _format_number(value: Any) -> str:
    """
    Format simple per taules. Ajusta si vols decimals, separadors, etc.
    """
    if value is None:
        return "No disponible"
    if isinstance(value, bool):
        return "Sí" if value else "No"
    if isinstance(value, int):
        return f"{value}"
    if isinstance(value, float):
        # 2 decimals per hores, etc. (simple)
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def build_subsection_context(
    report: AnnualReport,
    out: Dict[str, Any],
    spec: SubsectionSpec,
) -> Dict[str, Any]:
    """
    Extreu només el necessari per aquella subsecció (KPIs + figures + taula).
    """
    kpis = out.get("kpis") or {}
    artifacts = out.get("artifacts") or {}
    plots = artifacts.get("plots") or []

    kpi_block = _get_kpi_block(kpis, spec.kpi_block.path)
    plot_idx = _index_plots(plots)

    figures_ctx = [_resolve_figure_context(plot_idx, f) for f in spec.figures]

    # Taula de KPIs (label -> value)
    table_rows = []
    for label, kpi_key in spec.kpi_table:
        raw = kpi_block.get(kpi_key)
        table_rows.append({"label": label, "key": kpi_key, "value": _format_number(raw)})

    # Un “resum curt” pel prompt (ajuda a generar la frase inicial)
    derived = {
        "instal_lacio": report.instal_lacio_nom,
        "any": report.any,
        "kpi_block_path": ".".join(spec.kpi_block.path),
        "missing_kpis": [r["key"] for r in table_rows if r["value"] == "No disponible"],
    }

    return {
        "report": {"instal_lacio": report.instal_lacio_nom, "any": report.any},
        "subsection": {"key": spec.key, "title": spec.title},
        "kpis": kpi_block,                 # només reserves, en aquest cas
        "kpi_table": table_rows,           # ja formatat per template i per prompt
        "figures": figures_ctx,            # amb exists/file/title/label
        "derived": derived,
    }


# -------------------------
# 4) Prompt functions (1 per subsecció important)
# -------------------------

def prompt_reserva_espais(ctx: Dict[str, Any]) -> str:
    """
    Micro-prompt curt i amb el format del teu DOCX:
    - 1 frase resum amb dades clau
    - després 1-2 paràgrafs d’interpretació
    - menció a figures si existeixen (Gràfic 1/2)
    """
    report = ctx["report"]
    table = ctx["kpi_table"]
    figs = ctx["figures"]
    kpis = ctx["kpis"]
    missing = ctx["derived"]["missing_kpis"]

    # Figures disponibles
    fig_lines = []
    for f in figs:
        if f["exists"]:
            # etiqueta tipus “Gràfic 1”
            tag = f["label"] or f["key"]
            fig_lines.append(f"- {tag}: {f['title']} (key={f['key']})")
    fig_block = "\n".join(fig_lines) if fig_lines else "- (No hi ha figures disponibles per aquesta subsecció)"

    # Taula (ja formatada)
    table_block = "\n".join([f"- {r['label']}: {r['value']} (kpi={r['key']})" for r in table])

    # Nota de limitacions (si falten KPIs)
    limitations = ""
    if missing:
        limitations = (
            "\nLimitacions:\n"
            f"- Alguns KPIs no estan disponibles: {', '.join(missing)}. "
            "Si calen per redactar (p. ex. entitats regulars), indica-ho explícitament sense inventar.\n"
        )

    return f"""
Redacta la subsecció: "{ctx['subsection']['title']}" dins la secció "Serveis i activitats" per a {report['instal_lacio']} ({report['any']}).

Estructura OBLIGATÒRIA:
1) Una primera frase (1 línia) amb síntesi quantitativa (hores totals i nombre d'esports; i entitats si existeix).
2) Després, 2 paràgrafs curts (3-5 línies cadascun) amb interpretació (volum d’activitat, diversitat d’esports, i lectura prudent).
3) Tanca amb una frase breu que referenciï les figures disponibles (ex: "Vegeu Gràfic 1 i Gràfic 2"), només si existeixen.

Dades disponibles (taula KPI):
{table_block}

Figures disponibles:
{fig_block}
{limitations}

KPIs complets del bloc "reserves" (per si necessites més context):
{json.dumps(kpis, ensure_ascii=False)}
""".strip()


PROMPT_REGISTRY: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "services_activities.reserva_espais": prompt_reserva_espais,
}


# -------------------------
# 5) Persistence (seccions editables)
# -------------------------

def upsert_subsection_content(report: AnnualReport, key: str, title: str, content: str, source: str = "llm") -> None:
    """
    Desa el text per subsecció.
    ✅ Ideal: AnnualReportSection (1 fila per subsecció, editable)
    """
    # Si encara no has creat el model, deixa aquesta funció com a TODO.
    # Quan el creïs, descomenta l'import al principi i el codi següent.

    from ..models import AnnualReportSection
    AnnualReportSection.objects.update_or_create(
        report=report,
        key=key,
        defaults={"title": title, "content": content, "source": source},
    )



def fetch_subsections_for_render(report: AnnualReport) -> List[Dict[str, Any]]:
    """
    Recupera subseccions per render.
    ✅ Ideal: AnnualReportSection
    """
    from ..models import AnnualReportSection
    qs = AnnualReportSection.objects.filter(report=report).order_by("key")
    return [{"key": s.key, "title": s.title, "content": s.content, "source": s.source} for s in qs]



# -------------------------
# 6) Writer
# -------------------------

def write_subsection(
    ctx: Dict[str, Any],
    *,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    model: str = DEFAULT_OLLAMA_MODEL,
    temperature: float = 0.1,
) -> str:
    key = ctx["subsection"]["key"]
    prompt_fn = PROMPT_REGISTRY.get(key)
    if not prompt_fn:
        raise ValueError(f"No hi ha prompt_fn registrat per la subsecció: {key}")

    user_prompt = prompt_fn(ctx)

    text = _ollama_chat(
        base_url=base_url,
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )

    # Neteja suau: evita encapçalaments duplicats o cometes rares
    text = text.strip()
    text = re.sub(r"^\s*#+\s*", "", text)  # si ve amb Markdown headers
    return text.strip()


# -------------------------
# 7) PDF Render + Save
# -------------------------

def render_pdf(report: AnnualReport, out: Dict[str, Any]) -> bytes:
    """
    Renderitza el PDF des de template.
    Important: el template ha de consumir subseccions guardades + plots.
    """
    artifacts = out.get("artifacts") or {}
    plots = artifacts.get("plots") or []
    plot_idx = _index_plots(plots)

    # Recupera subseccions desades (editable)
    subsections = fetch_subsections_for_render(report)

    # Enriquim subseccions amb figures resoltes des dels specs (opcional)
    # Aquí fem un mapa de key->figures segons build_specs()
    figures_by_subkey: Dict[str, List[Dict[str, Any]]] = {}
    for section in build_specs():
        for sub in section.subsections:
            figures_by_subkey[sub.key] = [_resolve_figure_context(plot_idx, f) for f in sub.figures]

    for s in subsections:
        s["figures"] = figures_by_subkey.get(s["key"], [])

    html = render_to_string(
        "annual_report_pdf.html",
        {
            "report": report,
            "subsections": subsections,
            "all_plots": plots,
        },
    )

    from weasyprint import HTML
    return HTML(string=html, base_url=settings.MEDIA_ROOT).write_pdf()


def save_pdf_to_report(report: AnnualReport, pdf_bytes: bytes) -> None:
    rel_dir = os.path.join("marbella", str(report.any), "final_reports")
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    filename = f"informe_{report.instal_lacio_nom}_{report.any}.pdf"
    abs_path = os.path.join(abs_dir, filename)

    with open(abs_path, "wb") as f:
        f.write(pdf_bytes)

    # Si uses FileField:
    report.report_file.name = os.path.join(rel_dir, filename)
    report.report_generated_at = timezone.now()
    report.save(update_fields=["report_file", "report_generated_at"])


# -------------------------
# 8) Main entry: generate_report(report_id)
# -------------------------

def generate_report(report_id: int, progress_cb=None) -> None:
    """
    Pipeline:
    - valida analysis_result
    - iterar specs -> construir context -> escriure subsecció -> guardar
    - render pdf (template) -> guardar fitxer
    """
    def _p(pct: int, status: str):
        if progress_cb:
            progress_cb(_clamp_progress(pct), status)

    report = AnnualReport.objects.get(pk=report_id)
    if not report.analysis_result:
        raise ValueError("No hi ha analysis_result. Executa l'anàlisi abans de generar l'informe.")

    out = report.analysis_result

    specs = build_specs()
    all_subs: List[SubsectionSpec] = [sub for sec in specs for sub in sec.subsections]
    if not all_subs:
        raise ValueError("No hi ha subseccions definides a build_specs().")

    _p(5, "report_prepare")

    # 1) Escriure i guardar subseccions (editable)
    _p(15, "report_writing_sections")
    for i, sub_spec in enumerate(all_subs):
        ctx = build_subsection_context(report, out, sub_spec)

        # assigna prompt_fn si ve per registry (o al spec)
        if sub_spec.prompt_fn is None and sub_spec.key in PROMPT_REGISTRY:
            # no podem mutar dataclass frozen; simplement usem registry a write_subsection
            pass

        text = write_subsection(ctx)

        # Guarda cada subsecció separadament (per edició individual)
        upsert_subsection_content(
            report=report,
            key=sub_spec.key,
            title=sub_spec.title,
            content=text,
            source="llm",
        )

        # progress 15..65
        pct = 15 + int(50 * (i + 1) / len(all_subs))
        _p(pct, f"report_written:{sub_spec.key}")

    # 2) Render PDF
    _p(70, "report_render_pdf")
    pdf_bytes = render_pdf(report, out)

    # 3) Guardar fitxer
    _p(90, "report_save_pdf")
    save_pdf_to_report(report, pdf_bytes)

    _p(100, "report_done")
