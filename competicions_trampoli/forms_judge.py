from django import forms

FIELD_CHOICES_EMPTY = [("", "—")]

class JudgeTokenCreateForm(forms.Form):
    label = forms.CharField(
        required=True,
        max_length=120,
        error_messages={
            "required": "El títol/etiqueta és obligatori.",
            "max_length": "El títol/etiqueta no pot superar 120 caràcters.",
        },
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "Ex: Jutge A / Taula 1"})
    )
    can_record_video = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

class PermissionRowForm(forms.Form):
    field_code = forms.ChoiceField(
        required=True,
        error_messages={"required": "Has de seleccionar un camp."},
        widget=forms.Select(attrs={"class": "form-select form-select-sm"})
    )
    judge_index = forms.IntegerField(
        required=True,
        min_value=1,
        error_messages={
            "required": "Has d'indicar el jutge.",
            "min_value": "El jutge ha de ser 1 o superior.",
        },
        widget=forms.NumberInput(attrs={"class": "form-control form-control-sm", "style": "width:90px"})
    )
    item_start = forms.IntegerField(
        required=False,
        min_value=1,
        error_messages={"min_value": "Start ha de ser 1 o superior."},
        widget=forms.NumberInput(attrs={"class": "form-control form-control-sm", "style": "width:90px"})
    )
    item_count = forms.IntegerField(
        required=False,
        min_value=1,
        error_messages={"min_value": "Count ha de ser 1 o superior."},
        widget=forms.NumberInput(attrs={"class": "form-control form-control-sm", "style": "width:90px"})
    )

    def __init__(self, *args, field_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = field_choices or FIELD_CHOICES_EMPTY
        self.fields["field_code"].choices = choices
        self.fields["item_start"].initial = 1
