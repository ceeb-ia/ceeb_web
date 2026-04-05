from django.contrib.auth import get_user_model

from ..models import Competicio, CompeticioMembership, Equip, Inscripcio, InscripcioEquipAssignacio
from ..models.competicio import Aparell, CompeticioAparell
from ..services.equip_contexts import ensure_base_equip_context


class _BaseTrampoliDataMixin:
    def _create_competicio(self, nom="Comp"):
        return Competicio.objects.create(
            nom=nom,
            tipus=Competicio.Tipus.TRAMPOLI,
        )

    def _ensure_default_aparell_owner(self):
        owner = getattr(self, "_default_aparell_owner", None)
        if owner is not None:
            return owner
        User = get_user_model()
        owner = User.objects.create_user(
            username=f"ap_owner_{self.__class__.__name__.lower()}",
            password="testpass123",
            email=f"ap-owner-{self.__class__.__name__.lower()}@example.com",
        )
        self._default_aparell_owner = owner
        return owner

    def _create_aparell(self, codi, nom, owner=None):
        owner = owner or getattr(self, "user", None) or self._ensure_default_aparell_owner()
        return Aparell.objects.create(codi=codi, nom=nom, actiu=True, created_by=owner)

    def _create_comp_aparell(self, competicio, aparell, ordre=1, actiu=True):
        return CompeticioAparell.objects.create(
            competicio=competicio,
            aparell=aparell,
            ordre=ordre,
            actiu=actiu,
        )

    def _create_inscripcio(self, competicio, nom, ordre=1, grup=1):
        return Inscripcio.objects.create(
            competicio=competicio,
            nom_i_cognoms=nom,
            ordre_sortida=ordre,
            grup=grup,
        )

    def _create_competicio_user(
        self,
        competicio,
        *,
        role=CompeticioMembership.Role.EDITOR,
        username_prefix="comp_user",
    ):
        User = get_user_model()
        username = f"{username_prefix}_{self.__class__.__name__.lower()}_{competicio.id}_{CompeticioMembership.objects.count()}"
        user = User.objects.create_user(
            username=username,
            password="testpass123",
            email=f"{username}@example.com",
        )
        CompeticioMembership.objects.create(
            user=user,
            competicio=competicio,
            role=role,
            is_active=True,
        )
        return user

    def _login_competicio_user(
        self,
        competicio,
        *,
        role=CompeticioMembership.Role.EDITOR,
        username_prefix="comp_user",
    ):
        user = self._create_competicio_user(
            competicio,
            role=role,
            username_prefix=username_prefix,
        )
        self.client.force_login(user)
        return user

    def _ensure_native_equip_context(self, competicio):
        return ensure_base_equip_context(competicio)

    def _create_equip(self, competicio, nom, *, context=None, origen=Equip.Origen.MANUAL, criteri=None):
        context = context or self._ensure_native_equip_context(competicio)
        max_nom_length = getattr(Equip._meta.get_field("nom"), "max_length", None)
        if isinstance(max_nom_length, int) and max_nom_length > 0:
            nom = str(nom or "")[:max_nom_length]
        return Equip.objects.create(
            competicio=competicio,
            context=context,
            nom=nom,
            origen=origen,
            criteri=criteri or {},
        )

    def _assign_equip(
        self,
        competicio,
        inscripcio,
        equip,
        *,
        context=None,
        origen=InscripcioEquipAssignacio.Origen.MANUAL,
        criteri=None,
    ):
        context = context or self._ensure_native_equip_context(competicio)
        return InscripcioEquipAssignacio.objects.create(
            competicio=competicio,
            context=context,
            inscripcio=inscripcio,
            equip=equip,
            origen=origen,
            criteri=criteri or {},
        )
