import hashlib
import json
from pathlib import Path

from flask_migrate import upgrade
from sqlalchemy import inspect, text

from app import create_app
from app.audit_service import verify_audit_chain, write_audit
from app.config import TestConfig
from app.extensions import db


def test_upgrade_preserves_legacy_audit_and_supports_new_signed_records(tmp_path):
    class MigrationConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"

    application = create_app(MigrationConfig)
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with application.app_context():
        upgrade(directory=migrations, revision="20260927_paid_pass_cards")
        payload = {
            "chain_index": 1,
            "employee_id": None,
            "terminal_id": None,
            "action": "legacy.test",
            "entity_type": "test",
            "entity_id": None,
            "details": {},
            "request_id": None,
            "prev_hash": "0" * 64,
        }
        old_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        db.session.execute(
            text("""
            INSERT INTO audit_logs
              (id, chain_index, action, entity_type, details, prev_hash, current_hash, created_at)
            VALUES ('legacy-test', 1, 'legacy.test', 'test', '{}', :prev, :hash, '2026-09-01 08:00:00')
        """),
            {"prev": "0" * 64, "hash": old_hash},
        )
        db.session.commit()
        upgrade(directory=migrations, revision="20260930_security_evidence")
        assert "revoked_sessions" in inspect(db.engine).get_table_names()
        assert verify_audit_chain() == (True, None)
        with application.test_request_context("/migration-test"):
            write_audit("security.test", "test", None, {})
            db.session.commit()
        assert verify_audit_chain() == (True, None)
        assert db.session.execute(text("SELECT current_hash FROM audit_logs WHERE chain_index=1")).scalar() == old_hash
        assert (
            db.session.execute(text("SELECT version_num FROM alembic_version")).scalar() == "20260930_security_evidence"
        )
        db.session.remove()
        db.engine.dispose()
