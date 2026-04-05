import json
from collections import OrderedDict

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import Competicio, Equip, EquipContext, Inscripcio, InscripcioEquipAssignacio
from .models.competicio import Aparell, CompeticioAparell
from .models.scoring import ScoringSchema
from .services.shared.competition_groups import get_competicio_groups, group_label
from .services.teams.equip_contexts import (
    BASE_EQUIP_CONTEXT_DESCRIPTION,
    BASE_EQUIP_CONTEXT_NAME,
    NATIVE_EQUIP_CONTEXT_CODE,
    get_equip_context,
    get_equip_context_payload,
    normalize_equip_context_code,
    resolve_inscripcio_equip,
)
from .services.inscripcions.import_excel import (
    _build_value_aliases,
    _canonicalize_text_field,
    _clean_text,
    _norm_text_key,
)
from .services.scoring.scoring_schema_validation import validate_schema


def _text_sort_key(value):
    return (_norm_text_key(value) or "", _clean_text(value) or "")


class CompeticioForm(forms.ModelForm):
    class Meta:
        model = Competicio
        fields = ["nom", "data", "tipus"]
        widgets = {
            "data": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "nom": forms.TextInput(attrs={"class": "form-control"}),
        }


class ImportInscripcionsExcelForm(forms.Form):
    fitxer = forms.FileField()
    sheet = forms.CharField(required=False, help_text="Nom del full (opcional)")

    def clean_fitxer(self):
        fitxer = self.cleaned_data["fitxer"]
        filename = str(getattr(fitxer, "name", "") or "").strip().lower()
        allowed_exts = (".xlsx", ".xlsm", ".xltx", ".xltm")
        if not filename.endswith(allowed_exts):
            raise ValidationError("Cal pujar un fitxer Excel compatible amb OpenXML (.xlsx/.xlsm).")
        return fitxer


