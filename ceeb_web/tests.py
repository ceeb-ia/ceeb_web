from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings


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
