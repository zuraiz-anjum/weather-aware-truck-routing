"""
Settings for the weather-aware truck routing service.

Anything that differs between a laptop and a server comes from the
environment: DJANGO_DEBUG, DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS, CACHE_DIR
and the base URLs of the three outside services.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("set DJANGO_SECRET_KEY when DJANGO_DEBUG is 0")
    SECRET_KEY = "development-only-not-a-secret"

ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
# Render tells a service its own hostname.
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])

if not DEBUG:
    # Behind a proxy that terminates TLS and sets X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 30 * 24 * 3600

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "rest_framework",
    "trips",
]

MIDDLEWARE = [
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "truckweather.urls"
WSGI_APPLICATION = "truckweather.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    },
]

# Nothing is stored. Sessions, users and the admin are not installed, so
# there is no database and no migration to run.
DATABASES = {}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True

# The React build is served from the root of the site by WhiteNoise; Django's
# own static files (the browsable API) live under static/. Vite names its
# bundles with a content hash, so they can be cached for good.
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Compressed copies are written beside the files when they are collected,
    # as the Dockerfile does for the React build, and served in their place.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
WHITENOISE_ROOT = FRONTEND_DIST
WHITENOISE_INDEX_FILE = True
WHITENOISE_IMMUTABLE_FILE_TEST = lambda path, url: "/assets/" in url
WHITENOISE_AUTOREFRESH = WHITENOISE_USE_FINDERS = DEBUG

# Geocoding, routes and forecasts are cached so that moving the departure
# time or the load does not go back to the routing server, and so that the
# forecast for a corridor is fetched once an hour rather than once a click.
# Files rather than memory so that gunicorn's workers share one cache.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": os.environ.get("CACHE_DIR", str(BASE_DIR / ".cache")),
        "OPTIONS": {"MAX_ENTRIES": 2000},
    }
}

REST_FRAMEWORK = {
    # No accounts: every request is anonymous and rate-limited by address.
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "120/min", "plan": "20/min"},
    "NUM_PROXIES": int(os.environ.get("NUM_PROXIES", "0")),
    "EXCEPTION_HANDLER": "trips.views.exception_handler",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {"trips": {"level": "INFO"}},
}

# Outside services. All three are public, keyless, and ask callers to say
# who they are.
OSRM_URL = os.environ.get("OSRM_URL", "https://router.project-osrm.org")
OPEN_METEO_URL = os.environ.get("OPEN_METEO_URL", "https://api.open-meteo.com")
PHOTON_URL = os.environ.get("PHOTON_URL", "https://photon.komoot.io")
USER_AGENT = "weather-aware-truck-routing/1.0 (zuraizwork@gmail.com)"
# Connect and read. A coast-to-coast route with every step takes a few
# seconds; a plan makes up to four rounds of requests in series, and all
# of them have to fit inside gunicorn's patience.
HTTP_TIMEOUT = (5, 20)

# How far ahead Open-Meteo forecasts, counting today.
FORECAST_DAYS = 16
