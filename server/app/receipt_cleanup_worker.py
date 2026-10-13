"""Private-network owner job, with no HTTP server, migrations or reset recovery."""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import create_app
from .extensions import db
from .receipt_retention import cleanup_expired_receipts, next_midnight

HEALTH = Path('/tmp/xiquan-receipt-cleanup-health.json')
HEAD = '20261011_service_receipts'
SUPPORTED_SCHEMAS = {HEAD, '20261012_physical_membership', '20261013_wristband_chip',
                     '20261013_manual_inventory_excel'}


def require_receipt_schema(connection):
    if connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one() not in SUPPORTED_SCHEMAS:
        raise RuntimeError('Receipt schema not ready')


def main():
    if '--health' in sys.argv:
        try:
            value=json.loads(HEALTH.read_text())
            return 0 if value['ok'] is True and 0<=time.time()-value['checked_at']<=120 else 1
        except Exception: return 1
    app=create_app()
    if not app.config.get('MAINTENANCE_PROCESS') or app.config.get('AUTO_CREATE_DB'):
        raise RuntimeError('Receipt worker requires private maintenance configuration')
    while True:
        ok=False
        try:
            with app.app_context():
                with db.engine.connect() as connection:
                    require_receipt_schema(connection)
                cleanup_expired_receipts()
                ok=True
        except Exception:
            app.logger.error('Receipt cleanup deferred; no business data cleared. Inspect private owner configuration.')
        temporary=HEALTH.with_suffix('.tmp')
        temporary.write_text(json.dumps({'ok':ok,'checked_at':time.time()}))
        temporary.chmod(0o600);os.replace(temporary,HEALTH)
        now=datetime.now(timezone.utc)
        time.sleep(min(60,max(1,(next_midnight(now)-now).total_seconds())))


if __name__=='__main__': raise SystemExit(main())
