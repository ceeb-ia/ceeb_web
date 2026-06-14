from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse


class BaseTemplateChatbotEnvTests(TestCase):
    def _render_base(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        return render_to_string("base.html", {}, request=request)

    @override_settings(APP_ENV="dev")
    def test_base_renders_chatbot_widget_and_script_in_dev(self):
        html = self._render_base()

        self.assertIn('id="chatbot-open"', html)
        self.assertIn("js/chatbot.js", html)

    @override_settings(APP_ENV="prod")
    def test_base_hides_chatbot_widget_and_script_outside_dev(self):
        html = self._render_base()

        self.assertNotIn('id="chatbot-open"', html)
        self.assertNotIn('id="chatbot"', html)
        self.assertNotIn("js/chatbot.js", html)
        self.assertNotIn('class="navbar-brand"', html)
        self.assertNotIn('class="footer_section"', html)

    @override_settings(APP_ENV="prod")
    def test_login_uses_competition_wallpaper_in_prod(self):
        request = RequestFactory().get("/accounts/login/")
        request.user = AnonymousUser()

        html = render_to_string("registration/login.html", {}, request=request)

        self.assertIn("--ceeb-page-background-image: url('/static/general/wallpapers/general.png');", html)
        self.assertIn("competicions-app", html)

    def test_competition_dock_renders_outside_main(self):
        request = RequestFactory().get("/competicions/1/")
        request.user = AnonymousUser()
        html = render_to_string(
            "base.html",
            {
                "is_competicions_app": True,
                "has_competition_dock": True,
                "hide_base_chrome": False,
                "competition_dock_items": [
                    {
                        "section": "home",
                        "active": True,
                        "url": "#",
                        "label": "Competicions",
                        "icon_path": "dock/competicions.png",
                    }
                ],
            },
            request=request,
        )

        main_close = html.index("</main>")
        dock = html.index('class="competition-dock"')
        footer = html.index('class="footer_section"')

        self.assertGreater(dock, main_close)
        self.assertGreater(dock, footer)


@override_settings(APP_ENV="prod", ROOT_URLCONF="ceeb_web.urls_prod")
class ProdCompetitionShellTests(TestCase):
    def setUp(self):
        group, _ = Group.objects.get_or_create(name="competicions_manager")
        self.user = get_user_model().objects.create_user(
            username="prod_competicions_manager",
            password="testpass123",
        )
        self.user.groups.add(group)

    def test_prod_root_redirects_to_competitions_home(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("home"))

        self.assertRedirects(response, reverse("competicions_home"))

    def test_prod_competitions_home_renders_with_logout_only(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("competicions_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Competicions")
        self.assertContains(response, "Sortir")
        self.assertContains(response, "competicions-app")
        self.assertNotContains(response, 'class="navbar-brand"')
        self.assertNotContains(response, 'class="footer_section"')
        self.assertContains(response, "<strong>Nova competició</strong>", html=True)
