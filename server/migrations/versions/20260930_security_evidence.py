"""Authenticated audit evidence and immutable financial records."""

import sqlalchemy as sa
from alembic import op

revision = '20260930_security_evidence'
down_revision = '20260927_paid_pass_cards'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('audit_logs', sa.Column('integrity_version', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('audit_logs', sa.Column('context', sa.JSON(), nullable=False, server_default='{}'))
    op.create_table('revoked_sessions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('employee_id', sa.String(36), sa.ForeignKey('employees.id'), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=False),
    )
    from app.database_guards import install_database_guards
    install_database_guards(op.get_bind())
    # Old tokens did not have the new session policy. Require a fresh login after this upgrade.
    op.execute(sa.text('UPDATE employees SET session_version = session_version + 1'))


def downgrade():
    from app.database_guards import remove_database_guards
    remove_database_guards(op.get_bind())
    op.drop_table('revoked_sessions')
    op.drop_column('audit_logs', 'context')
    op.drop_column('audit_logs', 'integrity_version')
