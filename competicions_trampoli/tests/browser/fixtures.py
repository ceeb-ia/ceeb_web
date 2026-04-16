"""Shared browser fixtures for inscripcions browser tests."""

from datetime import date
from types import SimpleNamespace

from django.core.files.uploadedfile import SimpleUploadedFile

from ...models import Competicio, CompeticioMembership, EquipContext, Inscripcio, InscripcioMedia
from ...models.competicio import Aparell, CompeticioAparellEquipContextSource
from ...services.shared.competition_groups import ensure_group_for_display_num
from ..base import _BaseTrampoliDataMixin


class BrowserInscripcionsFixturesMixin(_BaseTrampoliDataMixin):
    """Small deterministic data builders for browser-level inscripcions tests."""

    browser_user_password = "testpass123"

    def _browser_competicio_defaults(self, *, group_by_default=None, inscripcions_schema=None, inscripcions_view=None):
        return {
            "tipus": Competicio.Tipus.TRAMPOLI,
            "group_by_default": list(group_by_default or ["categoria", "subcategoria"]),
            "tab_merges": {},
            "inscripcions_schema": inscripcions_schema or {
                "columns": [
                    {"code": "nivell", "label": "Nivell", "kind": "extra"},
                    {"code": "delegacio", "label": "Delegacio", "kind": "extra"},
                ]
            },
            "inscripcions_view": inscripcions_view or {
                "table_columns": [
                    "nom_i_cognoms",
                    "document",
                    "categoria",
                    "subcategoria",
                    "entitat",
                    "grup",
                    "equip",
                    "__aparells__",
                    "__media__",
                    "ordre_sortida",
                    "__actions__",
                ]
            },
        }

    def _create_browser_competicio(
        self,
        nom="Browser Comp",
        *,
        data=None,
        group_by_default=None,
        inscripcions_schema=None,
        inscripcions_view=None,
    ):
        defaults = self._browser_competicio_defaults(
            group_by_default=group_by_default,
            inscripcions_schema=inscripcions_schema,
            inscripcions_view=inscripcions_view,
        )
        return Competicio.objects.create(
            nom=nom,
            data=data,
            **defaults,
        )

    def _create_browser_user(
        self,
        competicio,
        *,
        username_prefix="browser_user",
        role=CompeticioMembership.Role.EDITOR,
        email=None,
        is_active=True,
        login=False,
    ):
        user = self._create_competicio_user(
            competicio,
            role=role,
            username_prefix=username_prefix,
        )
        if email is not None and str(user.email or "") != str(email):
            user.email = email
            user.save(update_fields=["email"])
        membership = CompeticioMembership.objects.get(user=user, competicio=competicio)
        dirty_fields = []
        if membership.role != role:
            membership.role = role
            dirty_fields.append("role")
        if membership.is_active != bool(is_active):
            membership.is_active = bool(is_active)
            dirty_fields.append("is_active")
        if dirty_fields:
            membership.save(update_fields=dirty_fields)
        if login:
            self.client.force_login(user)
        return user

    def _login_browser_user(
        self,
        competicio,
        *,
        username_prefix="browser_user",
        role=CompeticioMembership.Role.EDITOR,
        email=None,
        is_active=True,
    ):
        return self._create_browser_user(
            competicio,
            username_prefix=username_prefix,
            role=role,
            email=email,
            is_active=is_active,
            login=True,
        )

    def _create_compact_inscripcions(
        self,
        competicio,
        *,
        total=4,
        with_groups=True,
        start_order=1,
        base_name="Inscripcio",
        entitats=None,
        categories=None,
        subcategories=None,
        sexes=None,
        start_birth_year=2010,
    ):
        entitats = list(entitats or ["Club A", "Club B"])
        categories = list(categories or ["Base", "Promocio"])
        subcategories = list(subcategories or ["A", "B"])
        sexes = list(sexes or ["F", "M"])

        rows = []
        for index in range(int(total)):
            group_num = 1 + (index // 2)
            group = None
            if with_groups and index < max(1, int(total) - 1):
                group = ensure_group_for_display_num(
                    competicio,
                    group_num,
                    name=f"Group {group_num}",
                )
            row = self._create_inscripcio(
                competicio,
                f"{base_name} {index + 1}",
                ordre=start_order + index,
                grup=group.display_num if group is not None else None,
            )
            row.categoria = categories[index % len(categories)]
            row.subcategoria = subcategories[index % len(subcategories)]
            row.entitat = entitats[index % len(entitats)]
            row.sexe = sexes[index % len(sexes)]
            row.data_naixement = date(start_birth_year + (index % 4), (index % 12) + 1, (index % 28) + 1)
            row.document = f"ID{index + 1:04d}"
            row.extra = {
                "delegacio": f"Zone {index + 1}",
                "nivell": f"Level {index + 1}",
            }
            row.group_by_default = list(competicio.group_by_default or [])
            row.save()
            rows.append(row)
        return rows

    def _create_optional_team_context(
        self,
        competicio,
        *,
        code="pairs",
        nom="Pairs",
        description="",
        team_names=None,
        member_names_by_team=None,
        inscripcions=None,
        attach_memberships=True,
    ):
        context = EquipContext.objects.create(
            competicio=competicio,
            code=code,
            nom=nom,
            description=description,
        )
        teams = []
        members = list(inscripcions or [])
        assignments = []

        team_names = list(team_names or ["Team A", "Team B"])
        member_names_by_team = list(
            member_names_by_team
            or [
                ["Alice One", "Bob One"],
                ["Cara Two", "Dan Two"],
            ]
        )

        for index, team_name in enumerate(team_names):
            team = self._create_equip(competicio, team_name, context=context)
            teams.append(team)
            member_names = member_names_by_team[index] if index < len(member_names_by_team) else []
            for member_index, member_name in enumerate(member_names):
                if members and len(members) > (index * 2 + member_index):
                    inscripcio = members[index * 2 + member_index]
                else:
                    inscripcio = self._create_inscripcio(
                        competicio,
                        member_name,
                        ordre=100 + (index * 10) + member_index,
                        grup=1 + index,
                    )
                    members.append(inscripcio)
                if attach_memberships:
                    assignments.append(self._assign_equip(competicio, inscripcio, team, context=context))

        return SimpleNamespace(
            context=context,
            teams=teams,
            inscripcions=members,
            assignments=assignments,
        )

    def _create_optional_series_app(
        self,
        competicio,
        *,
        codi="SERIES",
        nom="Series App",
        ordre=1,
        context=None,
        context_code="pairs",
        context_name="Pairs",
        attach_context_source=True,
    ):
        context_bundle = None
        if context is None:
            context_bundle = self._create_optional_team_context(
                competicio,
                code=context_code,
                nom=context_name,
            )
            context = context_bundle.context

        aparell = self._create_aparell(codi, nom)
        aparell.competition_unit = Aparell.CompetitionUnit.TEAM
        aparell.save(update_fields=["competition_unit"])

        comp_aparell = self._create_comp_aparell(
            competicio,
            aparell,
            ordre=ordre,
        )

        context_source = None
        if attach_context_source:
            context_source = CompeticioAparellEquipContextSource.objects.create(
                competicio=competicio,
                comp_aparell=comp_aparell,
                context=context,
            )

        return SimpleNamespace(
            aparell=aparell,
            comp_aparell=comp_aparell,
            context=context,
            context_source=context_source,
            context_bundle=context_bundle,
        )

    def _create_optional_media(
        self,
        competicio,
        *,
        inscripcions=None,
        count=2,
        tipologies=None,
        primary_index=0,
    ):
        rows = list(inscripcions or self._create_compact_inscripcions(competicio, total=max(2, int(count))))
        tipologies = list(tipologies or [InscripcioMedia.Tipus.AUDIO, InscripcioMedia.Tipus.VIDEO])

        media_items = []
        for index in range(min(int(count), len(rows))):
            inscripcio = rows[index]
            tipus = tipologies[index % len(tipologies)]
            extension = "mp3" if tipus == InscripcioMedia.Tipus.AUDIO else "mp4"
            content_type = "audio/mpeg" if tipus == InscripcioMedia.Tipus.AUDIO else "video/mp4"
            upload = SimpleUploadedFile(
                f"media_{inscripcio.id}_{index + 1}.{extension}",
                b"browser-fixture",
                content_type=content_type,
            )
            media_items.append(
                InscripcioMedia.objects.create(
                    competicio=competicio,
                    inscripcio=inscripcio,
                    fitxer=upload,
                    tipus=tipus,
                    mime_type=content_type,
                    original_filename=f"{inscripcio.nom_i_cognoms}_{tipus}.{extension}",
                    file_size_bytes=len(b"browser-fixture"),
                    is_primary=index == int(primary_index),
                    source=InscripcioMedia.Source.MANUAL,
                )
            )
        return SimpleNamespace(inscripcions=rows, media_items=media_items)


__all__ = ["BrowserInscripcionsFixturesMixin"]
