"""Application and database configuration loader."""

import os
import secrets
from pathlib import Path
import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_CONFIG_PATH = BASE_DIR / "db_config.yaml"
DEFAULT_INSTANCE_DIR = BASE_DIR / "instance"


def load_db_config(config_path: str | Path | None = None) -> dict:
    """Load PostgreSQL connection settings from YAML with optional env overrides."""
    path = Path(config_path) if config_path else Path(
        os.environ.get("IMS_DB_CONFIG", DEFAULT_DB_CONFIG_PATH)
    )
    if not path.exists():
        raise FileNotFoundError(f"Database configuration file not found: {path}")

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    db_section = raw.get("database")
    if not isinstance(db_section, dict):
        raise KeyError("db_config.yaml must contain a 'database' mapping.")

    required = ("host", "port", "database", "user", "password")
    missing = [k for k in required if k not in db_section]
    if missing:
        raise KeyError(f"Missing database config keys: {', '.join(missing)}")

    return {
        "host": os.environ.get("IMS_DB_HOST", str(db_section["host"])),
        "port": int(os.environ.get("IMS_DB_PORT", db_section["port"])),
        "dbname": os.environ.get("IMS_DB_NAME", str(db_section["database"])),
        "user": os.environ.get("IMS_DB_USER", str(db_section["user"])),
        "password": os.environ.get("IMS_DB_PASSWORD", str(db_section["password"])),
        "connect_timeout": 10,
    }


def _load_or_create_secret_key(instance_dir: Path) -> str:
    env_key = os.environ.get("IMS_SECRET_KEY")
    if env_key:
        return env_key

    instance_dir.mkdir(parents=True, exist_ok=True)
    key_file = instance_dir / "secret_key"
    if key_file.exists():
        stored = key_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored

    generated = secrets.token_hex(32)
    key_file.write_text(generated, encoding="utf-8")
    return generated


def build_flask_config(test_config: dict | None = None) -> dict:
    """Build Flask configuration dictionary."""
    instance_dir = Path(
        (test_config or {}).get("INSTANCE_DIR", DEFAULT_INSTANCE_DIR)
    )
    upload_dir = instance_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "SECRET_KEY": _load_or_create_secret_key(instance_dir),
        "INSTANCE_DIR": str(instance_dir),
        "UPLOAD_DIR": str(upload_dir),
        "MAX_CONTENT_LENGTH": 16 * 1024 * 1024,  # 16 MB max upload
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "JSON_SORT_KEYS": False,
        "DB_CONFIG": load_db_config(
            (test_config or {}).get("DB_CONFIG_PATH")
        ),
    }

    if test_config:
        config.update(test_config)
        if "DB_CONFIG" not in test_config and any(
            k.startswith("IMS_DB_") for k in os.environ
        ):
            config["DB_CONFIG"] = load_db_config(
                test_config.get("DB_CONFIG_PATH")
            )

    return config
