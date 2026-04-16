"""Base classes for browser-driven inscripcions tests."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.middleware.csrf import _get_new_csrf_string
from django.urls import reverse

from ...models import CompeticioMembership
from ..base import _BaseTrampoliDataMixin
from .helpers import INSCRIPCIONS_PAGE_SHELL_ID, panel_related_selectors

try:
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover - import error is environment specific
    raise ImportError(
        "Playwright is required for browser tests. Install it and run "
        "`playwright install chromium`."
    ) from exc

# Playwright's sync API uses an event loop under the hood. Django's async
# safety guard would otherwise block ordinary ORM access inside these browser
# test cases.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


class BrowserInscripcionsBase(_BaseTrampoliDataMixin, StaticLiveServerTestCase):
    """Reusable Django + Playwright base for inscripcions browser tests."""

    browser_name = os.getenv("PLAYWRIGHT_BROWSER", "chromium")
    headless = os.getenv("PLAYWRIGHT_HEADLESS", "1").strip().lower() not in {"0", "false", "no"}
    default_timeout_ms = int(os.getenv("PLAYWRIGHT_DEFAULT_TIMEOUT_MS", "10000"))
    default_navigation_timeout_ms = int(os.getenv("PLAYWRIGHT_NAVIGATION_TIMEOUT_MS", "15000"))
    viewport_size = {"width": 1440, "height": 1200}

    _playwright = None
    browser = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._playwright = sync_playwright().start()
        browser_type = getattr(cls._playwright, cls.browser_name)
        cls.browser = browser_type.launch(headless=cls.headless)

    @classmethod
    def tearDownClass(cls):
        browser = getattr(cls, "browser", None)
        playwright = getattr(cls, "_playwright", None)
        try:
            if browser is not None:
                browser.close()
        finally:
            cls.browser = None
            if playwright is not None:
                playwright.stop()
            cls._playwright = None
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.context = self.browser.new_context(viewport=self.viewport_size)
        self.context.set_default_timeout(self.default_timeout_ms)
        self.context.set_default_navigation_timeout(self.default_navigation_timeout_ms)
        self.page = self.context.new_page()

        self._browser_console_errors: list[str] = []
        self._browser_page_errors: list[str] = []
        self._browser_request_failures: list[str] = []
        self._wire_browser_error_capture()

        self.addCleanup(self.assert_no_browser_errors)
        self.addCleanup(self._close_browser_context)

    def _close_browser_context(self):
        page = getattr(self, "page", None)
        context = getattr(self, "context", None)
        try:
            if page is not None:
                page.close()
        finally:
            if context is not None:
                context.close()
            self.page = None
            self.context = None

    def _wire_browser_error_capture(self):
        def on_console(message):
            if message.type != "error":
                return
            location = getattr(message, "location", None) or {}
            url = str(location.get("url") or "").strip()
            line = location.get("lineNumber")
            column = location.get("columnNumber")
            suffix = ""
            if url:
                suffix = f" ({url}"
                if line is not None:
                    suffix += f":{line}"
                    if column is not None:
                        suffix += f":{column}"
                suffix += ")"
            self._browser_console_errors.append(f"{message.text}{suffix}")

        def on_page_error(error):
            self._browser_page_errors.append(str(error))

        def on_request_failed(request):
            failure = request.failure() if callable(getattr(request, "failure", None)) else request.failure
            if isinstance(failure, str):
                failure_text = failure
            else:
                failure_text = getattr(failure, "error_text", None) if failure is not None else None
            reason = str(failure_text or "request failed").strip()
            self._browser_request_failures.append(f"{request.method} {request.url} - {reason}")

        self.page.on("console", on_console)
        self.page.on("pageerror", on_page_error)
        self.page.on("requestfailed", on_request_failed)

    def _build_url(self, path: str, query: dict[str, Any] | None = None) -> str:
        url = f"{self.live_server_url.rstrip('/')}/{str(path).lstrip('/')}"
        if query:
            query_string = urlencode([(key, value) for key, value in query.items() if value is not None], doseq=True)
            if query_string:
                url = f"{url}?{query_string}"
        return url

    def _sync_client_cookies_to_browser(self):
        cookies = []
        for name, morsel in self.client.cookies.items():
            cookies.append(
                {
                    "name": name,
                    "value": morsel.value,
                    "url": self.live_server_url,
                }
            )

        if settings.CSRF_COOKIE_NAME not in self.client.cookies:
            csrf_secret = _get_new_csrf_string()
            self.client.cookies[settings.CSRF_COOKIE_NAME] = csrf_secret
            cookies.append(
                {
                    "name": settings.CSRF_COOKIE_NAME,
                    "value": csrf_secret,
                    "url": self.live_server_url,
                }
            )

        if cookies:
            self.context.add_cookies(cookies)

    def login_user(self, user, *, reload_page: bool = False):
        """Log a user through the Django client and mirror the session in Playwright."""
        self.client.force_login(user)
        self._sync_client_cookies_to_browser()
        if reload_page and getattr(self, "page", None) is not None and self.page.url:
            self.page.reload(wait_until="domcontentloaded")
        return user

    def login_competicio_user(
        self,
        competicio,
        *,
        role=CompeticioMembership.Role.EDITOR,
        username_prefix="comp_user",
        reload_page: bool = False,
    ):
        """Create and log in a competition-scoped user, then sync browser cookies."""
        login_kwargs = {"username_prefix": username_prefix}
        if role is not None:
            login_kwargs["role"] = role
        user = self._login_competicio_user(competicio, **login_kwargs)
        self._sync_client_cookies_to_browser()
        if reload_page and getattr(self, "page", None) is not None and self.page.url:
            self.page.reload(wait_until="domcontentloaded")
        return user

    def open_inscripcions_page(self, competicio, *, query: dict[str, Any] | None = None, wait_for_ready: bool = True):
        """Open the main inscripcions page for a competition."""
        competicio_id = getattr(competicio, "pk", competicio)
        url = reverse("inscripcions_list", args=[competicio_id])
        if query:
            url = self._build_url(url, query)
        else:
            url = self._build_url(url)

        self.page.goto(url, wait_until="domcontentloaded")
        self.page.locator(f"#{INSCRIPCIONS_PAGE_SHELL_ID}").wait_for(state="visible")
        if wait_for_ready:
            self.wait_for_inscripcions_app()
        return self.page

    def wait_for_inscripcions_app(self):
        """Wait until the inscripcions JS boot object is available."""
        self.page.wait_for_function(
            """() => !!window.InscripcionsApp
            && typeof window.InscripcionsApp.refreshHtmlFragments === 'function'
            && typeof window.InscripcionsApp.openPanel === 'function'"""
        )
        return self.page

    def open_lazy_panel(self, panel_key: str, *, wait_for_loaded: bool = True):
        """Open a lazy panel and wait for the server-rendered content to replace the placeholder."""
        key = str(panel_key or "").strip()
        if not key:
            raise ValueError("panel_key is required")
        button_selector, panel_selector = panel_related_selectors(key)

        self.page.locator(button_selector).first.click()

        panel = self.page.locator(panel_selector)
        panel.wait_for(state="visible")

        if wait_for_loaded:
            self.page.wait_for_function(
                """panelKey => {
                    const panel = document.querySelector(`[data-panel-key="${panelKey}"]`);
                    return !!panel && panel.getAttribute('data-panel-lazy') !== '1';
                }""",
                arg=key,
            )

        return panel

    def get_browser_errors(self) -> dict[str, list[str]]:
        return {
            "console": list(self._browser_console_errors),
            "page": list(self._browser_page_errors),
            "requests": list(self._browser_request_failures),
        }

    def clear_browser_errors(self):
        self._browser_console_errors.clear()
        self._browser_page_errors.clear()
        self._browser_request_failures.clear()

    def assert_no_browser_errors(self):
        """Fail if the browser logged console errors, page errors or failed requests."""
        errors = self.get_browser_errors()
        lines = []

        if errors["console"]:
            lines.append("Console errors:")
            lines.extend(f"  - {item}" for item in errors["console"])
        if errors["page"]:
            lines.append("Page errors:")
            lines.extend(f"  - {item}" for item in errors["page"])
        if errors["requests"]:
            lines.append("Failed requests:")
            lines.extend(f"  - {item}" for item in errors["requests"])

        if lines:
            raise AssertionError("Browser errors detected:\n" + "\n".join(lines))
