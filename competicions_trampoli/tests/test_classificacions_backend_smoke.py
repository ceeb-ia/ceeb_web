import ast
import importlib
from pathlib import Path

from django.test import TestCase
from django.urls import resolve, reverse

from ..models import CompeticioMembership
from ..models_judging import PublicLiveToken
from ..models_trampoli import CompeticioAparell
from .base import _BaseTrampoliDataMixin


class ClassificacionsBackendSmokeTests(_BaseTrampoliDataMixin, TestCase):
    def setUp(self):
        self.comp = self._create_competicio("Comp Classificacions Smoke")
        self.user = self._create_competicio_user(
            self.comp,
            role=CompeticioMembership.Role.OWNER,
            username_prefix="class_smoke",
        )
        self.client.force_login(self.user)
        aparell = self._create_aparell("TRA", "Trampoli")
        self.comp_app = self._create_comp_aparell(self.comp, aparell, ordre=1)
        self.token = PublicLiveToken.objects.create(
            competicio=self.comp,
            label="Smoke Live",
            can_view_media=True,
        )

    def test_entrypoint_modules_import_and_do_not_depend_on_legacy_monolith(self):
        modules = [
            "competicions_trampoli.views_classificacions_builder",
            "competicions_trampoli.views_classificacions_live",
            "competicions_trampoli.views_classificacions_templates",
            "competicions_trampoli.views_classificacions_export",
        ]
        for module_name in modules:
            importlib.import_module(module_name)

        package_root = Path(__file__).resolve().parents[1]
        for rel_path in [
            "views_classificacions_builder.py",
            "views_classificacions_live.py",
            "views_classificacions_templates.py",
            "views_classificacions_export.py",
        ]:
            source = (package_root / rel_path).read_text(encoding="utf-8")
            self.assertNotIn("from .views_classificacions import", source)

    def test_legacy_file_reexports_split_entrypoints(self):
        package_root = Path(__file__).resolve().parents[1]
        source = (package_root / "views_classificacions.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        func_defs = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
        class_defs = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
        self.assertIn("Compatibility facade for split classificacions entrypoints", source)
        self.assertIn("from .views_classificacions_builder import", source)
        self.assertIn("from .views_classificacions_live import", source)
        self.assertIn("from .views_classificacions_templates import", source)
        self.assertIn("from .views_classificacions_export import", source)
        self.assertEqual(class_defs, [])
        self.assertEqual(func_defs, ["_template_schema_to_competicio_schema"])
        wrapper = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
        return_nodes = [node for node in wrapper.body if isinstance(node, ast.Return)]
        self.assertEqual(len(return_nodes), 1)

    def test_reverse_and_resolve_classificacions_routes(self):
        route_kwargs = {
            "classificacio_delete": {"pk": 1, "cid": 1},
            "classificacio_preview": {"pk": 1, "cid": 1},
            "public_live_portal": {"token": self.token.id},
            "public_live_loop": {"token": self.token.id},
            "public_live_classificacions_data": {"token": self.token.id},
        }
        route_names = [
            "classificacions_home",
            "classificacio_save",
            "classificacio_delete",
            "classificacio_reorder",
            "classificacio_preview",
            "classificacio_template_list",
            "classificacio_template_save",
            "classificacio_template_validate",
            "classificacio_template_apply",
            "classificacions_live",
            "classificacions_loop_live",
            "classificacions_live_data",
            "classificacions_live_export_excel",
            "public_live_portal",
            "public_live_loop",
            "public_live_classificacions_data",
        ]
        for route_name in route_names:
            kwargs = route_kwargs.get(route_name, {"pk": self.comp.id})
            url = reverse(route_name, kwargs=kwargs)
            match = resolve(url)
            self.assertEqual(match.view_name, route_name)

    def test_render_smoke_for_builder_internal_live_and_public_live(self):
        builder_response = self.client.get(reverse("classificacions_home", kwargs={"pk": self.comp.id}))
        self.assertEqual(builder_response.status_code, 200)
        self.assertTemplateUsed(builder_response, "competicio/classificacions_builder_v2.html")
        self.assertIn("cfg_status", builder_response.context)
        self.assertIn("aparell_field_options", builder_response.context)

        live_response = self.client.get(reverse("classificacions_live", kwargs={"pk": self.comp.id}))
        self.assertEqual(live_response.status_code, 200)
        self.assertTemplateUsed(live_response, "competicio/classificacions_live.html")
        self.assertIn("cfgs", live_response.context)
        self.assertIn("poll_ms", live_response.context)

        public_response = self.client.get(reverse("public_live_portal", kwargs={"token": self.token.id}))
        self.assertEqual(public_response.status_code, 200)
        self.assertTemplateUsed(public_response, "competicio/classificacions_live.html")
        self.assertTrue(public_response.context["is_public"])
        self.assertTrue(public_response.context["public_token_can_view_media"])

    def test_live_payload_contract_smoke(self):
        response = self.client.get(reverse("classificacions_live_data", kwargs={"pk": self.comp.id}))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertIn("changed", payload)
        self.assertIn("stamp", payload)
        self.assertIn("cfgs", payload)

        public_response = self.client.get(reverse("public_live_classificacions_data", kwargs={"token": self.token.id}))
        self.assertEqual(public_response.status_code, 200)
        public_payload = public_response.json()
        self.assertTrue(public_payload.get("ok"))
        self.assertIn("permissions", public_payload)
        self.assertIn("cfgs", public_payload)
