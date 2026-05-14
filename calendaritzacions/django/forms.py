"""Forms for the optional Django calendaritzacions app."""

from __future__ import annotations

from django import forms

from calendaritzacions.django.models import CalendarizationRun


class CalendarizationRunForm(forms.ModelForm):
    allowed_extensions = {".xlsx", ".xls", ".csv"}

    class Meta:
        model = CalendarizationRun
        fields = [
            "input_file",
            "engine_name",
            "phase",
            "resource_solver_linkage_mode",
            "resource_solver_level_constraint_mode",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control form-control-sm")

    def clean_input_file(self):
        uploaded = self.cleaned_data["input_file"]
        name = getattr(uploaded, "name", "")
        if "." not in name:
            raise forms.ValidationError("El fitxer ha de tenir extensio.")
        extension = "." + name.rsplit(".", 1)[-1].lower()
        if extension not in self.allowed_extensions:
            allowed = ", ".join(sorted(self.allowed_extensions))
            raise forms.ValidationError(f"Extensio no permesa. Formats acceptats: {allowed}.")
        return uploaded