class InscripcioForm(forms.ModelForm):
    ENTITAT_ALTRES_VALUE = "__other__"
    OPTIONAL_BUILTIN_CODES = ("document", "sexe", "data_naixement")
    TEXT_CANONICAL_FIELDS = ("entitat", "categoria", "subcategoria", "sexe")
    TEXT_SELECTOR_FIELDS = ("entitat", "categoria", "subcategoria")
    TEXT_SELECTOR_CONFIG = {
        "entitat": {
            "choice_name": "entitat_choice",
            "other_name": "entitat_altres",
            "label": "Entitat",
            "empty_label": "Sense entitat",
            "other_label": "Altra entitat",
            "placeholder": "Escriu l'entitat si no surt al llistat",
            "error_message": "Cal indicar l'entitat si tries Altres.",
        },
        "categoria": {
            "choice_name": "categoria_choice",
            "other_name": "categoria_altres",
            "label": "Categoria",
            "empty_label": "Sense categoria",
            "other_label": "Altra categoria",
            "placeholder": "Escriu la categoria si no surt al llistat",
            "error_message": "Cal indicar la categoria si tries Altres.",
        },
        "subcategoria": {
            "choice_name": "subcategoria_choice",
            "other_name": "subcategoria_altres",
            "label": "Subcategoria",
            "empty_label": "Sense subcategoria",
            "other_label": "Altra subcategoria",
            "placeholder": "Escriu la subcategoria si no surt al llistat",
            "error_message": "Cal indicar la subcategoria si tries Altres.",
        },
    }
    EQUIP_SELECTOR_CONFIG = {
        "choice_name": "equip_choice",
        "other_name": "equip_altres",
        "label": "Equip (Base)",
        "empty_label": "Sense equip",
        "other_label": "Altre equip",
        "placeholder": "Escriu l'equip si no surt al llistat",
        "error_message": "Cal indicar l'equip si tries Altres.",
    }

    class Meta:
        model = Inscripcio
        fields = [
            "nom_i_cognoms",
            "document",
            "sexe",
            "data_naixement",
            "categoria",
            "subcategoria",
        ]
        widgets = {
            "nom_i_cognoms": forms.TextInput(attrs={"class": "form-control"}),
            "document": forms.TextInput(attrs={"class": "form-control"}),
            "sexe": forms.TextInput(attrs={"class": "form-control"}),
            "data_naixement": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "categoria": forms.TextInput(attrs={"class": "form-control"}),
            "subcategoria": forms.TextInput(attrs={"class": "form-control"}),
        }
        labels = {
            "nom_i_cognoms": "Nom i cognoms",
            "document": "Document",
            "sexe": "Sexe",
            "data_naixement": "Data naixement",
            "categoria": "Categoria",
            "subcategoria": "Subcategoria",
        }

    def __init__(self, *args, **kwargs):
        self.competicio = kwargs.pop("competicio", None)
        self.team_context_code = normalize_equip_context_code(kwargs.pop("team_context_code", None))
        super().__init__(*args, **kwargs)
        if self.competicio is None:
            self.competicio = getattr(self.instance, "competicio", None)
        if self.competicio is None:
            raise ValueError("InscripcioForm requires a competicio instance.")

        self.team_context = get_equip_context(self.competicio, self.team_context_code)
        if self.team_context is None:
            self.team_context_code = NATIVE_EQUIP_CONTEXT_CODE
            self.team_context = get_equip_context(self.competicio, self.team_context_code)
        self.team_context_is_native = self.team_context_code == NATIVE_EQUIP_CONTEXT_CODE
        self.team_context_payload = next(
            (item for item in get_equip_context_payload(self.competicio) if item["code"] == self.team_context_code),
            {
                "code": self.team_context_code,
                "nom": BASE_EQUIP_CONTEXT_NAME,
                "description": BASE_EQUIP_CONTEXT_DESCRIPTION,
                "is_native": True,
            },
        )
        self.team_context_label = (
            str(self.team_context_payload.get("nom") or BASE_EQUIP_CONTEXT_NAME).strip()
            or BASE_EQUIP_CONTEXT_NAME
        )
        self.current_native_equip = (
            resolve_inscripcio_equip(
                self.instance,
                context_code=NATIVE_EQUIP_CONTEXT_CODE,
                fallback=None,
            )
            if getattr(self.instance, "pk", None)
            else None
        )
        self.current_base_equip = self.current_native_equip
        self.current_context_assignment = self._get_current_context_assignment()
        self.current_equip = getattr(self.current_context_assignment, "equip", None)
        if self.current_equip is None and self.team_context_is_native:
            self.current_equip = self.current_base_equip

        self.schema_columns = self._get_schema_columns()
        self.extra_field_map = OrderedDict()
        self.extra_field_names = []
        self._text_aliases = _build_value_aliases(self.competicio)
        self._text_canon_map = self._build_text_canon_map()
        self._group_choice_map = OrderedDict()
        self._equip_choice_map = OrderedDict()

        self._configure_builtin_fields()
        for field_name in self.TEXT_SELECTOR_FIELDS:
            self._configure_text_selector_field(field_name)
        self._configure_group_field()
        self._configure_equip_field()
        self._configure_extra_fields()

        self.basic_field_names = self._build_basic_field_names()
        self.order_fields(self.basic_field_names + self.extra_field_names)
        self.other_wrapper_field_names = self._build_other_wrapper_field_names()
        self.full_width_basic_field_names = ["nom_i_cognoms", *self.other_wrapper_field_names]
        self.show_altres_fields = self._build_show_altres_fields()

    def _get_current_context_assignment(self):
        if not getattr(self.instance, "pk", None) or self.team_context is None:
            return None
        return (
            InscripcioEquipAssignacio.objects
            .filter(
                competicio=self.competicio,
                context=self.team_context,
                inscripcio=self.instance,
            )
            .select_related("equip")
            .first()
        )

    def _get_schema_columns(self):
        schema = self.competicio.inscripcions_schema or {}
        columns = schema.get("columns") or []
        if not isinstance(columns, list):
            return []
        return [col for col in columns if isinstance(col, dict) and str(col.get("code") or "").strip()]

    def _build_text_canon_map(self):
        canon_map = {field: {} for field in self.TEXT_CANONICAL_FIELDS}
        qs = Inscripcio.objects.filter(competicio=self.competicio)
        for field in self.TEXT_CANONICAL_FIELDS:
            raw_values = sorted(qs.values_list(field, flat=True), key=_text_sort_key)
            for raw_value in raw_values:
                _canonicalize_text_field(
                    field,
                    raw_value,
                    aliases=self._text_aliases,
                    canon_map=canon_map,
                )
        return canon_map

    def _canonicalize_text(self, field, value):
        return _canonicalize_text_field(
            field,
            value,
            aliases=self._text_aliases,
            canon_map=self._text_canon_map,
        )

    def _configure_builtin_fields(self):
        schema_builtin_codes = {
            str(col.get("code") or "").strip()
            for col in self.schema_columns
            if (col.get("kind") or "") == "builtin"
        }
        for field_name in list(self.fields.keys()):
            if field_name == "nom_i_cognoms":
                continue
            if field_name not in schema_builtin_codes:
                self.fields.pop(field_name, None)

    def _get_text_selector_choices(self, field_name):
        config = self.TEXT_SELECTOR_CONFIG[field_name]
        options = OrderedDict()
        raw_values = sorted(
            Inscripcio.objects.filter(competicio=self.competicio).values_list(field_name, flat=True),
            key=_text_sort_key,
        )
        for raw_value in raw_values:
            canonical = self._canonicalize_text(field_name, raw_value)
            canonical_key = _norm_text_key(canonical)
            if canonical and canonical_key and canonical_key not in options:
                options[canonical_key] = canonical

        choices = [("", config["empty_label"])]
        choices.extend((value, value) for value in options.values())
        choices.append((self.ENTITAT_ALTRES_VALUE, "Altres"))
        return choices

    def _configure_text_selector_field(self, field_name):
        config = self.TEXT_SELECTOR_CONFIG[field_name]
        choices = self._get_text_selector_choices(field_name)
        option_values = {value for value, _label in choices if value not in ("", self.ENTITAT_ALTRES_VALUE)}
        current_value = _clean_text(getattr(self.instance, field_name, None))
        canonical_current = self._canonicalize_text(field_name, current_value)

        initial_choice = ""
        initial_other = ""
        if canonical_current and canonical_current in option_values:
            initial_choice = canonical_current
        elif current_value:
            initial_choice = self.ENTITAT_ALTRES_VALUE
            initial_other = current_value

        self.fields.pop(field_name, None)

        self.fields[config["choice_name"]] = forms.ChoiceField(
            required=False,
            label=config["label"],
            choices=choices,
            initial=initial_choice,
            widget=forms.Select(
                attrs={
                    "class": "form-select",
                    "data-other-target": f"{config['other_name']}-wrapper",
                }
            ),
        )
        self.fields[config["other_name"]] = forms.CharField(
            required=False,
            label=config["other_label"],
            initial=initial_other,
            widget=forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": config["placeholder"],
                }
            ),
        )

    def _configure_group_field(self):
        groups = list(get_competicio_groups(self.competicio, include_inactive=False))
        seen_group_ids = {group.id for group in groups}
        current_group = getattr(self.instance, "grup_competicio", None)
        if current_group is not None and current_group.id not in seen_group_ids:
            groups.append(current_group)

        self._group_choice_map = OrderedDict((str(group.id), group) for group in groups)
        choices = [("", "Sense grup")]
        choices.extend((value, group_label(group)) for value, group in self._group_choice_map.items())

        self.fields["grup_competicio_choice"] = forms.ChoiceField(
            required=False,
            label="Grup",
            choices=choices,
            initial=str(self.instance.grup_competicio_id or ""),
            widget=forms.Select(attrs={"class": "form-select"}),
        )

    def _configure_equip_field(self):
        config = dict(self.EQUIP_SELECTOR_CONFIG)
        config["label"] = (
            "Equip (Base)"
            if self.team_context_is_native
            else f"Equip ({self.team_context_label})"
        )
        equips = list(
            Equip.objects
            .filter(competicio=self.competicio, context=self.team_context)
            .order_by("nom", "id")
        )
        seen_equip_ids = {equip.id for equip in equips}
        current_equip = self.current_equip
        if current_equip is not None and current_equip.id not in seen_equip_ids:
            equips.append(current_equip)

        self._equip_choice_map = OrderedDict((str(equip.id), equip) for equip in equips)
        choices = [("", config["empty_label"])]
        choices.extend((value, equip.nom) for value, equip in self._equip_choice_map.items())
        choices.append((self.ENTITAT_ALTRES_VALUE, "Altres"))

        current_equip_name = _clean_text(getattr(current_equip, "nom", None))
        initial_choice = ""
        initial_other = ""
        if current_equip is not None and str(current_equip.id) in self._equip_choice_map:
            initial_choice = str(current_equip.id)
        elif current_equip_name:
            initial_choice = self.ENTITAT_ALTRES_VALUE
            initial_other = current_equip_name

        self.fields[config["choice_name"]] = forms.ChoiceField(
            required=False,
            label=config["label"],
            choices=choices,
            initial=initial_choice,
            widget=forms.Select(
                attrs={
                    "class": "form-select",
                    "data-other-target": f"{config['other_name']}-wrapper",
                }
            ),
        )
        self.fields[config["other_name"]] = forms.CharField(
            required=False,
            label=config["other_label"],
            initial=initial_other,
            widget=forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": config["placeholder"],
                }
            ),
        )

    def _configure_extra_fields(self):
        extra = getattr(self.instance, "extra", None) or {}
        for column in self.schema_columns:
            kind = column.get("kind") or "extra"
            if kind != "extra":
                continue
            code = str(column.get("code") or "").strip()
            if not code:
                continue
            field_name = f"extra__{code}"
            self.extra_field_map[field_name] = code
            self.extra_field_names.append(field_name)
            self.fields[field_name] = forms.CharField(
                required=False,
                label=str(column.get("label") or code).strip() or code,
                initial=extra.get(code, ""),
                widget=forms.TextInput(attrs={"class": "form-control"}),
            )

    def _build_basic_field_names(self):
        field_names = [
            "nom_i_cognoms",
            "entitat_choice",
            "entitat_altres",
            "categoria_choice",
            "categoria_altres",
            "subcategoria_choice",
            "subcategoria_altres",
        ]
        field_names.extend(code for code in self.OPTIONAL_BUILTIN_CODES if code in self.fields)
        field_names.append("grup_competicio_choice")
        field_names.extend(["equip_choice", "equip_altres"])
        return field_names

    def _build_other_wrapper_field_names(self):
        names = [config["other_name"] for config in self.TEXT_SELECTOR_CONFIG.values()]
        names.append(self.EQUIP_SELECTOR_CONFIG["other_name"])
        return names

    def _is_other_selected(self, choice_name):
        if self.is_bound:
            return self.data.get(self.add_prefix(choice_name)) == self.ENTITAT_ALTRES_VALUE
        field = self.fields.get(choice_name)
        return bool(field and field.initial == self.ENTITAT_ALTRES_VALUE)

    def _build_show_altres_fields(self):
        show_map = {}
        for config in self.TEXT_SELECTOR_CONFIG.values():
            show_map[config["other_name"]] = self._is_other_selected(config["choice_name"])
        show_map[self.EQUIP_SELECTOR_CONFIG["other_name"]] = self._is_other_selected(
            self.EQUIP_SELECTOR_CONFIG["choice_name"]
        )
        return show_map

    def _clean_text_selector_value(self, cleaned_data, field_name):
        config = self.TEXT_SELECTOR_CONFIG[field_name]
        choice_name = config["choice_name"]
        other_name = config["other_name"]
        selected_value = cleaned_data.get(choice_name) or ""
        other_value = _clean_text(cleaned_data.get(other_name))

        if selected_value == self.ENTITAT_ALTRES_VALUE:
            if not other_value:
                self.add_error(other_name, config["error_message"])
                cleaned_data[other_name] = ""
                return None
            cleaned_data[other_name] = other_value
            return self._canonicalize_text(field_name, other_value)
        if selected_value:
            cleaned_data[other_name] = ""
            return self._canonicalize_text(field_name, selected_value)

        cleaned_data[other_name] = ""
        return None

    def _clean_equip_value(self, cleaned_data):
        config = self.EQUIP_SELECTOR_CONFIG
        choice_name = config["choice_name"]
        other_name = config["other_name"]
        selected_value = cleaned_data.get(choice_name) or ""
        other_value = _clean_text(cleaned_data.get(other_name))

        if selected_value == self.ENTITAT_ALTRES_VALUE:
            if not other_value:
                self.add_error(other_name, config["error_message"])
                cleaned_data[other_name] = ""
                cleaned_data["resolved_equip"] = None
                cleaned_data["resolved_equip_name"] = ""
                return
            cleaned_data[other_name] = other_value
            cleaned_data["resolved_equip"] = None
            cleaned_data["resolved_equip_name"] = other_value
            return

        cleaned_data["resolved_equip_name"] = ""
        cleaned_data[other_name] = ""
        if not selected_value:
            cleaned_data["resolved_equip"] = None
            return

        resolved_equip = self._equip_choice_map.get(str(selected_value))
        if resolved_equip is None:
            self.add_error(choice_name, "L'equip seleccionat no es valid.")
        cleaned_data["resolved_equip"] = resolved_equip

    def _persist_contextual_equip_assignment(self, instance, equip):
        if self.team_context is None:
            return

        existing = (
            InscripcioEquipAssignacio.objects
            .filter(
                competicio=self.competicio,
                context=self.team_context,
                inscripcio=instance,
            )
            .first()
        )
        if equip is None:
            if existing is not None:
                existing.delete()
            return

        if existing is None:
            InscripcioEquipAssignacio.objects.create(
                competicio=self.competicio,
                context=self.team_context,
                inscripcio=instance,
                equip=equip,
                origen=InscripcioEquipAssignacio.Origen.MANUAL,
                criteri={},
            )
            return

        if existing.equip_id != equip.id or existing.origen != InscripcioEquipAssignacio.Origen.MANUAL or existing.criteri:
            existing.equip = equip
            existing.origen = InscripcioEquipAssignacio.Origen.MANUAL
            existing.criteri = {}
            existing.save(update_fields=["equip", "origen", "criteri", "updated_at"])

    def clean(self):
        cleaned_data = super().clean()

        cleaned_data["nom_i_cognoms"] = _clean_text(cleaned_data.get("nom_i_cognoms"))
        if "document" in self.fields:
            cleaned_data["document"] = _clean_text(cleaned_data.get("document"))
        if "sexe" in self.fields:
            cleaned_data["sexe"] = self._canonicalize_text("sexe", cleaned_data.get("sexe"))

        for field_name in self.TEXT_SELECTOR_FIELDS:
            cleaned_data[field_name] = self._clean_text_selector_value(cleaned_data, field_name)
        self._clean_equip_value(cleaned_data)

        group_choice = cleaned_data.get("grup_competicio_choice") or ""
        resolved_group = None
        if group_choice:
            resolved_group = self._group_choice_map.get(str(group_choice))
            if resolved_group is None:
                self.add_error("grup_competicio_choice", "El grup seleccionat no es valid.")
        cleaned_data["resolved_grup_competicio"] = resolved_group

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.entitat = self.cleaned_data.get("entitat")
        instance.categoria = self.cleaned_data.get("categoria")
        instance.subcategoria = self.cleaned_data.get("subcategoria")

        resolved_group = self.cleaned_data.get("resolved_grup_competicio")
        if resolved_group is None:
            instance.grup_competicio = None
            instance.grup = None
        else:
            instance.grup_competicio = resolved_group
            instance.grup = resolved_group.display_num

        resolved_equip = self.cleaned_data.get("resolved_equip")
        resolved_equip_name = _clean_text(self.cleaned_data.get("resolved_equip_name"))
        if resolved_equip_name:
            resolved_equip, _created = Equip.objects.get_or_create(
                competicio=self.competicio,
                context=self.team_context,
                nom=resolved_equip_name,
                defaults={"origen": Equip.Origen.MANUAL, "criteri": {}},
            )

        next_extra = dict(getattr(instance, "extra", None) or {})
        for field_name, code in self.extra_field_map.items():
            value = _clean_text(self.cleaned_data.get(field_name))
            if value is None:
                next_extra.pop(code, None)
            else:
                next_extra[code] = value
        instance.extra = next_extra

        if commit:
            instance.save()
            self._persist_contextual_equip_assignment(instance, resolved_equip)
        return instance


class CompeticioAparellForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.competicio = kwargs.pop("competicio", None)
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        qs = Aparell.objects.filter(actiu=True)
        if self.user and not getattr(self.user, "is_superuser", False):
            if not self.user.groups.filter(name="platform_admin").exists():
                qs = qs.filter(created_by=self.user)
        self.fields["aparell"].queryset = qs.order_by("nom", "id")

    def clean_aparell(self):
        aparell = self.cleaned_data.get("aparell")
        if not aparell or not self.competicio:
            return aparell

        is_platform_admin = bool(
            self.user
            and (
                getattr(self.user, "is_superuser", False)
                or self.user.groups.filter(name="platform_admin").exists()
            )
        )
        if self.user and not is_platform_admin and aparell.created_by_id != self.user.id:
            raise ValidationError(
                _("No pots utilitzar aparells creats per un altre usuari."),
                code="forbidden_aparell_owner",
            )

        qs = CompeticioAparell.objects.filter(
            competicio=self.competicio,
            aparell=aparell,
        )

        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise ValidationError(
                _("Aquest aparell ja esta afegit a la competicio."),
                code="duplicate_aparell",
            )
        return aparell

    def clean_nombre_exercicis(self):
        n = int(self.cleaned_data.get("nombre_exercicis") or 1)
        if n < 1 or n > 5:
            raise ValidationError(
                _("El nombre d'exercicis ha de ser entre 1 i 5."),
                code="invalid_nombre_exercicis",
            )
        return max(1, min(5, n))

    def clean(self):
        cleaned_data = super().clean()
        aparell = cleaned_data.get("aparell")
        if aparell and not getattr(aparell, "actiu", True):
            self.add_error("aparell", "Cal seleccionar un aparell actiu.")
        return cleaned_data

    class Meta:
        model = CompeticioAparell
        fields = [
            "aparell",
            "nombre_exercicis",
        ]
        widgets = {
            "aparell": forms.Select(attrs={"class": "form-select"}),
            "nombre_exercicis": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 10, "value": 1}),
        }


class AparellForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

    def clean_codi(self):
        codi = str(self.cleaned_data.get("codi") or "").strip().upper()
        if not codi:
            raise ValidationError(
                _("Cal indicar un codi d'aparell."),
                code="missing_codi",
            )
        return codi

    def clean(self):
        cleaned_data = super().clean()
        codi = cleaned_data.get("codi")
        if not codi or not self.user:
            return cleaned_data
        qs = Aparell.objects.filter(created_by=self.user, codi=codi)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            self.add_error(
                "codi",
                ValidationError(
                    _("Ja tens un aparell amb aquest codi."),
                    code="duplicate_owner_codi",
                ),
            )
        return cleaned_data

    class Meta:
        model = Aparell
        fields = ["codi", "nom", "competition_unit", "actiu"]
        widgets = {
            "codi": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: TRAMP, DMT..."}),
            "nom": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nom de l'aparell"}),
            "competition_unit": forms.Select(attrs={"class": "form-select"}),
            "actiu": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {"codi": "Codi", "nom": "Nom", "competition_unit": "Unitat competitiva", "actiu": "Actiu"}
        help_texts = {"codi": "Ha de ser unic per usuari. Recomanat en majuscules (ex: TRAMP)."}


class ScoringSchemaForm(forms.ModelForm):
    schema_json = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = ScoringSchema
        fields = ["schema_json"]

    def __init__(self, *args, **kwargs):
        self.comp_aparell = kwargs.pop("comp_aparell", None)
        self.raw_schema_json = ""
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["schema_json"].initial = json.dumps(self.instance.schema or {}, ensure_ascii=False)

    def get_raw_schema_json(self) -> str:
        return str(self.raw_schema_json or "")

    def _update_errors(self, errors):
        if hasattr(errors, "error_dict") and isinstance(errors.error_dict, dict):
            schema_errors = list(errors.error_dict.pop("schema", []) or [])
            if schema_errors:
                errors.error_dict.setdefault("schema_json", []).extend(schema_errors)
        return super()._update_errors(errors)

    def clean_schema_json(self):
        txt = (self.cleaned_data.get("schema_json") or "").strip()
        self.raw_schema_json = txt
        if not txt:
            return None

        try:
            data = json.loads(txt)
        except Exception as exc:
            raise ValidationError(f"JSON invalid: {exc}")

        if not isinstance(data, dict):
            raise ValidationError("El JSON ha de ser un objecte (dict).")

        validate_schema(
            data,
            aparell=(self.comp_aparell.aparell if self.comp_aparell else getattr(self.instance, "aparell", None)),
        )
        return data
