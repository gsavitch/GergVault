import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "gergvault-dev-secret")
DEBUG = os.environ.get("DEBUG", "1").lower() in {"1", "true", "yes", "on"}
ALLOWED_HOSTS = [host.strip() for host in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "card_vault",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "card_vault.middleware.GergVaultRateLimitMiddleware",
    "card_vault.middleware.GergVaultTrafficMiddleware",
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
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

if os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ.get("POSTGRES_USER", "postgres"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", str(BASE_DIR / "media")))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/card-vault/"
LOGOUT_REDIRECT_URL = "/"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = os.environ.get("USE_X_FORWARDED_HOST", "1").lower() in {"1", "true", "yes", "on"}
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "0").lower() in {"1", "true", "yes", "on"}
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0").lower() in {"1", "true", "yes", "on"}
CSRF_COOKIE_SECURE = os.environ.get("CSRF_COOKIE_SECURE", "0").lower() in {"1", "true", "yes", "on"}
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0") or "0")
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get("SECURE_HSTS_INCLUDE_SUBDOMAINS", "0").lower() in {"1", "true", "yes", "on"}
SECURE_HSTS_PRELOAD = os.environ.get("SECURE_HSTS_PRELOAD", "0").lower() in {"1", "true", "yes", "on"}
SECURE_REFERRER_POLICY = os.environ.get("SECURE_REFERRER_POLICY", "same-origin")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@gergvault.halobridge.ai")
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
GERGVAULT_SERVE_MEDIA = os.environ.get("GERGVAULT_SERVE_MEDIA", "1").lower() in {"1", "true", "yes", "on"}
GERGVAULT_TRACK_TRAFFIC = os.environ.get("GERGVAULT_TRACK_TRAFFIC", "1").lower() in {"1", "true", "yes", "on"}
GERGVAULT_RATE_LIMIT_ENABLED = os.environ.get("GERGVAULT_RATE_LIMIT_ENABLED", "1").lower() in {"1", "true", "yes", "on"}
GERGVAULT_RATE_LIMITS = {
    "/accounts/login/": (int(os.environ.get("GERGVAULT_LOGIN_RATE_LIMIT", "20")), 300),
    "/accounts/signup/": (int(os.environ.get("GERGVAULT_SIGNUP_RATE_LIMIT", "10")), 3600),
    "/card-vault/intake/new/": (int(os.environ.get("GERGVAULT_UPLOAD_RATE_LIMIT", "30")), 3600),
    "/api/card-vault/intake/batch/": (int(os.environ.get("GERGVAULT_API_UPLOAD_RATE_LIMIT", "30")), 3600),
}
GERGVAULT_TRAFFIC_EXCLUDED_PREFIXES = tuple(
    prefix.strip()
    for prefix in os.environ.get("GERGVAULT_TRAFFIC_EXCLUDED_PREFIXES", "/static/,/media/,/favicon.ico").split(",")
    if prefix.strip()
)

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
}
