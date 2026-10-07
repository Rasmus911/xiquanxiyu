"""Focused startup tests: no Flask app or live PostgreSQL is created."""
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest


def checks():
    source = Path(__file__).parents[1] / 'app' / 'deployment_checks.py'
    assert source.is_file(), 'Missing fail-closed deployment startup helper'
    spec = importlib.util.spec_from_file_location('deployment_checks', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def environment():
    return {
        'DATABASE_URL': 'postgresql+psycopg://xiquan_app:test@postgres/bathhouse',
        'RUNTIME_DATABASE_URL': 'postgresql+psycopg://xiquan_app:test@postgres/bathhouse',
        'RESET_DATABASE_URL': 'postgresql+psycopg://xiquan_reset:test@postgres:5432/bathhouse',
        'RESET_BACKUP_DATABASE_URL': 'postgresql+psycopg://xiquan_backup:test@postgres/bathhouse',
        'RESET_PRIVATE_DIR': '/var/lib/xiquan-reset',
        'AUTO_CREATE_DB': '0', 'RUN_MIGRATIONS': '0', 'SEED_DEFAULTS': '0',
        'API_WORKERS': '1', 'WEB_CONCURRENCY': '1', 'API_REPLICAS': '1',
    }


def test_config_accepts_same_endpoint_with_default_port():
    assert checks().validate_environment(environment())['runtime'].username == 'xiquan_app'


@pytest.mark.parametrize('key,value', [
    ('RUN_MIGRATIONS', '1'), ('SEED_DEFAULTS', 'true'), ('AUTO_CREATE_DB', '1'),
    ('API_WORKERS', '2'), ('WEB_CONCURRENCY', '2'), ('API_REPLICAS', '2'),
    ('RESET_PRIVATE_DIR', 'relative/private'), ('RESET_PRIVATE_DIR', '/app/static'),
    ('RESET_DATABASE_URL', 'postgresql+psycopg://xiquan_reset:test@other/bathhouse'),
    ('RESET_BACKUP_DATABASE_URL', 'postgresql+psycopg://xiquan_app:test@postgres/bathhouse'),
    ('RESET_DATABASE_URL', 'postgresql+psycopg://wrong:test@postgres/bathhouse'),
    ('DATABASE_URL', 'postgresql+psycopg://owner:private-secret@postgres/bathhouse'),
    ('RUNTIME_DATABASE_URL', ''),
])
def test_config_fails_closed_without_echoing_credentials(key, value):
    config = environment()
    config[key] = value
    with pytest.raises(RuntimeError) as failure:
        checks().validate_environment(config)
    assert 'private-secret' not in str(failure.value)
    assert 'test@' not in str(failure.value)


def status(**changed):
    values = dict(identity='xiquan_app', privileged=False, member=False,
                  owner=False, forbidden=False, missing_read=False, schema_create=False, server_major=17)
    values.update(changed)
    return values


@pytest.mark.parametrize('field,value', [
    ('privileged', True), ('member', True), ('owner', True), ('forbidden', True),
    ('missing_read', True), ('server_major', 16), ('identity', 'schema_owner'),
])
def test_role_check_rejects_unsafe_identity_or_grants(field, value):
    with pytest.raises(RuntimeError):
        checks().validate_role_status(status(**{field: value}), 'xiquan_app')


def test_role_check_accepts_dedicated_nonowner():
    checks().validate_role_status(status(), 'xiquan_app')


def test_role_check_rejects_schema_create_even_for_nonowner():
    with pytest.raises(RuntimeError, match='role/grants'):
        checks().validate_role_status(status(schema_create=True), 'xiquan_app')


def test_probe_uses_independent_readonly_connection_and_disposes():
    # Only the external PG connection is doubled: protocol/decision code is real.
    module = checks()
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value.one.return_value = status()
    factory = Mock(return_value=engine)
    module.check_database_roles({'runtime': module.make_url(environment()['DATABASE_URL'])}, factory)
    assert factory.call_args.kwargs['connect_args']['options'] == '-c default_transaction_read_only=on'
    assert connection.execute.call_count == 1
    query = str(connection.execute.call_args.args[0])
    assert query.lstrip().upper().startswith('SELECT')
    assert not any(word in query.upper().split() for word in ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'))
    engine.dispose.assert_called_once()


def test_database_failure_is_sanitized_and_disposes():
    module = checks()
    engine = MagicMock()
    engine.connect.side_effect = RuntimeError('postgresql://user:private-secret@host/db')
    with pytest.raises(RuntimeError) as failure:
        module.check_database_roles(
            {'runtime': module.make_url(environment()['DATABASE_URL'])}, Mock(return_value=engine)
        )
    assert 'private-secret' not in str(failure.value)
    engine.dispose.assert_called_once()
