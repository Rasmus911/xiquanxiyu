"""Freeze pre-0.5.0 actor foreign keys when replaying earlier schema revisions."""
from sqlalchemy import ForeignKeyConstraint, MetaData, inspect

from .extensions import db


def create_pre_identity_table(connection, table, *, exclude_columns=()):
    identity_exists = inspect(connection).has_table('employee_identities')
    if identity_exists and not exclude_columns:
        table.create(connection, checkfirst=True)
        return
    metadata = MetaData()
    for existing in db.metadata.tables.values():
        existing.to_metadata(metadata)
    historical = metadata.tables[table.name]
    # Earlier revisions must not pre-create columns owned by later migrations.
    for name in exclude_columns:
        historical._columns.remove(historical.c[name])
    for constraint in list(historical.foreign_key_constraints):
        if not identity_exists and any(element.target_fullname == 'employee_identities.id' for element in constraint.elements):
            references = [element.target_fullname.replace('employee_identities.id', 'employees.id')
                          for element in constraint.elements]
            columns = list(constraint.column_keys)
            historical.constraints.remove(constraint)
            for element in constraint.elements:
                historical.foreign_keys.discard(element)
                element.parent.foreign_keys.discard(element)
            historical.append_constraint(ForeignKeyConstraint(columns, references, name=constraint.name,
                ondelete=constraint.ondelete, onupdate=constraint.onupdate))
    historical.create(connection, checkfirst=True)
