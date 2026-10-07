"""Attribute preserved business evidence to its initial period; never execute a reset."""
from alembic import op

revision = '20261002_business_period_reset'
down_revision = '20260930_security_evidence'
branch_labels = None
depends_on = None


def upgrade():
    from app.schema_maintenance import upgrade_business_period_schema
    upgrade_business_period_schema(op.get_bind())


def downgrade():
    # Dropping attribution after a switch would merge historical balances and phone identities.
    raise RuntimeError('Business-period migration cannot be downgraded; restore a verified pre-upgrade backup')
