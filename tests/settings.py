"""Settings for the test suite. Wagtail's apps are added when Wagtail is installed."""

from __future__ import annotations

import importlib.util

from django_converter_studio import formats

WAGTAIL = importlib.util.find_spec("wagtail") is not None

SECRET_KEY = "tests-only-not-secret"
DEBUG = False
USE_TZ = True
ALLOWED_HOSTS = ["testserver", "localhost"]
ROOT_URLCONF = "tests.urls"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django_converter_studio",
    "tests.testapp",
]
if WAGTAIL:
    INSTALLED_APPS += [
        "django_converter_studio.wagtail",
        "wagtail.sites",
        "wagtail.users",
        "wagtail.documents",
        "wagtail.images",
        "wagtail.search",
        "wagtail.admin",
        "wagtail",
        "modelcluster",
        "taggit",
        "django_filters",
    ]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

# Files live in memory: nothing in the package may assume a local file system.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
STATIC_URL = "/static/"
MEDIA_URL = "/media/"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CONVERTER_STUDIO_API_KEY = "cvs_live_test_key_0123456789"
CONVERTER_STUDIO_BASE_URL = "https://api.test/api"
CONVERTER_STUDIO_RUN = "inline"

WAGTAIL_SITE_NAME = "Tests"
WAGTAILADMIN_BASE_URL = "http://testserver"
WAGTAILIMAGES_IMAGE_FORM_BASE = "django_converter_studio.wagtail.forms.ConvertingImageForm"
WAGTAILIMAGES_EXTENSIONS = [
    "avif",
    "gif",
    "jpg",
    "jpeg",
    "png",
    "webp",
    *formats.RAW,
    *formats.VECTOR,
]
CONVERTER_STUDIO_WAGTAIL_DOCUMENTS = {"docx": "pdf", "odt": "pdf"}
# HEIC is left out of WAGTAILIMAGES_EXTENSIONS on purpose (see test_wagtail.py).
SILENCED_SYSTEM_CHECKS = ["converter_studio.W102"]
