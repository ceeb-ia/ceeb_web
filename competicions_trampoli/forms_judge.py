from django import forms

FIELD_CHOICES_EMPTY = [("", "—")]

class JudgeTokenCreateForm(forms.Form):
    label = forms.CharField(
        required=False,
        max_length=120,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "Ex: Jutge A / Taula 1"})
    )

class PermissionRowForm(forms.Form):
    field_code = forms.CharField(
        required=True,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"})
    )
    judge_index = forms.IntegerField(
        required=True,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control form-control-sm", "style": "width:90px"})
    )
    item_start = forms.IntegerField(
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control form-control-sm", "style": "width:90px"})
    )
    item_count = forms.IntegerField(
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control form-control-sm", "style": "width:90px"})
    )

    def __init__(self, *args, field_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = field_choices or FIELD_CHOICES_EMPTY
        self.fields["field_code"].widget.choices = choices
        self.fields["item_start"].initial = 1