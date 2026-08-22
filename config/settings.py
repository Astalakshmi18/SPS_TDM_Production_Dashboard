"""
Swift Prosys Production Dashboard - Django settings.

Database:
    Defaults to SQLite so the project runs immediately with zero setup.
    To switch to SQL Server:
      1. pip install mssql-django pyodbc   (uncomment in requirements.txt)
      2. Install the "ODBC Driver 17/18 for SQL Server" on the host machine.
      3. Set env vars: DB_ENGINE=mssql, DB_NAME, DB_HOST, DB_USER, DB_PASSWORD
         (see DATABASES below - it reads them automatically when DB_ENGINE=mssql)
"""
import os
from pathlib import Path
from decouple import config as env

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = env("SECRET_KEY", default="django-insecure-change-me-for-production")
DEBUG = env("DEBUG", cast=bool, default=True)
ALLOWED_HOSTS = env("ALLOWED_HOSTS", default="*").split(",")

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "rest_framework",
    "widget_tweaks",

    "apps.accounts.apps.AccountsConfig",
    "apps.branches.apps.BranchesConfig",
    "apps.projects.apps.ProjectsConfig",
    "apps.inventory.apps.InventoryConfig",
    "apps.dashboard.apps.DashboardConfig",
    "apps.mapping.apps.MappingConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
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
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DB_ENGINE = env("DB_ENGINE", default="sqlite")

if DB_ENGINE == "mssql":
    DATABASES = {
        "default": {
            "ENGINE": "mssql",
            "NAME": env("DB_NAME", default="SwiftProsysDB"),
            "HOST": env("DB_HOST", default="localhost"),
            "PORT": env("DB_PORT", default=""),
            "USER": env("DB_USER", default=""),
            "PASSWORD": env("DB_PASSWORD", default=""),
            "OPTIONS": {"driver": env("DB_DRIVER", default="ODBC Driver 17 for SQL Server")},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            # "database is locked" on SQLite happens because the default
            # sqlite3 busy-timeout is only 5s and the default rollback-journal
            # mode makes writers block ALL readers (and vice versa) for the
            # whole transaction. With auto-sync pulling Google Sheets on page
            # load, "Sync All" writing several projects back-to-back, and the
            # dev server + /admin both hitting the same file, that 5s window
            # is easy to blow through. `timeout` below raises how long a
            # connection will wait for the lock before raising; WAL mode
            # (set via the connection_created signal further down) is the
            # real fix - it lets reads proceed concurrently with a writer.
            "OPTIONS": {"timeout": 30},
        }
    }

    # Enable SQLite's Write-Ahead-Logging mode on every new connection. WAL
    # is per-database-file (persists in the file itself once set, but this
    # keeps it explicit and self-healing if the file is ever recreated) and
    # is the standard fix for "database is locked" under concurrent
    # readers+writers - readers no longer block a writer and vice versa.
    from django.db.backends.signals import connection_created

    def _configure_sqlite(sender, connection, **kwargs):
        if connection.vendor == "sqlite":
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA busy_timeout=30000;")

    connection_created.connect(_configure_sqlite)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "accounts:login"

# Folder that holds one JSON mapping file per project template (BPW, Latvia, SSH, HOR, ...)
MAPPINGS_DIR = BASE_DIR / "mappings"

# Optional: enables AI-assisted mapping detection (apps/mapping/autodetect.py)
# for Excel formats that don't match the standard PM02 layout. Auto-detect
# works fine without this - it just falls back to keyword scanning instead
# of semantic understanding. Get a key at https://aistudio.google.com/apikey
GEMINI_API_KEY = env("GEMINI_API_KEY", default="")

# The four physical branches. Kept here (not just DB) so seed/migration scripts
# and the mapping engine can validate against a single source of truth.
BRANCH_CHOICES = [
    ("TDM", "Tindivanam"),
    ("CHN", "Chennai"),
    ("KPM", "Kanchipuram"),
    ("MDU", "Madurai"),
]
