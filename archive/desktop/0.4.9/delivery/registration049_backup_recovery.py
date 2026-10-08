"""Human-run recovery of one migrated checkpoint; no DDL replay or business clearing."""
import argparse
import inspect
import json
import os
import stat
import sys
import uuid
from pathlib import Path

JOB = '/opt/xiquan-backups/desktop049-cutover-0612e87608b44f9991c797c0a1a76845'
STAGE = '/opt/xiquan-releases/desktop049-stage-d4655ecc673c4b9c89889d76c5c9b3db'
COMMIT = '4f11626373298754d2e0ceacd82ae7ff5dd71204'
IMAGE = 'sha256:3cba00f7ab39ace454a9961ef4f34b221a9632e91a3cabf6ce3d7ad2b800c3d2'


def grant_sql(schema, name, role='xiquan_backup'):
    if (schema != 'public' or name != 'registration_token_state_id_seq'
            or role not in ('xiquan_app', 'xiquan_reset', 'xiquan_backup')):
        raise ValueError('Not the exact new registration sequence; no grant performed')
    return 'GRANT SELECT ON SEQUENCE "public"."registration_token_state_id_seq" TO "' + role + '"'


def missing_sequence_roles(row):
    grants = row.get('role_privileges', {})
    if (row.get('schema') != 'public' or row.get('name') != 'registration_token_state_id_seq'
            or row.get('owner_matches') is not True
            or set(grants) != {'xiquan_app', 'xiquan_reset', 'xiquan_backup'}
            or any(set(value) != {'readable', 'usage', 'writable'} or
                   any(type(value[key]) is not bool for key in value) for value in grants.values())
            or any(value['writable'] for value in grants.values())
            or grants['xiquan_backup']['usage'] or grants['xiquan_backup']['readable']):
        raise ValueError('Exact missing backup read/owned sequence with no unexpected write authority required')
    return [role for role in ('xiquan_app', 'xiquan_reset', 'xiquan_backup') if not grants[role]['readable']]


def pregrant_role_query(query):
    # Preserve every original identity/authority/other-object read check. Only
    # this owned new sequence is separately inspected before the missing grant.
    marker = "AND NOT CASE WHEN c.relkind = 'S'"
    if query.count(marker) != 1:
        raise ValueError('Original role checker shape differs; no recovery exception applied')
    return query.replace(marker, "AND c.oid <> to_regclass('public.registration_token_state_id_seq') " + marker)


def pregrant_engine_factory(factory):
    from contextlib import contextmanager
    from sqlalchemy import text
    class ScopedEngine:
        def __init__(self, engine):
            self.engine = engine
        @contextmanager
        def connect(self):
            with self.engine.connect() as connection:
                class ScopedConnection:
                    def execute(self, statement, *args, **kwargs):
                        return connection.execute(text(pregrant_role_query(str(statement))), *args, **kwargs)
                yield ScopedConnection()
        def dispose(self):
            self.engine.dispose()
    def scoped_factory(*args, **kwargs):
        return ScopedEngine(factory(*args, **kwargs))
    return scoped_factory


def quarantine_empty_after(job):
    job = Path(job)
    after = job / 'after'
    dump = after / 'database.backup'
    if (after.is_symlink() or not after.is_dir() or {p.name for p in after.iterdir()} != {'database.backup'}
            or dump.is_symlink() or not dump.is_file() or dump.stat().st_size != 0):
        raise ValueError('Only the exact zero-byte attempt can be quarantined; retain partial evidence')
    destination = job / ('after-failed-empty-' + uuid.uuid4().hex)
    if destination.exists():
        raise ValueError('Quarantine destination already exists')
    after.rename(destination)
    return destination


def update_context(path, value, reviewed_compose_hash):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected original private context file')
    original = path.read_bytes()
    current = json.loads(original)
    if (set(value) != set(current) or value.get('compose_sha256') != reviewed_compose_hash
            or any(value[k] != current[k] for k in current if k != 'compose_sha256')):
        raise ValueError('Only the reviewed Compose hash can change; identity is protected')
    if current == value:
        return
    backup = path.with_name('context-before-compose-' + uuid.uuid4().hex + '.json')
    with backup.open('xb') as writer:
        writer.write(original)
        writer.flush()
        os.fsync(writer.fileno())
    backup.chmod(0o600)
    temporary = path.with_name('context-reviewed-' + uuid.uuid4().hex + '.json')
    with temporary.open('x', encoding='utf-8') as writer:
        json.dump(value, writer, ensure_ascii=False, indent=2)
        writer.flush()
        os.fsync(writer.fileno())
    temporary.chmod(0o600)
    if path.read_bytes() != original:
        raise ValueError('Context changed concurrently; replacement stopped')
    os.replace(temporary, path)


