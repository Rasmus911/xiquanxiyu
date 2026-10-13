"""Adopt reviewed 0.5.0 compatibility/checkpoint fixes before production migration.

The original backup and baseline stay intact. No API start, production DDL,
maintenance release, installer publication or data clearing occurs here.
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

BASE_COMMIT = '7ee0b77af83b7dc47b12fba1b21f13248fdf9390'
BASE_SHA256 = '5a1baa5ab2b63c897c3932da5e0a6c4c92b77e761fdc356dcc98f0e5f4a3181a'
FIXED_FILES = ('deploy/cloud/scripts/desktop_050_guard.py', 'server/app/database_guards.py',
               'deploy/cloud/scripts/desktop_050_deploy.py')
ADDED_FILES = {'deploy/cloud/scripts/desktop_050_probe_recovery.py',
               'server/tests/test_desktop050_probe_lengths.py',
               'server/tests/test_receipt_postgresql_json050.py',
               'scripts/tests/test_desktop_050_probe_recovery.py'}
PROOF_KEYS = ('pg17', 'isolated', 'one_use', 'expiry_after_lock', 'immutable',
              'runtime_grants', 'identity_immutable', 'receipt_immutable',
              'receipt_cleanup', 'retained_rows')


def expected_fixed_source(relative, original):
    text = original.decode('utf-8').replace('\r\n', '\n')
    if relative == FIXED_FILES[0]:
        old = "band=Wristband(number='proof-'+uuid.uuid4().hex,bath_area='male')"
        if text.count(old) != 1:
            raise ValueError('Exact original receipt probe required')
        return text.replace(old, "band=Wristband(number='proof-'+uuid.uuid4().hex[:24],bath_area='male')", 1).encode()
    if relative == FIXED_FILES[2]:
        helper = '''def replace_context(path,value,expected_sha256):
    """Context is mutable; each prior exact version stays as private evidence."""
    path=no_links(path)
    require(digest_file(path)==expected_sha256,'Context changed outside this owned checkpoint')
    if json_read(path)==value: return expected_sha256
    previous=path.with_name('context-retained-'+uuid.uuid4().hex+'.json')
    with previous.open('xb') as writer:
        writer.write(path.read_bytes());writer.flush();os.fsync(writer.fileno())
    previous.chmod(0o600)
    temporary=path.with_name('context-next-'+uuid.uuid4().hex+'.json')
    json_write(temporary,value)
    require(digest_file(path)==expected_sha256,'Context changed before atomic replacement')
    os.replace(temporary,path)
    return digest_file(path)


'''
        changes = [
            ('def resource_budget(', helper + 'def resource_budget('),
            ("        self.context=json_read(self.job/'context.json') if job else {}\n",
             "        self.context=json_read(self.job/'context.json') if job else {}\n        self.context_file_sha256=digest_file(self.job/'context.json') if job else None\n"),
            ("        json_write(self.job/'context.json',self.context)\n",
             "        self.store_context()\n\n    def store_context(self):\n        self.context_file_sha256=replace_context(self.job/'context.json',self.context,self.context_file_sha256)\n"),
            ("        self.build(info[0]['Image']);json_write(self.job/'context.json',self.context)\n",
             "        self.build(info[0]['Image']);json_write(self.job/'context.json',self.context)\n        self.context_file_sha256=digest_file(self.job/'context.json')\n"),
        ]
        for old, new in changes:
            if text.count(old) != 1:
                raise ValueError('Exact original checkpoint update required')
            text = text.replace(old, new, 1)
        return text.encode()
    if relative != FIXED_FILES[1]:
        raise ValueError('Unapproved executable source change')
    prefix, separator, suffix = text.partition('def install_receipt_guards(connection):')
    if not separator:
        raise ValueError('Exact original receipt guard required')
    changes = [
        ('    from sqlalchemy import inspect\n', '    from sqlalchemy import JSON, inspect\n'),
        ("        columns = {column['name'] for column in inspect(connection).get_columns(name)}\n",
         "        column_types = {column['name']: column['type'] for column in inspect(connection).get_columns(name)}\n        columns = set(column_types)\n"),
        ("            changes = ' OR '.join(f'OLD.{column} IS DISTINCT FROM NEW.{column}' for column in immutable)\n",
         "            changes = ' OR '.join(\n                f'OLD.{column}::jsonb IS DISTINCT FROM NEW.{column}::jsonb'\n                if isinstance(column_types[column], JSON)\n                else f'OLD.{column} IS DISTINCT FROM NEW.{column}' for column in immutable)\n"),
    ]
    for old, new in changes:
        if old not in suffix:
            raise ValueError('Original JSON guard differs')
        suffix = suffix.replace(old, new, 1)
    return (prefix + separator + suffix).encode()


def validate_source_delta(old_source, new_source, old_manifest, new_manifest):
    old_records = {row['file']: row for row in old_manifest['files']}
    new_records = {row['file']: row for row in new_manifest['files']}
    if not set(old_records) <= set(new_records) or set(new_records) - set(old_records) != ADDED_FILES:
        raise ValueError('Unexpected SOURCE removal/addition')
    changed = {name for name in old_records if old_records[name]['sha256'] != new_records[name]['sha256']}
    if changed != set(FIXED_FILES) | {'scripts/lib/source-security.cjs'}:
        raise ValueError('Unexpected existing SOURCE change; desktop/mobile bytes must remain identical')
    for name in FIXED_FILES:
        if (new_source / name).read_bytes().replace(b'\r\n', b'\n') != expected_fixed_source(name, (old_source / name).read_bytes()):
            raise ValueError('Fix differs from the approved compatibility/checkpoint changes')
    original = (old_source / 'scripts/lib/source-security.cjs').read_bytes().replace(b'\r\n', b'\n')
    addition = b"  'deploy/cloud/scripts/desktop_050_probe_recovery.py',\n  'scripts/tests/test_desktop_050_probe_recovery.py',\n"
    expected = original.replace(b'const FILES = new Set([\n', b'const FILES = new Set([\n' + addition, 1)
    if (new_source / 'scripts/lib/source-security.cjs').read_bytes().replace(b'\r\n', b'\n') != expected:
        raise ValueError('Source allowlist changed beyond the recovery tool/test')


def main():
    parser = argparse.ArgumentParser()
    for name in ('stage', 'job', 'bundle', 'sha256', 'commit'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    if os.name != 'posix' or os.getuid() != 0:
        raise ValueError('Human-run ECS root only')
    if not re.fullmatch('/opt/xiquan-releases/desktop050-stage-[0-9a-f]{32}', args.stage) or not re.fullmatch('/opt/xiquan-backups/desktop050-cutover-[0-9a-f]{32}', args.job):
        raise ValueError('Exact 0.5.0 checkpoint required')
    os.umask(0o077)
    sys.path.insert(0, str(Path(args.stage) / 'xiquan/deploy/cloud/scripts'))
    from desktop_050_deploy import Desktop050, OLD, TOOLS, require
    from operations_deploy import CLOUD, json_read, json_write
    from operations_preflight import command_json, digest_file, no_links, query_cloud_state, stage_bundle
    import fcntl

    driver = None
    with no_links('/run/lock/xiquan-stock-cutover.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            job = no_links(args.job)
            original_stage = no_links(args.stage)
            original_source = original_stage / 'xiquan'
            original_report = json_read(original_stage / 'desktop-stage.json')
            require(original_report['source_commit'] == BASE_COMMIT and
                    original_report['bundle_sha256'] == BASE_SHA256, 'Exact original failed SOURCE required')
            require(not any((job / name).exists() for name in
                            ('after.json', 'ready.json', 'completed.json', 'maintenance-released.json')),
                    'Production migration already attempted; this repair is pre-migration-only')
            adoption_path = job / 'probe-source-adoption.json'
            if adoption_path.exists():
                prior = json_read(adoption_path)
                if prior['source_commit'] != args.commit or prior['source_sha256'] != args.sha256:
                    context = json_read(job / 'context.json')
                    require(not (job / 'probe-corrected-image.json').exists() and
                            context['source_commit'] == BASE_COMMIT and context['stage'] == args.stage,
                            'An adopted image requires its exact corrected SOURCE; no replacement allowed')
                    adoption_path.rename(job / ('probe-source-adoption-retained-' + uuid.uuid4().hex + '.json'))
            if not adoption_path.exists():
                original = Desktop050(args.stage, args.job)
                require(original.context['stage'] == args.stage and original.context['source_commit'] == BASE_COMMIT,
                        'Original checkpoint identity changed')
                original.protected()
                original.verify_pinned_image()
                require(original.guard('inspect') == json_read(job / 'before.json'), 'Original production baseline changed')
                identity = stage_bundle(args.bundle, args.sha256)
                require(identity['source_commit'] == args.commit, 'Corrected SOURCE identity differs')
                stage = no_links('/opt/xiquan-releases') / ('desktop050-stage-' + uuid.uuid4().hex)
                identity = stage_bundle(args.bundle, args.sha256, stage)
                new_source = stage / 'xiquan'
                validate_source_delta(original_source, new_source,
                    json_read(original_source / 'source-manifest.json'), json_read(new_source / 'source-manifest.json'))
                require(digest_file(new_source / 'deploy/cloud/scripts/desktop_050_probe_recovery.py') ==
                        digest_file(Path(__file__)), 'Uploaded recovery tool differs from corrected SOURCE')
                json_write(stage / 'desktop-stage.json', dict(**identity, state=original_report['state'],
                                                             protected=original_report['protected']))
                retained = job / ('before-probe-fix-' + uuid.uuid4().hex)
                retained.mkdir(mode=0o700)
                for name in ('context.json', 'image.json', 'Dockerfile', 'build.log'):
                    file = no_links(job / name)
                    if file.exists():
                        shutil.copy2(file, retained / name)
                json_write(adoption_path, dict(original_stage=args.stage, original_commit=BASE_COMMIT,
                    original_source_sha256=BASE_SHA256, original_context=str(retained / 'context.json'),
                    stage=str(stage), source_commit=args.commit, source_sha256=args.sha256,
                    changed_files=list(FIXED_FILES), production_migrated=False))
            adoption = json_read(adoption_path)
            require(adoption['original_stage'] == args.stage and adoption['source_commit'] == args.commit and
                    adoption['source_sha256'] == args.sha256, 'Resume requires the same exact corrected SOURCE')
            stage = no_links(adoption['stage'])
            source = stage / 'xiquan'
            spec = importlib.util.spec_from_file_location('corrected_desktop050_deploy', source / 'deploy/cloud/scripts/desktop_050_deploy.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            driver = module.Desktop050(str(stage), args.job)
            state = query_cloud_state()
            owner_sql = "BEGIN READ ONLY; SELECT json_build_object('maintenance',maintenance,'owner',maintenance_reset_id) FROM business_state WHERE id=1; ROLLBACK;"
            ownership = command_json(['docker', 'exec', 'xiquan-postgres-1', 'sh', '-eu', '-c',
                'exec psql -X -q -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"', 'sh', owner_sql])
            require(state['schema_revision'] == OLD and not state['pending_resets'] and ownership['maintenance'] and
                    ownership['owner'] == driver.context['owner'], 'Exact owned pre-migration state required')
            require(digest_file(CLOUD / '.env') == driver.context['env_sha256'], 'Private configuration changed')
            driver.protected()
            require(driver.guard('inspect') == json_read(job / 'before.json'), 'Production baseline changed')
            image_receipt = job / 'probe-corrected-image.json'
            if not image_receipt.exists():
                old_context = json_read(Path(adoption['original_context']))
                # stream_build deliberately refuses an existing evidence file.
                # Retain that exact old/partial log instead of deleting/overwriting it.
                prior_log = job / 'build.log'
                if prior_log.exists():
                    no_links(prior_log).rename(job / ('build-before-probe-fix-' + uuid.uuid4().hex + '.log'))
                prior_image = job / 'image.json'
                if prior_image.exists():
                    no_links(prior_image).rename(job / ('image-before-probe-fix-' + uuid.uuid4().hex + '.json'))
                driver.context.update(stage=str(stage), source_commit=args.commit,
                    tools={name: digest_file(source / 'deploy/cloud/scripts' / name) for name in TOOLS})
                driver.build(old_context['image_id'])
                driver.verify_pinned_image()
                driver.store_context()
                json_write(image_receipt, dict(source_commit=args.commit, source_sha256=args.sha256,
                                               image_id=driver.context['image_id']))
            else:
                receipt = json_read(image_receipt)
                require(driver.context['stage'] == str(stage) and driver.context['source_commit'] == args.commit and
                        receipt['image_id'] == driver.context['image_id'] and receipt['source_commit'] == args.commit,
                        'Corrected image/checkpoint differ')
                driver.verify_pinned_image()
            if not (job / 'clone-proof.json').exists():
                before = job / 'before'
                receipt = json_read(before / 'receipt.json')
                require(receipt['restore']['status'] == 'verified' and
                        digest_file(before / 'database.backup') == receipt['dump_sha256'], 'Original verified backup changed')
                for name in ('clone-logins.sql', 'clone.env', 'clone-before.json',
                             'clone-preserved-before-fixtures.json', 'clone-enable-logins.sql'):
                    file = job / name
                    if file.exists():
                        no_links(file).rename(job / (name + '.retained-' + uuid.uuid4().hex))
                clone = driver.restore(before / 'database.backup')
                driver.rehearsal(clone)
            proof = json_read(job / 'clone-proof.json')
            require(all(proof.get(key) is True for key in PROOF_KEYS), 'Incomplete real PostgreSQL proof')
            require(driver.guard('inspect') == json_read(job / 'before.json'), 'Production changed during proof')
            json_write(job / 'probe-fix-verified.json', dict(source_commit=args.commit, source_sha256=args.sha256,
                image_id=driver.context['image_id'], proof_sha256=digest_file(job / 'clone-proof.json'),
                production_schema_unchanged=True, api_started=False))
            print('DESKTOP050_CORRECTED_SOURCE_AND_PG17_VERIFIED; production remains paused', flush=True)
            print(json.dumps(dict(stage=str(stage), job=args.job, source_commit=args.commit, source_sha256=args.sha256)))
        finally:
            if driver:
                for restore in driver.restores:
                    try:
                        restore.stop()
                    except Exception:
                        pass


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) or type(error).__name__ in ('DeploymentError', 'PreflightError') else type(error).__name__
        print('DESKTOP050_PROBE_RECOVERY_STOPPED: ' + message, file=sys.stderr)
        raise SystemExit(1)
