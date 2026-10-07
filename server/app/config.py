import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else BASE_DIR
load_dotenv(ENV_DIR / ".env")
DEFAULT_DATA_DIR = Path(
    os.getenv(
        "XIQUAN_DATA_DIR",
        str(Path.cwd() / "data" if getattr(sys, "frozen", False) else BASE_DIR / "instance"),
    )
).resolve()
DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-secret-change-me-use-32-bytes")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-jwt-secret-change-me-use-32-bytes")
    AUDIT_HMAC_KEY = os.getenv("AUDIT_HMAC_KEY", "").strip()
    PRODUCTION = os.getenv("XIQUAN_PRODUCTION", "0") == "1"
    TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "0") == "1"
    MAX_CONTENT_LENGTH = 512 * 1024
    BOOTSTRAP_TOKEN = os.getenv("BOOTSTRAP_TOKEN", "").strip()
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DATA_DIR / 'bathhouse.db'}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_AS_ASCII = False
    CORS_ORIGINS = [
        item.strip()
        for item in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,https://localhost,null",
        ).split(",")
        if item.strip()
    ]
    AUTO_CREATE_DB = os.getenv("AUTO_CREATE_DB", "1") == "1"
    SOCKETIO_ASYNC_MODE = os.getenv("SOCKETIO_ASYNC_MODE") or None
    ACCESS_POLICY_LEGACY_COMPAT = False
    # This release supports one API process and one replica, including sockets.
    API_WORKERS = int(os.getenv('API_WORKERS', '1'))
    WEB_CONCURRENCY = int(os.getenv('WEB_CONCURRENCY', '1'))
    API_REPLICAS = int(os.getenv('API_REPLICAS', '1'))
    SOCKETIO_POLICY_POLL_SECONDS = 1
    RESET_DATABASE_URL = os.getenv('RESET_DATABASE_URL', '').strip()
    RESET_BACKUP_DATABASE_URL = os.getenv('RESET_BACKUP_DATABASE_URL', '').strip()
    RESET_PRIVATE_DIR = os.getenv('RESET_PRIVATE_DIR', '').strip()
    PG_DUMP_PATH = os.getenv('PG_DUMP_PATH', 'pg_dump')
    PG_RESTORE_PATH = os.getenv('PG_RESTORE_PATH', 'pg_restore')
    RESET_WORKER_ENABLED = os.getenv('RESET_WORKER_ENABLED','1') == '1'
    MAINTENANCE_PROCESS = os.getenv('MAINTENANCE_PROCESS','0') == '1'
    SMS_ENABLED = os.getenv("SMS_ENABLED", "0") == "1"
    SMS_ADMIN_PHONE = os.getenv("SMS_ADMIN_PHONE", "18631459666").strip()
    SMS_SIGN_NAME = os.getenv("SMS_SIGN_NAME", "溪泉洗浴").strip()
    SMS_STORED_CARD_TEMPLATE_CODE = os.getenv("SMS_STORED_CARD_TEMPLATE_CODE", "").strip()
    SMS_PASS_CARD_TEMPLATE_CODE = os.getenv("SMS_PASS_CARD_TEMPLATE_CODE", "").strip()
    SMS_ADMIN_TEMPLATE_CODE = os.getenv("SMS_ADMIN_TEMPLATE_CODE", "").strip()
    SMS_ENDPOINT = os.getenv("SMS_ENDPOINT", "dysmsapi.aliyuncs.com").strip()
    ALIBABA_CLOUD_ACCESS_KEY_ID = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "").strip()
    ALIBABA_CLOUD_ACCESS_KEY_SECRET = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "").strip()
    JWT_ACCESS_TOKEN_EXPIRES = 60 * 60 * 8
    JWT_REFRESH_TOKEN_EXPIRES = 60 * 60 * 24 * 30


class TestConfig(Config):
    TESTING = True
    ACCESS_POLICY_LEGACY_COMPAT = True
    SOCKETIO_POLICY_POLL_SECONDS = 0
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    AUTO_CREATE_DB = False
    SOCKETIO_ASYNC_MODE = "threading"
    JWT_ACCESS_TOKEN_EXPIRES = 3600
    SMS_ENABLED = False
    RESET_WORKER_ENABLED = False
