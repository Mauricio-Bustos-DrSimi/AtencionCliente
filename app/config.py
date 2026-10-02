from dataclasses import dataclass
import os
from pathlib import Path
import secrets


ROOT_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = ROOT_DIR / ".env") -> None:
    """Load a small .env file without adding a dotenv dependency."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_host: str = os.getenv("APP_HOST", "127.0.0.1")
    app_port: int = int(os.getenv("APP_PORT", "8000"))
    secret_key: str = os.getenv("APP_SECRET_KEY") or secrets.token_urlsafe(48)
    database_path: Path = Path(
        os.getenv("APP_DATABASE_PATH", str(ROOT_DIR / "data" / "app_atencion.sqlite3"))
    )

    attention_server: str = os.getenv("ATENCION_SQL_SERVER", "")
    attention_database: str = os.getenv("ATENCION_SQL_DATABASE", "simicl_almacen")
    attention_user: str = os.getenv("ATENCION_SQL_USER", "")
    attention_password: str = os.getenv("ATENCION_SQL_PASSWORD", "")
    attention_driver: str = os.getenv(
        "ATENCION_SQL_DRIVER", "ODBC Driver 17 for SQL Server"
    )
    attention_trust_certificate: str = os.getenv(
        "ATENCION_SQL_TRUST_CERTIFICATE", "yes"
    )

    locales_server: str = os.getenv("LOCALES_SQL_SERVER", "")
    locales_database: str = os.getenv("LOCALES_SQL_DATABASE", "DW_Simi")
    locales_user: str = os.getenv("LOCALES_SQL_USER", "")
    locales_password: str = os.getenv("LOCALES_SQL_PASSWORD", "")
    locales_driver: str = os.getenv(
        "LOCALES_SQL_DRIVER", "ODBC Driver 17 for SQL Server"
    )
    locales_trust_certificate: str = os.getenv(
        "LOCALES_SQL_TRUST_CERTIFICATE", "yes"
    )


settings = Settings()


def sql_connection_string(source: str) -> str:
    if source == "attention":
        server = settings.attention_server
        database = settings.attention_database
        user = settings.attention_user
        password = settings.attention_password
        driver = settings.attention_driver
        trust = settings.attention_trust_certificate
    elif source == "locales":
        server = settings.locales_server
        database = settings.locales_database
        user = settings.locales_user
        password = settings.locales_password
        driver = settings.locales_driver
        trust = settings.locales_trust_certificate
    else:
        raise ValueError("Unknown SQL source")

    missing = [
        name
        for name, value in (
            ("server", server),
            ("user", user),
            ("password", password),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"SQL connection settings are missing: {', '.join(missing)}")

    def quoted(value: str) -> str:
        return "{" + value.replace("}", "}}") + "}"

    return (
        f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};"
        f"UID={quoted(user)};PWD={quoted(password)};"
        f"TrustServerCertificate={trust};"
    )
