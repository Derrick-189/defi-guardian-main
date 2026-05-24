import os
from pathlib import Path

# Normalise DATABASE_URL once at import time so every module that imports
# `config` gets the same resolved string.  Covers both Render's
# 'postgres://…' form and the SQLAlchemy 2.x-required 'postgresql://…' form.
_RAW_DB_URL = os.environ.get("DATABASE_URL")
if _RAW_DB_URL and _RAW_DB_URL.startswith("postgres://"):
    _RAW_DB_URL = "postgresql://" + _RAW_DB_URL[len("postgres://"):]

class Config:
    """Base configuration."""
    PROJECT_DIR = Path(__file__).parent.parent
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me-in-production")

    # Use the module-level _RAW_DB_URL so the value is always consistent
    # whether config.py is imported stand-alone or via flask-sqlalchemy.
    SQLALCHEMY_DATABASE_URI = _RAW_DB_URL or f"sqlite:///{PROJECT_DIR}/web_portal/defi_guardian.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Celery / Redis
    CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # Uploads
    UPLOAD_FOLDER = PROJECT_DIR / "web_portal" / "uploads"
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB

    # Verification
    VSERVER_URL = os.environ.get("VSERVER_URL", "http://127.0.0.1:9000")
    VSERVER_TOKEN = os.environ.get("VSERVER_TOKEN")

    # External APIs
    ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    TESTING = False

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    TESTING = False

class TestingConfig(Config):
    """Testing configuration."""
    DEBUG = False
    TESTING = True
    DATABASE = ":memory:"

config_by_name = {
    "dev": DevelopmentConfig,
    "prod": ProductionConfig,
    "test": TestingConfig
}
