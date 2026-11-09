"""The settings module as it comes out under different environments, loaded afresh each time."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

BACKEND = Path(__file__).resolve().parents[2]
A_KEY = "k" * 50


def settings_under(**variables):
    """The settings module evaluated with exactly these environment variables set."""
    with mock.patch.dict(os.environ, variables, clear=True):
        spec = importlib.util.spec_from_file_location("settings_under_test", BACKEND / "truckweather" / "settings.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class SettingsTests(SimpleTestCase):
    def test_production_is_the_default_and_wants_a_key(self):
        with self.assertRaises(ImproperlyConfigured):
            settings_under()
        production = settings_under(DJANGO_SECRET_KEY=A_KEY)
        self.assertFalse(production.DEBUG)
        self.assertEqual(production.SECRET_KEY, A_KEY)
        self.assertEqual(production.SECURE_PROXY_SSL_HEADER, ("HTTP_X_FORWARDED_PROTO", "https"))
        self.assertEqual(production.SECURE_HSTS_SECONDS, 30 * 24 * 3600)

    def test_development_needs_nothing_but_the_flag(self):
        development = settings_under(DJANGO_DEBUG="1")
        self.assertTrue(development.DEBUG)
        self.assertTrue(development.SECRET_KEY)
        self.assertFalse(hasattr(development, "SECURE_HSTS_SECONDS"))

    def test_the_loopback_names_are_always_allowed(self):
        self.assertEqual(settings_under(DJANGO_DEBUG="1").ALLOWED_HOSTS, ["localhost", "127.0.0.1", "[::1]"])
        named = settings_under(
            DJANGO_SECRET_KEY=A_KEY, DJANGO_ALLOWED_HOSTS="trucks.example.com,localhost", RENDER_EXTERNAL_HOSTNAME="trucks.onrender.com")
        self.assertEqual(named.ALLOWED_HOSTS, ["trucks.example.com", "localhost", "trucks.onrender.com", "127.0.0.1", "[::1]"])

    def test_a_subscription_key_moves_the_forecasts_to_the_customer_endpoint(self):
        keyed = settings_under(DJANGO_DEBUG="1", OPEN_METEO_API_KEY="abc")
        self.assertEqual(keyed.OPEN_METEO_URL, "https://customer-api.open-meteo.com")
        # A URL given on purpose is kept, as for a self-hosted copy.
        own = settings_under(DJANGO_DEBUG="1", OPEN_METEO_API_KEY="abc", OPEN_METEO_URL="http://meteo.internal")
        self.assertEqual(own.OPEN_METEO_URL, "http://meteo.internal")
        self.assertEqual(settings_under(DJANGO_DEBUG="1").OPEN_METEO_API_KEY, "")

    def test_the_browser_is_sent_to_the_public_service_whatever_the_server_uses(self):
        own = settings_under(DJANGO_DEBUG="1", OPEN_METEO_API_KEY="abc", OPEN_METEO_URL="http://meteo.internal")
        self.assertEqual(own.OPEN_METEO_PUBLIC_URL, "https://api.open-meteo.com")
        mirror = settings_under(DJANGO_DEBUG="1", OPEN_METEO_PUBLIC_URL="http://mirror.example")
        self.assertEqual(mirror.OPEN_METEO_PUBLIC_URL, "http://mirror.example")

    def test_the_frame_header_goes_on_before_whitenoise_answers_for_the_page(self):
        development = settings_under(DJANGO_DEBUG="1")
        self.assertLess(development.MIDDLEWARE.index("django.middleware.clickjacking.XFrameOptionsMiddleware"),
                        development.MIDDLEWARE.index("whitenoise.middleware.WhiteNoiseMiddleware"))
        self.assertEqual(development.WHITENOISE_MAX_AGE, 0)

    def test_the_command_line_runs_with_nothing_set(self):
        # manage.py is the development entry point, so it turns debugging on itself.
        environment = {name: value for name, value in os.environ.items() if not name.startswith("DJANGO_")}
        done = subprocess.run([sys.executable, "manage.py", "check"], cwd=BACKEND, env=environment, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
