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

    def test_the_command_line_runs_with_nothing_set(self):
        # manage.py is the development entry point, so it turns debugging on itself.
        environment = {name: value for name, value in os.environ.items() if not name.startswith("DJANGO_")}
        done = subprocess.run([sys.executable, "manage.py", "check"], cwd=BACKEND, env=environment, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
