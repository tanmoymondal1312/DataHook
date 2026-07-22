"""
Django settings for the DataHook project.

All environment-specific configuration is driven by a `.env` file (see
`.env.example`). Defaults are chosen so the project runs out of the box for
local development while remaining Postgres/production friendly.
"""

from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
import os
import sys

BASE_DIR = Path(__file__).resolve().parent.parent

# Throttle counters live in a process-wide cache, so under `manage.py test`
# they leak between test cases and 429 unrelated ones once the suite grows.
# Rate limiting is therefore switched off while testing (see REST_FRAMEWORK).
TESTING = "test" in sys.argv

# Load environment variables from a .env file at the project root, if present.
load_dotenv(BASE_DIR / ".env")


def env_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def env_list(key: str, default=None):
    val = os.getenv(key)
    if not val:
        return list(default or [])
    return [item.strip() for item in val.split(",") if item.strip()]


# --------------------------------------------------------------------------- #
# Core
# --------------------------------------------------------------------------- #
SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "django-insecure-dev-only-change-me-in-production-0123456789abcdef",
)

DEBUG = env_bool("DEBUG", True)

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", ["localhost", "127.0.0.1"])

# Public base URL used when building ingest URLs and code snippets.
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")


# --------------------------------------------------------------------------- #
# Applications
# --------------------------------------------------------------------------- #
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "corsheaders",
    "django_filters",
    # Local
    "accounts",
    "endpoints",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "config.middleware.IngestCorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# --------------------------------------------------------------------------- #
# Database — SQLite by default, Postgres when DATABASE_URL-style vars are set.
# --------------------------------------------------------------------------- #
if os.getenv("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB"),
            "USER": os.getenv("POSTGRES_USER", "postgres"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
            "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# --------------------------------------------------------------------------- #
# Internationalization
# --------------------------------------------------------------------------- #
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True


# --------------------------------------------------------------------------- #
# Static files
# --------------------------------------------------------------------------- #
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --------------------------------------------------------------------------- #
# Django REST Framework
# --------------------------------------------------------------------------- #
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    # Only submissions are paginated (SubmissionListView applies it explicitly),
    # so no global pagination — endpoints/attributes return plain arrays.
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
    ),
    # The public export endpoint uses ?format=csv|json as a plain query param.
    # Disable DRF's format-suffix override so it doesn't hijack negotiation
    # (which would 404 on 'csv' for lack of a matching renderer).
    "URL_FORMAT_OVERRIDE": None,
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.ScopedRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        # Public ingest endpoint — throttled per client IP.
        "ingest": None if TESTING else os.getenv("INGEST_THROTTLE_RATE", "60/minute"),
        # Registration/login — light protection against abuse.
        "auth": None if TESTING else os.getenv("AUTH_THROTTLE_RATE", "20/minute"),
    },
    "EXCEPTION_HANDLER": "config.exceptions.custom_exception_handler",
}


# --------------------------------------------------------------------------- #
# Simple JWT
# --------------------------------------------------------------------------- #
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=int(os.getenv("ACCESS_TOKEN_LIFETIME_MIN", "60"))
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=int(os.getenv("REFRESH_TOKEN_LIFETIME_DAYS", "14"))
    ),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}


# --------------------------------------------------------------------------- #
# CORS
#   - django-cors-headers governs ONLY the admin API (CORS_URLS_REGEX = ^/api/),
#     restricted to the app's known origins (or all origins if you flip the env).
#   - The public /ingest/ path is handled separately by IngestCorsMiddleware,
#     which always allows all origins so plain HTML forms / apps from any site
#     can POST. (Ingest is authorized by the X-API-Key header, not cookies.)
# --------------------------------------------------------------------------- #
CORS_ALLOW_ALL_ORIGINS = env_bool("CORS_ALLOW_ALL_ORIGINS", False)
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", [])
CORS_ALLOW_CREDENTIALS = True
# Restrict django-cors-headers to the admin API only; ingest CORS is separate.
CORS_URLS_REGEX = r"^/api/.*$"


# --------------------------------------------------------------------------- #
# Firebase / FCM
# --------------------------------------------------------------------------- #
# Path to the service-account JSON. When unset, push notifications are disabled
# gracefully (the rest of the API keeps working).
FIREBASE_CREDENTIALS = os.getenv("FIREBASE_CREDENTIALS", "")


# --------------------------------------------------------------------------- #
# Google Sign-In
# --------------------------------------------------------------------------- #
# The OAuth **Web** client ID of the Firebase project (client_type 3 in the
# app's google-services.json). The Android client requests an ID token with
# this as its audience, and `/api/auth/google/` verifies it against this value.
# Leave blank to disable Google sign-in (the endpoint then returns 400).
GOOGLE_WEB_CLIENT_ID = os.getenv("GOOGLE_WEB_CLIENT_ID", "")


# --------------------------------------------------------------------------- #
# Logging — surface FCM/ingest issues without crashing requests.
# --------------------------------------------------------------------------- #
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[{levelname}] {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "endpoints": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}


# --------------------------------------------------------------------------- #
# Production hardening (active only when DEBUG is off).
# Django runs behind nginx (TLS terminated at nginx / Cloudflare origin), so we
# teach it to trust the forwarded scheme and the HTTPS origin for CSRF.
# --------------------------------------------------------------------------- #
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", [BASE_URL])
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
