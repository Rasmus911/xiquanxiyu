import hashlib
import sqlite3


def test_sqlite_backup_restores_real_money_and_integrity(tmp_path):
    from app import create_app
    from app.config import TestConfig
    from app.extensions import db
    from app.models import Member
    from app.seed import seed_defaults
    class BackupConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'source.sqlite').as_posix()}"
        RESET_PRIVATE_DIR = str(tmp_path / 'private')
    app = create_app(BackupConfig)
    with app.app_context():
        db.create_all()
        seed_defaults()
        db.session.add(Member(phone='123', balance=30))
        db.session.commit()
        from app import reset_backup
        with db.engine.connect() as connection:
            backup = reset_backup.create_database_backup(connection, 'test-reset', 'test-period')
        from pathlib import Path
        path = Path(backup.private_path)
        assert path.is_file() and path.stat().st_size == backup.size
        assert hashlib.sha256(path.read_bytes()).hexdigest() == backup.sha256
        with sqlite3.connect(path) as restored:
            assert restored.execute('pragma integrity_check').fetchone()[0] == 'ok'
            assert restored.execute('select balance from members').fetchone()[0] == 30
        db.session.remove()
        db.engine.dispose()
