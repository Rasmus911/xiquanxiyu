"""Current stock base-unit cost and three bath service classifications."""
from alembic import op

revision = '20261007_ordering_cost'
down_revision = '20261007_insights_cost'
branch_labels = None
depends_on = None


def upgrade():
    from app.schema_maintenance import upgrade_ordering048_schema
    upgrade_ordering048_schema(op.get_bind())


def downgrade():
    raise RuntimeError('Retain cost evidence; use a verified explicit recovery procedure')
