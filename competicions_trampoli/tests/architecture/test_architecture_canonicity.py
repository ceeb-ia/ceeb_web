import ast
import importlib
from importlib.util import resolve_name
from pathlib import Path

from django.test import SimpleTestCase


class CanonicalArchitectureTests(SimpleTestCase):
    def setUp(self):
        self.package_root = Path(__file__).resolve().parents[2]
        self.repo_python_root = self.package_root.parent

    def _iter_python_files(self):
        for path in self.package_root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path

    def _module_name_for_path(self, path: Path) -> str:
        rel_parts = path.relative_to(self.repo_python_root).with_suffix("").parts
        return ".".join(rel_parts)

    def _resolved_imports_for_path(self, path: Path):
        module_name = self._module_name_for_path(path)
        package_name = module_name.rsplit(".", 1)[0] if "." in module_name else module_name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                target = "." * node.level + (node.module or "")
                if node.level:
                    imports.append(resolve_name(target, package_name))
                elif node.module:
                    imports.append(node.module)
        return imports

    def test_urls_entrypoint_is_package(self):
        module = importlib.import_module("competicions_trampoli.urls")
        self.assertTrue(module.__file__.replace("\\", "/").endswith("/competicions_trampoli/urls/__init__.py"))

    def test_models_entrypoint_is_package(self):
        module = importlib.import_module("competicions_trampoli.models")
        self.assertTrue(module.__file__.replace("\\", "/").endswith("/competicions_trampoli/models/__init__.py"))

    def test_removed_legacy_shims_and_shadow_files_are_absent(self):
        removed_paths = [
            "models_trampoli.py",
            "models_scoring.py",
            "models_judging.py",
            "models_rotacions.py",
            "models_classificacions.py",
            "views_competitions.py",
            "views_judge_admin.py",
            "views_judge_messages.py",
            "views_judge.py",
            "views_scoring.py",
            "views_trampoli.py",
            "views_rotacions.py",
            "models.py",
            "urls.py",
        ]
        for rel_path in removed_paths:
            self.assertFalse((self.package_root / rel_path).exists(), rel_path)

    def test_no_python_source_imports_removed_legacy_modules(self):
        forbidden_modules = {
            "competicions_trampoli.models_trampoli",
            "competicions_trampoli.models_scoring",
            "competicions_trampoli.models_judging",
            "competicions_trampoli.models_rotacions",
            "competicions_trampoli.models_classificacions",
            "competicions_trampoli.views_competitions",
            "competicions_trampoli.views_judge_admin",
            "competicions_trampoli.views_judge_messages",
            "competicions_trampoli.views_judge",
            "competicions_trampoli.views_scoring",
            "competicions_trampoli.views_trampoli",
            "competicions_trampoli.views_rotacions",
        }

        offenders = []
        for path in self._iter_python_files():
            for imported_module in self._resolved_imports_for_path(path):
                if imported_module in forbidden_modules:
                    offenders.append(f"{path.relative_to(self.package_root)} -> {imported_module}")

        self.assertEqual(offenders, [])