DB_CODE = r'''
import json
import sys
import os
from pathlib import Path
sys.path.insert(0, '/')
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from app import create_app
from app.operations_upgrade import maintenance_connection
from app.business_barrier import exclusive_barrier
from app.deployment_checks import check_database_roles
from stock_guard import roles, state, revision, require
from desktop_guard import snapshot

mode, job, baseline = sys.argv[1:]
app = create_app()
with app.app_context(), maintenance_connection() as c:
    with exclusive_barrier(c, job):
        current = state(c)
        require(revision(c) == '20261008_registration_token' and current['maintenance']
                and current['maintenance_reset_id'] == job, 'Exact migrated owned maintenance required')
        require(c.exec_driver_sql("SELECT count(*) FROM reset_tasks WHERE status IN ('queued','running')").scalar_one() == 0,
                'Pending reset blocks repair')
        row = c.exec_driver_sql("""SELECT n.nspname AS schema, s.relname AS name,
            s.relowner=(SELECT oid FROM pg_roles WHERE rolname=session_user) AS owner_matches
            FROM pg_class s JOIN pg_namespace n ON n.oid=s.relnamespace
            WHERE s.oid=pg_get_serial_sequence('public.registration_token_state','id')::regclass
              AND s.relkind='S'""").mappings().one()
        row = dict(row)
        row['role_privileges'] = {}
        for role in ('xiquan_app', 'xiquan_reset', 'xiquan_backup'):
            row['role_privileges'][role] = dict(c.execute(text("""SELECT
                has_sequence_privilege(:role,'public.registration_token_state_id_seq','SELECT') AS readable,
                has_sequence_privilege(:role,'public.registration_token_state_id_seq','USAGE') AS usage,
                has_sequence_privilege(:role,'public.registration_token_state_id_seq','UPDATE') AS writable"""),
                {'role':role}).mappings().one())
        missing = missing_sequence_roles(row)
        row['missing_select_roles'] = missing
        urls = {kind:make_url(os.environ[name]) for kind,name in (
            ('runtime','RUNTIME_DATABASE_URL'), ('reset','RESET_DATABASE_URL'), ('backup','RESET_BACKUP_DATABASE_URL'))}
        require({kind:url.username for kind,url in urls.items()} ==
                {'runtime':'xiquan_app','reset':'xiquan_reset','backup':'xiquan_backup'}, 'Dedicated role identities differ')
        check_database_roles(urls, engine_factory=pregrant_engine_factory(create_engine))
        expected = json.loads(Path(baseline).read_text())
        require(snapshot(c) == expected, 'Retained business snapshot changed before grant')
        if mode == 'apply':
            for role in missing:
                c.exec_driver_sql(grant_sql(row['schema'], row['name'], role))
            c.commit()
            # Independent physical role connections must see committed grants.
            # Session advisory ownership remains held across this commit.
            roles()
            require(snapshot(c) == expected, 'Retained rows/grants/credentials changed after sequence-only repair')
            row['readable_after'] = True
        else:
            c.rollback()
        print(json.dumps(dict(sequence=row, snapshot=expected)))
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    driver = None
    try:
        if os.name != 'posix' or os.getuid() != 0:
            raise ValueError('This entry is human-run on ECS root only')
        os.umask(0o077)
        sys.path.insert(0, STAGE + '/xiquan/deploy/cloud/scripts')
        import fcntl
        import desktop_049_deploy as deploy
        from operations_preflight import no_links, digest_file
        from operations_deploy import json_read, json_write, MOUNT
        from stock_deploy import check_resources, require
        with no_links('/run/lock/xiquan-stock-cutover.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            driver = deploy.Desktop049(STAGE, JOB)
            require(driver.context['source_commit'] == COMMIT and driver.context['image_id'] == IMAGE
                    and driver.context['stage'] == STAGE
                    and driver.context['tools'] == {n: digest_file(Path(deploy.__file__).parent / n) for n in deploy.TOOLS},
                    'Original checkpoint image/source/tool identity differs')
            require(all((driver.job / n).exists() for n in ('before.json', 'after.json', 'clone-proof.json'))
                    and not any((driver.job / n).exists() for n in ('ready.json', 'maintenance-released.json', 'completed.json')),
                    'Not the exact pre-after-backup checkpoint; do not retry this repair')
            proof = json_read(driver.job / 'clone-proof.json')
            require(all(proof.get(k) is True for k in ('pg17','isolated','one_use','expiry_after_lock','immutable','runtime_grants')),
                    'Original PG17 security rehearsal proof is incomplete')
            after = no_links(driver.job / 'after')
            require(after.is_dir() and stat.S_IMODE(after.stat().st_mode) == 0o700 and after.stat().st_uid == 0,
                    'Expected root-owned private zero-byte backup folder')
            names = {p.name for p in after.iterdir()}
            require(names == {'database.backup'} and no_links(after / 'database.backup').is_file()
                    and (after / 'database.backup').stat().st_size == 0,
                    'Backup is not exactly the empty failed attempt; no evidence moved')
            driver.protected()
            driver.verify_pinned_image()
            code = '\n'.join(inspect.getsource(function) for function in (
                grant_sql, missing_sequence_roles, pregrant_role_query, pregrant_engine_factory)) + '\n' + DB_CODE
            result = json.loads(driver.command(['-c', code, 'inspect', driver.context['owner'], MOUNT + '/after.json']))
            require(result['snapshot'] == json_read(driver.job / 'after.json'), 'Migrated snapshot changed')
            sequence = result['sequence']
            print('SEQUENCE_CHECK=' + json.dumps(sequence), flush=True)
            missing_sequence_roles(sequence)
            print('MISSING_BACKUP_SEQUENCE_SELECT_CONFIRMED', flush=True)
            if not args.apply:
                print('READ_ONLY_CHECK_FINISHED; no grant, move, resume or service start')
                return 0
            check_resources('registration049-backup-recovery', include_restore=True)
            driver.phase('grant-select-on-only-new-registration-sequence')
            repaired_result = json.loads(driver.command(['-c', code, 'apply', driver.context['owner'], MOUNT + '/after.json']))
            repaired = repaired_result['sequence']
            require(repaired.get('readable_after') is True, 'Repair verification missing')
            json_write(driver.job / ('sequence-select-repair-' + uuid.uuid4().hex + '.json'),
                       dict(source_commit=COMMIT, image_id=IMAGE, owner=driver.context['owner'], sequence=repaired))
            require(driver.guard('inspect') == json_read(driver.job / 'after.json'), 'Retained business snapshot changed')
            archived = quarantine_empty_after(driver.job)
            print('EMPTY_FAILED_ATTEMPT_RETAINED=' + str(archived), flush=True)
            # Original writer is intentionally create-only. Context is the sole
            # mutable metadata file: preserve it, update only reviewed Compose hash.
            original_write = deploy.json_write
            compose_record = next(r for r in driver.manifest['files'] if r['file'] == 'deploy/cloud/docker-compose.prod.yml')
            def checkpoint_write(path, value):
                if Path(path) == driver.job / 'context.json':
                    update_context(path, value, compose_record['sha256'])
                else:
                    original_write(path, value)
            deploy.json_write = checkpoint_write
            print('RESUME_ORIGINAL_CHECKPOINT; no rebuild, migration replay or business clearing', flush=True)
            driver.resume()
            print('REGISTRATION049_BACKUP_RECOVERY_AND_CLOUD_DEPLOYMENT_COMPLETED')
            return 0
    except Exception as error:
        safe = str(error) if isinstance(error, ValueError) else type(error).__name__ + ': inspect private checkpoint'
        print('BACKUP_RECOVERY_STOPPED: ' + safe, file=sys.stderr)
        print('PRIVATE_DESKTOP_JOB=' + JOB, file=sys.stderr)
        print('Do not rerun deploy, delete evidence, clear maintenance or start an old API.', file=sys.stderr)
        return 1
    finally:
        if driver:
            for restore in driver.restores:
                try:
                    restore.stop()
                except Exception:
                    pass


if __name__ == '__main__':
    raise SystemExit(main())
