from django import forms
from django.forms import inlineformset_factory
from .models import AnnualReport, AnnualDataset


PLOT_STYLE_CHOICES = [
    ("seaborn-v0_8", "Seaborn v0.8 (recomanat)"),
    ("default", "Matplotlib default"),
    ("ggplot", "ggplot"),
]


TITLE_WEIGHT_CHOICES = [
    ("normal", "Normal"),
    ("bold", "Negreta"),
]


def _to_float(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _to_int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return int(default)


class AnnualReportForm(forms.ModelForm):
    # ----------------------------
    #   PLOT DEFAULTS (generals)
    # ----------------------------
    plot_style = forms.ChoiceField(
        required=False,
        choices=PLOT_STYLE_CHOICES,
        initial="seaborn-v0_8",
        label="Estil global (plt.style.use)",
    )
    plot_dpi = forms.IntegerField(
        required=False,
        min_value=72,
        max_value=600,
        initial=200,
        label="DPI dels gràfics",
    )
    plot_grid = forms.BooleanField(
        required=False,
        initial=True,
        label="Mostrar graella (grid)",
    )
    plot_grid_alpha = forms.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
        initial=0.3,
        label="Transparència de la graella (alpha)",
    )

    plot_font_family = forms.CharField(
        required=False,
        initial="DejaVu Sans",
        label="Família de font",
    )
    plot_font_size = forms.IntegerField(
        required=False,
        min_value=6,
        max_value=32,
        initial=10,
        label="Mida base de font",
    )
    plot_title_size = forms.IntegerField(
        required=False,
        min_value=8,
        max_value=48,
        initial=14,
        label="Mida del títol",
    )
    plot_title_weight = forms.ChoiceField(
        required=False,
        choices=TITLE_WEIGHT_CHOICES,
        initial="bold",
        label="Gruix del títol",
    )

    # Figura (separem line i pie perquè els teus scripts usen mides diferents)
    figsize_line_w = forms.FloatField(required=False, min_value=2.0, max_value=30.0, initial=9.0, label="Amplada figura (línies)")
    figsize_line_h = forms.FloatField(required=False, min_value=2.0, max_value=30.0, initial=5.0, label="Alçada figura (línies)")
    figsize_pie_w = forms.FloatField(required=False, min_value=2.0, max_value=30.0, initial=9.0, label="Amplada figura (pastís/donut)")
    figsize_pie_h = forms.FloatField(required=False, min_value=2.0, max_value=30.0, initial=7.0, label="Alçada figura (pastís/donut)")

    class Meta:
        model = AnnualReport
        fields = ["instal_lacio_nom", "any"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Inicialitza camps des de config
        cfg = (self.instance.config or {}) if self.instance and self.instance.pk else {}
        pdflt = cfg.get("plot_defaults", {}) or {}

        self.fields["plot_style"].initial = pdflt.get("style", self.fields["plot_style"].initial)
        self.fields["plot_dpi"].initial = pdflt.get("dpi", self.fields["plot_dpi"].initial)
        self.fields["plot_grid"].initial = pdflt.get("grid", self.fields["plot_grid"].initial)
        self.fields["plot_grid_alpha"].initial = pdflt.get("grid_alpha", self.fields["plot_grid_alpha"].initial)

        self.fields["plot_font_family"].initial = pdflt.get("font_family", self.fields["plot_font_family"].initial)
        self.fields["plot_font_size"].initial = pdflt.get("font_size", self.fields["plot_font_size"].initial)
        self.fields["plot_title_size"].initial = pdflt.get("title_size", self.fields["plot_title_size"].initial)
        self.fields["plot_title_weight"].initial = pdflt.get("title_weight", self.fields["plot_title_weight"].initial)

        figsize_line = pdflt.get("figsize_line", [9, 5]) or [9, 5]
        figsize_pie = pdflt.get("figsize_pie", [9, 7]) or [9, 7]
        self.fields["figsize_line_w"].initial = figsize_line[0]
        self.fields["figsize_line_h"].initial = figsize_line[1]
        self.fields["figsize_pie_w"].initial = figsize_pie[0]
        self.fields["figsize_pie_h"].initial = figsize_pie[1]

        # BS4 styling (coherent amb el teu forms.py actual)
        for f in ["instal_lacio_nom", "any"]:
            self.fields[f].widget.attrs.setdefault("class", "form-control form-control-sm")

        # Controls generals: inputs petits
        for f in [
            "plot_style", "plot_dpi", "plot_grid_alpha",
            "plot_font_family", "plot_font_size", "plot_title_size", "plot_title_weight",
            "figsize_line_w", "figsize_line_h", "figsize_pie_w", "figsize_pie_h",
        ]:
            self.fields[f].widget.attrs.setdefault("class", "form-control form-control-sm")

        self.fields["plot_grid"].widget.attrs.setdefault("class", "form-check-input")

    def clean(self):
        cleaned = super().clean()

        plot_defaults = {
            "style": cleaned.get("plot_style") or "seaborn-v0_8",
            "dpi": _to_int(cleaned.get("plot_dpi"), 200),
            "grid": bool(cleaned.get("plot_grid")),
            "grid_alpha": _to_float(cleaned.get("plot_grid_alpha"), 0.3),

            "font_family": (cleaned.get("plot_font_family") or "DejaVu Sans").strip(),
            "font_size": _to_int(cleaned.get("plot_font_size"), 10),
            "title_size": _to_int(cleaned.get("plot_title_size"), 14),
            "title_weight": cleaned.get("plot_title_weight") or "bold",

            "figsize_line": [
                _to_float(cleaned.get("figsize_line_w"), 9),
                _to_float(cleaned.get("figsize_line_h"), 5),
            ],
            "figsize_pie": [
                _to_float(cleaned.get("figsize_pie_w"), 9),
                _to_float(cleaned.get("figsize_pie_h"), 7),
            ],
        }

        # Mantén claus existents si ja hi havia overrides per plot (per no trencar futur)
        prev_cfg = (self.instance.config or {}) if self.instance and self.instance.pk else {}
        plots_overrides = prev_cfg.get("plots", {}) or {}

        cleaned["_config_payload"] = {
            "plot_defaults": plot_defaults,
            "plots": plots_overrides,
        }
        return cleaned


class AnnualDatasetForm(forms.ModelForm):
    class Meta:
        model = AnnualDataset
        fields = ["tipus", "fitxer", "notes"]
        widgets = {
            "tipus": forms.Select(attrs={"class": "form-control form-control-sm"}),
            "notes": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fitxer"].widget.attrs.setdefault("class", "form-control form-control-sm")
        self.fields["fitxer"].required = False  # per poder editar sense re-pujar sempre


class PlotOverrideForm(forms.Form):
    enabled = forms.BooleanField(required=False, initial=True, label="Actiu")
    title = forms.CharField(required=False, label="Títol")
    # opcional: overrides útils
    dpi = forms.IntegerField(required=False, min_value=72, max_value=600, label="DPI (override)")
    grid = forms.BooleanField(required=False, label="Graella (override)")

    def clean(self):
        cleaned = super().clean()

        # construïm només overrides que l’usuari realment ha informat
        payload = {}
        payload["enabled"] = bool(cleaned.get("enabled"))

        title = (cleaned.get("title") or "").strip()
        if title:
            payload["title"] = title

        if cleaned.get("dpi") is not None:
            payload["dpi"] = int(cleaned["dpi"])

        if cleaned.get("grid") is not None:
            payload["grid"] = bool(cleaned.get("grid"))

        cleaned["_plot_override_payload"] = payload
        return cleaned



AnnualDatasetFormSet = inlineformset_factory(
    AnnualReport,
    AnnualDataset,
    form=AnnualDatasetForm,
    extra=0,
    can_delete=True,
)
