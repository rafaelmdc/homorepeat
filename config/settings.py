"""Django settings for the HomoRepeat web project."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name, "")
    if not value.strip():
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "replace-me")
DEBUG = _env_flag("DJANGO_DEBUG", False)
NO_ADMIN = _env_flag("no_admin", False)
ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS", [])
HOMOREPEAT_TRUST_X_FORWARDED_FOR = _env_flag("HOMOREPEAT_TRUST_X_FORWARDED_FOR", False)

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core.apps.CoreConfig",
    "apps.browser.apps.BrowserConfig",
    "apps.imports.apps.ImportsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.no_admin.NoAdminMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "UTC")
USE_TZ = True
HOMOREPEAT_RUNS_ROOT = os.getenv("HOMOREPEAT_RUNS_ROOT", "").strip()
HOMOREPEAT_IMPORTS_ROOT = os.getenv("HOMOREPEAT_IMPORTS_ROOT", "/data/imports").strip()
HOMOREPEAT_UPLOAD_MAX_ZIP_BYTES = _env_int("HOMOREPEAT_UPLOAD_MAX_ZIP_BYTES", 5 * 1024 * 1024 * 1024)
HOMOREPEAT_UPLOAD_CHUNK_BYTES = _env_int("HOMOREPEAT_UPLOAD_CHUNK_BYTES", 8 * 1024 * 1024)
HOMOREPEAT_UPLOAD_MAX_EXTRACTED_BYTES = _env_int(
    "HOMOREPEAT_UPLOAD_MAX_EXTRACTED_BYTES",
    50 * 1024 * 1024 * 1024,
)
HOMOREPEAT_UPLOAD_MAX_FILES = _env_int("HOMOREPEAT_UPLOAD_MAX_FILES", 200000)
HOMOREPEAT_UPLOAD_INCOMPLETE_RETENTION_HOURS = _env_int("HOMOREPEAT_UPLOAD_INCOMPLETE_RETENTION_HOURS", 24)
HOMOREPEAT_UPLOAD_FAILED_RETENTION_HOURS = _env_int("HOMOREPEAT_UPLOAD_FAILED_RETENTION_HOURS", 168)
HOMOREPEAT_UPLOAD_DISK_PREFLIGHT_ENABLED = _env_flag("HOMOREPEAT_UPLOAD_DISK_PREFLIGHT_ENABLED", True)
HOMOREPEAT_UPLOAD_MIN_FREE_BYTES = _env_int("HOMOREPEAT_UPLOAD_MIN_FREE_BYTES", 1 * 1024 * 1024 * 1024)
HOMOREPEAT_UPLOAD_EXTRACTION_SPACE_MULTIPLIER = float(
    os.getenv("HOMOREPEAT_UPLOAD_EXTRACTION_SPACE_MULTIPLIER", "3.0")
)
HOMOREPEAT_UPLOAD_MAX_ACTIVE_PER_USER = _env_int("HOMOREPEAT_UPLOAD_MAX_ACTIVE_PER_USER", 0)
HOMOREPEAT_UPLOAD_MAX_DAILY_BYTES_PER_USER = _env_int("HOMOREPEAT_UPLOAD_MAX_DAILY_BYTES_PER_USER", 0)
HOMOREPEAT_UPLOAD_MAX_ZIP_BYTES_PER_USER = _env_int("HOMOREPEAT_UPLOAD_MAX_ZIP_BYTES_PER_USER", 0)
HOMOREPEAT_BROWSER_STATS_CACHE_TTL = _env_int("HOMOREPEAT_BROWSER_STATS_CACHE_TTL", 60)

_REDIS_URL = os.getenv("REDIS_URL", "").strip()

if _REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": f"{_REDIS_URL}/1",
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            },
        }
    }

# --- Celery ---
CELERY_BROKER_URL = f"{_REDIS_URL}/0" if _REDIS_URL else "memory://"
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 43200}
CELERY_TASK_ALWAYS_EAGER = _env_flag("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_ROUTES = {
    # Explicit upload-queue tasks must come before the imports wildcard.
    "apps.imports.tasks.extract_uploaded_run": {"queue": "uploads"},
    "apps.imports.tasks.cleanup_stale_uploaded_runs": {"queue": "uploads"},
    # Deletion task uses a short registered name; must be explicit before the wildcard.
    "imports.delete_pipeline_run_job": {"queue": "deletions"},
    # All remaining imports tasks (run_import_batch, reset_stale_import_batches, …)
    "apps.imports.tasks.*": {"queue": "imports"},
    # Explicit downloads-queue tasks before the wildcard (wildcard → payload_graph).
    "apps.browser.tasks.expire_stale_download_builds": {"queue": "downloads"},
    "apps.browser.tasks.*": {"queue": "payload_graph"},
}
CELERY_BEAT_SCHEDULE = {
    "reset-stale-import-batches": {
        "task": "apps.imports.tasks.reset_stale_import_batches",
        "schedule": timedelta(minutes=5),
    },
    "cleanup-stale-uploaded-runs": {
        "task": "apps.imports.tasks.cleanup_stale_uploaded_runs",
        "schedule": timedelta(hours=1),
    },
    "expire-stale-download-builds": {
        "task": "apps.browser.tasks.expire_stale_download_builds",
        "schedule": timedelta(hours=6),
    },
}

if os.getenv("DATABASE_ENGINE", "").strip():
    DATABASES = {
        "default": {
            "ENGINE": os.getenv("DATABASE_ENGINE", "django.db.backends.postgresql"),
            "NAME": os.getenv("DATABASE_NAME", "homorepeat"),
            "USER": os.getenv("DATABASE_USER", "homorepeat"),
            "PASSWORD": os.getenv("DATABASE_PASSWORD", "homorepeat"),
            "HOST": os.getenv("DATABASE_HOST", "postgres"),
            "PORT": os.getenv("DATABASE_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
