from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse

from ceeb_web.auth_groups import GLOBAL_AUTH_GROUPS
from ceeb_web.app_registry import is_internal_app_installed as real_is_internal_app_installed

from competicions_trampoli.models import Competicio, CompeticioMembership


@override_settings(APP_ENV="intern", ROOT_URLCONF="ceeb_web.urls_intern")
class InternalAppAccessTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        for group_name in GLOBAL_AUTH_GROUPS:
            Group.objects.get_or_create(name=group_name)

        self.comp = Competicio.objects.create(nom="Comp Interna")
        self.other_comp = Competicio.objects.create(nom="Comp Aliena")

    def _user(self, username):
        return self.User.objects.create_user(username=username, password="testpass123")

    def _add_group(self, user, group_name):
        user.groups.add(Group.objects.get(name=group_name))

    def _add_membership(self, user, competicio, role=CompeticioMembership.Role.READONLY):
        return CompeticioMembership.objects.create(
            user=user,
            competicio=competicio,
            role=role,
            is_active=True,
        )

    def test_anonymous_user_is_redirected_to_login_for_internal_apps(self):
        urls = (
            reverse("calendar_home"),
            reverse("designacions_runs_list"),
            reverse("annual_report_list"),
            reverse("competicions_home"),
        )

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response["Location"])

    def test_authenticated_user_without_roles_gets_403_on_app_routes(self):
        user = self._user("sense_roles")
        self.client.force_login(user)

        urls = (
            reverse("calendar_home"),
            reverse("designacions_runs_list"),
            reverse("annual_report_list"),
            reverse("competicions_home"),
        )

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 403)

    def test_internal_landing_without_access_returns_200_and_informative_message(self):
        user = self._user("sense_accessos")
        self.client.force_login(user)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aquest usuari no te cap acces intern assignat.")

    def test_calendar_manager_sees_only_calendar_and_can_access_it(self):
        user = self._user("calendar_manager_user")
        self._add_group(user, "calendar_manager")
        self.client.force_login(user)

        home_response = self.client.get(reverse("home"))
        self.assertEqual(home_response.status_code, 200)
        self.assertContains(home_response, "Calendari")
        self.assertNotContains(home_response, "Designacions")
        self.assertNotContains(home_response, "Informes")
        self.assertNotContains(home_response, "Competicions")

        self.assertEqual(self.client.get(reverse("calendar_home")).status_code, 200)
        self.assertEqual(self.client.get(reverse("calendar_events_json")).status_code, 200)
        self.assertEqual(self.client.get(reverse("designacions_runs_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("annual_report_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("competicions_home")).status_code, 403)

    def test_designacions_manager_sees_only_designacions_and_secondary_endpoint(self):
        user = self._user("designacions_manager_user")
        self._add_group(user, "designacions_manager")
        self.client.force_login(user)

        home_response = self.client.get(reverse("home"))
        self.assertEqual(home_response.status_code, 200)
        self.assertContains(home_response, "Designacions")
        self.assertNotContains(home_response, "Calendari")
        self.assertNotContains(home_response, "Informes")
        self.assertNotContains(home_response, "Competicions")

        self.assertEqual(self.client.get(reverse("designacions_runs_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("designacions_task_status", kwargs={"task_id": "missing-task"})).status_code, 200)
        self.assertEqual(self.client.get(reverse("annual_report_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("competicions_home")).status_code, 403)

    def test_informes_manager_sees_only_informes(self):
        user = self._user("informes_manager_user")
        self._add_group(user, "informes_manager")
        self.client.force_login(user)

        home_response = self.client.get(reverse("home"))
        self.assertEqual(home_response.status_code, 200)
        self.assertContains(home_response, "Informes")
        self.assertNotContains(home_response, "Calendari")
        self.assertNotContains(home_response, "Designacions")
        self.assertNotContains(home_response, "Competicions")

        self.assertEqual(self.client.get(reverse("annual_report_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("designacions_runs_list")).status_code, 403)

    def test_competicions_manager_can_access_global_competicions_pages(self):
        user = self._user("competicions_manager_user")
        self._add_group(user, "competicions_manager")
        self.client.force_login(user)

        home_response = self.client.get(reverse("home"))
        self.assertEqual(home_response.status_code, 200)
        self.assertContains(home_response, "Competicions")
        self.assertEqual(self.client.get(reverse("competicions_home")).status_code, 200)
        self.assertEqual(self.client.get(reverse("created")).status_code, 200)
        self.assertEqual(self.client.get(reverse("create")).status_code, 200)

    def test_membership_user_sees_competicions_but_cannot_open_foreign_competition(self):
        user = self._user("membership_user")
        self._add_membership(user, self.comp)
        self.client.force_login(user)

        home_response = self.client.get(reverse("home"))
        self.assertEqual(home_response.status_code, 200)
        self.assertContains(home_response, "Competicions")
        self.assertEqual(self.client.get(reverse("competicions_home")).status_code, 200)

        created_response = self.client.get(reverse("created"))
        self.assertEqual(created_response.status_code, 200)
        self.assertContains(created_response, self.comp.nom)
        self.assertNotContains(created_response, self.other_comp.nom)

        foreign_response = self.client.get(reverse("inscripcions_list", kwargs={"pk": self.other_comp.id}))
        self.assertEqual(foreign_response.status_code, 403)

    def test_platform_admin_sees_all_installed_apps(self):
        user = self._user("platform_admin_user")
        self._add_group(user, "platform_admin")
        self.client.force_login(user)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Calendari")
        self.assertContains(response, "Competicions")
        self.assertContains(response, "Designacions")
        self.assertContains(response, "Informes")

        self.assertEqual(self.client.get(reverse("calendar_home")).status_code, 200)
        self.assertEqual(self.client.get(reverse("designacions_runs_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("annual_report_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("competicions_home")).status_code, 200)

    def test_internal_nav_omits_apps_marked_as_not_installed(self):
        user = self._user("platform_admin_partial")
        self._add_group(user, "platform_admin")
        self.client.force_login(user)

        def _patched_is_installed(app_key):
            if app_key in {"designacions", "informes"}:
                return False
            return real_is_internal_app_installed(app_key)

        with patch("ceeb_web.access.is_internal_app_installed", side_effect=_patched_is_installed):
            response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Calendari")
        self.assertContains(response, "Competicions")
        self.assertNotContains(response, "Designacions")
        self.assertNotContains(response, "Informes")
