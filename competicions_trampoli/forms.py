
from django import forms
from .models import Competicio, Inscripcio
from .models_trampoli import Aparell, CompeticioAparell

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
    class Meta:
        model = CompeticioAparell
        fields = [
            "aparell",
            "ordre",
            "nombre_elements",
            "mode_execucio",
            "te_execucio",
            "te_dificultat",
            "te_tof",
            "te_hd",
            "te_penalitzacio",
            "actiu",
        ]
        widgets = {
            "aparell": forms.Select(attrs={"class": "form-select"}),
            "ordre": forms.NumberInput(attrs={"class": "form-control"}),
            "nombre_elements": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 30}),
            "mode_execucio": forms.Select(attrs={"class": "form-select"}),
            "te_execucio": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "te_dificultat": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "te_tof": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "te_hd": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "te_penalitzacio": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "actiu": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "nombre_elements": "Nombre d’elements (salts)",
            "te_execucio": "Execució",
            "te_dificultat": "Dificultat",
            "te_tof": "ToF",
            "te_hd": "HD",
            "te_penalitzacio": "Penalització",
            "actiu": "Actiu",
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
