from django import forms


FIELD_CHOICES_EMPTY = [("", "-")]
SCOPE_CHOICES = [
    ("shared", "Compartit"),
    ("member", "Individual"),
]
MEMBER_MODE_CHOICES = [
    ("all", "Tots els membres"),
    ("single", "Només un membre"),
    ("subset", "Diversos membres"),
]
PERMISSION_ROLE_CHOICES = [
    ("standard", "Standard"),
    ("supervisor", "Supervisor"),
]


class JudgeTokenCreateForm(forms.Form):
    label = forms.CharField(
        required=True,
        max_length=120,
        error_messages={
            "required": "El titol/etiqueta es obligatori.",
            "max_length": "El titol/etiqueta no pot superar 120 caracters.",
        },
        widget=forms.TextInput(
            attrs={"class": "form-control form-control-sm", "placeholder": "Ex: Jutge A / Taula 1"}
        ),
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
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    scope = forms.ChoiceField(
        required=False,
        choices=SCOPE_CHOICES,
        initial="shared",
        widget=forms.Select(attrs={"class": "form-select form-select-sm", "style": "width:120px"}),
    )
    role = forms.ChoiceField(
        required=False,
        choices=PERMISSION_ROLE_CHOICES,
        initial="standard",
        widget=forms.Select(attrs={"class": "form-select form-select-sm", "style": "width:130px"}),
    )
    judge_index = forms.IntegerField(
        required=True,
        min_value=1,
        error_messages={
            "required": "Has d'indicar el jutge.",
            "min_value": "El jutge ha de ser 1 o superior.",
        },
        widget=forms.NumberInput(attrs={"class": "form-control form-control-sm", "style": "width:90px"}),
    )
    item_start = forms.IntegerField(
        required=False,
        min_value=1,
        error_messages={"min_value": "Start ha de ser 1 o superior."},
        widget=forms.NumberInput(attrs={"class": "form-control form-control-sm", "style": "width:90px"}),
    )
    item_count = forms.IntegerField(
        required=False,
        min_value=1,
        error_messages={"min_value": "Count ha de ser 1 o superior."},
        widget=forms.NumberInput(attrs={"class": "form-control form-control-sm", "style": "width:90px"}),
    )
    member_mode = forms.ChoiceField(
        required=False,
        choices=MEMBER_MODE_CHOICES,
        initial="all",
        widget=forms.Select(attrs={"class": "form-select form-select-sm", "style": "min-width:150px"}),
    )
    member_slots = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )

    def __init__(self, *args, field_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = field_choices or FIELD_CHOICES_EMPTY
        self.fields["field_code"].choices = choices
        self.fields["item_start"].initial = 1
        self.fields["scope"].initial = "shared"
        self.fields["role"].initial = "standard"
        self.fields["member_mode"].initial = "all"
