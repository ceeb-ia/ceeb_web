
from django import forms
from .models import Competicio, Inscripcio
from .models_trampoli import Aparell, CompeticioAparell
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from .models_scoring import ScoringSchema
import json

class CompeticioForm(forms.ModelForm):
    class Meta:
        model = Competicio
        fields = ['nom', 'data', 'tipus']
        widgets = {
            'data': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'nom': forms.TextInput(attrs={'class': 'form-control'}),
        }

class ImportInscripcionsExcelForm(forms.Form):
    fitxer = forms.FileField()
    sheet = forms.CharField(required=False, help_text="Nom del full (opcional)")



class InscripcioForm(forms.ModelForm):
    # Opcions fixes per `categoria` i `subcategoria`
    PARTITS_NIVEL_ORDER = [
        "SÈNIOR", "JÚNIOR", 'JUVENIL', "CADET", "INFANTIL",
        "PREINFANTIL", "ALEVÍ", "PREALEVÍ", "BENJAMÍ", "PREBENJAMÍ",
        "MENUDETS", "MENUTS",
    ]

    SEXE_CHOICES = ["MASCULÍ", "FEMENÍ"]

    categoria = forms.ChoiceField(
        choices=[("", "---")] + [(v, v) for v in PARTITS_NIVEL_ORDER],
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Categoria",
    )

    subcategoria = forms.ChoiceField(
        choices=[("", "---")] + [(v, v) for v in SEXE_CHOICES],
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Subcategoria",
    )

    class Meta:
        model = Inscripcio
        fields = [
            "nom_i_cognoms",
            "document",
            "sexe",
            "data_naixement",
            "entitat",
            "categoria",
            "subcategoria",
            "grup",
        ]


class CompeticioAparellForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.competicio = kwargs.pop("competicio", None)
        super().__init__(*args, **kwargs)

    def clean_aparell(self):
        aparell = self.cleaned_data.get("aparell")
        if not aparell or not self.competicio:
            return aparell

        exists = CompeticioAparell.objects.filter(
            competicio=self.competicio,
            aparell=aparell,
        ).exists()
        if exists:
            raise ValidationError(
                _("Aquest aparell ja esta afegit a la competicio."),
                code="duplicate_aparell",
            )
        return aparell

    class Meta:
        model = CompeticioAparell
        fields = [
            "aparell",
        ]
        widgets = {
            "aparell": forms.Select(attrs={"class": "form-select"}),
        }



class AparellForm(forms.ModelForm):
    class Meta:
        model = Aparell
        fields = ["codi", "nom", "actiu"]
        widgets = {
            "codi": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: TRAMP, DMT..."}),
            "nom": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nom de l’aparell"}),
            "actiu": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {"codi": "Codi", "nom": "Nom", "actiu": "Actiu"}
        help_texts = {"codi": "Ha de ser únic. Recomanat en majúscules (ex: TRAMP)."}




class ScoringSchemaForm(forms.ModelForm):
    """
    Guardem el schema en un únic camp 'schema_json'.
    El browser envia una cadena, nosaltres la parsejem a dict.
    """
    schema_json = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )

    class Meta:
        model = ScoringSchema
        fields = ["schema_json"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["schema_json"].initial = json.dumps(self.instance.schema or {}, ensure_ascii=False)

    def clean_schema_json(self):
        txt = (self.cleaned_data.get("schema_json") or "").strip()
        if not txt:
            return None
        try:
            data = json.loads(txt)
        except Exception as e:
            raise ValidationError(f"JSON invàlid: {e}")
        if not isinstance(data, dict):
            raise ValidationError("El JSON ha de ser un objecte (dict).")
        return data
