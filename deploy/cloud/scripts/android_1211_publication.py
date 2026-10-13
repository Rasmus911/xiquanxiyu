"""Human-run Android publication; preserve all desktop/web feeds and old APKs."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import uuid
import zipfile


def merge_policy(previous, config):
    if previous.get('schemaVersion') != 1 or not all(key in previous for key in ('desktop','web','android')):
        raise ValueError('Existing release policy is incomplete; no guessed replacement')
    version = config.get('version')
    code = {'1.2.11': 18}.get(version)
    if (code is None or config.get('versionCode') != code
        or config.get('minimumVersionCode') != 9
        or config.get('androidApkUrl') != '/mobile/downloads/xiquan-mobile-ordering-' + version + '.apk'
        or not re.fullmatch('[0-9a-f]{64}', str(config.get('sha256','')))):
        raise ValueError('Exact reviewed Android version/code identity required')
    old=previous['android']
    if int(old.get('latestVersionCode',0)) > code:
        raise ValueError('A newer Android version is already live; do not downgrade')
    if int(old.get('latestVersionCode',0)) == code and (old.get('sha256') != config['sha256'] or old.get('latestVersion') != version):
        raise ValueError('VersionCode already has different immutable APK bytes')
    minimum=9
    if int(old.get('minimumVersionCode',1)) > minimum:
        raise ValueError('Existing minimum exceeds approved code 9; no policy relaxation')
    if not 1 <= minimum <= code:
        raise ValueError('Invalid minimum installed version code')
    result=copy.deepcopy(previous)
    result['android']={'latestVersion':version,'latestVersionCode':code,'minimumVersionCode':minimum,
        'required':False,'downloadUrl':'https://api.pqxqxy.xyz'+config['androidApkUrl'],
        'sha256':config['sha256'],'releaseNotes':str(config.get('releaseNotes','')).splitlines(),
        'publishedAt':datetime.now(timezone.utc).isoformat()}
    return result


def no_links(path):
    path=Path(path)
    if not path.is_absolute() or any(parent.is_symlink() for parent in (path,*path.parents)):
        raise ValueError('Unexpected linked or relative publication path')
    return path


def file_hash(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path, document):
    temporary=no_links(path.parent / (path.name+'.new-'+uuid.uuid4().hex))
    with temporary.open('x',encoding='utf-8') as stream:
        json.dump(document,stream,ensure_ascii=False,indent=2)
        stream.flush(); os.fsync(stream.fileno())
    temporary.chmod(0o644)
    os.replace(temporary,path)


def extract_web_archive(archive, destination):
    destination = no_links(destination)
    roots = {'index.html', 'icon.svg', 'download-qr.svg', 'manifest.webmanifest', 'sw.js'}
    with zipfile.ZipFile(no_links(archive)) as zipped:
        entries = zipped.infolist()
        if len(entries) > 500 or sum(entry.file_size for entry in entries) > 10 * 1024 * 1024:
            raise ValueError('Mobile web archive exceeds safe limits')
        names = set()
        for entry in entries:
            # PowerShell 5.1 archive implementations may use Windows separators.
            name = entry.filename.replace('\\', '/')
            if name in names or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError('Duplicate or linked web archive member')
            names.add(name)
            if name.endswith('/'):
                if name != 'assets/': raise ValueError('Unexpected web archive directory')
            elif name not in roots and not re.fullmatch(r'assets/[A-Za-z0-9_-]+\.(?:js|css|svg|png|jpg|woff2?)', name):
                raise ValueError('Unexpected web archive member')
        if 'index.html' not in names: raise ValueError('Web archive entry point missing')
        destination.mkdir(mode=0o700)
        for entry in entries:
            name = entry.filename.replace('\\', '/')
            path = no_links(destination / name)
            if name.endswith('/'): path.mkdir(mode=0o700, exist_ok=True)
            else:
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with path.open('xb') as stream: stream.write(zipped.read(entry))
    return destination


def publish_mobile_web(incoming, live, backup):
    incoming, live, backup = map(no_links, (incoming, live, backup))
    roots = {'index.html', 'icon.svg', 'download-qr.svg', 'manifest.webmanifest', 'sw.js', 'download-config.json'}
    files = []
    size = 0
    for path in incoming.rglob('*'):
        no_links(path)
        relative = path.relative_to(incoming)
        if path.is_dir():
            if relative.as_posix() != 'assets': raise ValueError('Unexpected mobile web directory')
            continue
        name = relative.as_posix()
        if not path.is_file() or (name not in roots and not re.fullmatch(r'assets/[A-Za-z0-9_-]+\.(?:js|css|svg|png|jpg|woff2?)', name)):
            raise ValueError('Unexpected mobile web file; nothing published')
        size += path.stat().st_size
        no_links(live / relative)
        if name != 'download-config.json': files.append((relative, path))
    if size > 10 * 1024 * 1024 or not (incoming / 'index.html').is_file():
        raise ValueError('Mobile web tree too large or missing entry point')
    html = (incoming / 'index.html').read_text(encoding='utf-8')
    assets = re.findall(r'\./(assets/[A-Za-z0-9_-]+\.(?:js|css))', html)
    if not assets or any(not (incoming / name).is_file() for name in assets):
        raise ValueError('Mobile web entry assets missing')
    # Validate immutable hashed assets before changing any live files.
    for relative, path in files:
        final = live / relative
        if relative.parts[0] == 'assets' and final.exists() and file_hash(final) != file_hash(path):
            raise ValueError('Existing mobile asset differs; no overwrite')
    # Keep old hashed resources/APKs; replace the entry page last.
    for relative, path in sorted(files, key=lambda item: item[0].as_posix() == 'index.html'):
        final = live / relative
        final.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        if final.exists():
            saved = backup / 'web' / relative
            saved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copy2(final, saved)
        staged = no_links(final.with_name(final.name + '.new-' + uuid.uuid4().hex))
        shutil.copyfile(path, staged); staged.chmod(0o644); os.replace(staged, final)


def publish(config_file, incoming_apk, incoming_web=None, web_archive=None):
    cloud=no_links('/opt/xiquan/xiquan/deploy/cloud')
    config=json.loads(no_links(config_file).read_text(encoding='utf-8-sig'))
    policy_file=no_links(cloud/'releases/client-policy.json')
    old_policy=json.loads(policy_file.read_text(encoding='utf-8'))
    merged=merge_policy(old_policy,config)
    incoming=no_links(incoming_apk)
    digest=file_hash(incoming)
    if digest != config['sha256'] or incoming.stat().st_size < 1000000:
        raise ValueError('Uploaded APK bytes do not match verified local package')
    downloads=no_links(cloud/'mobile/downloads'); downloads.mkdir(mode=0o755,exist_ok=True)
    final=no_links(downloads/Path(config['androidApkUrl']).name)
    if final.exists():
        if file_hash(final) != digest:
            raise ValueError('Existing immutable APK differs; no replacement')
    publication_id = 'android' + config['version'].replace('.', '')
    backup=no_links('/opt/xiquan-backups')/(publication_id+'-publication-'+uuid.uuid4().hex)
    backup.mkdir(mode=0o700)
    if web_archive is not None:
        incoming_web = extract_web_archive(web_archive, backup / 'incoming-web')
    shutil.copy2(policy_file,backup/'client-policy.json')
    download_config=no_links(cloud/'mobile/download-config.json')
    if download_config.exists(): shutil.copy2(download_config,backup/'download-config.json')
    if not final.exists():
        staged=no_links(downloads/('.'+publication_id+'-'+uuid.uuid4().hex))
        shutil.copyfile(incoming,staged); staged.chmod(0o644); os.replace(staged,final)
    # APK must be reachable before either old-app discovery document points to it.
    from urllib.request import Request,urlopen
    with urlopen(Request('https://api.pqxqxy.xyz'+config['androidApkUrl'],method='HEAD'),timeout=30) as response:
        if response.status != 200 or int(response.headers.get('Content-Length','0')) != final.stat().st_size:
            raise ValueError('Public APK route not ready; feeds were not changed')
    if incoming_web is not None:
        publish_mobile_web(incoming_web, no_links(cloud / 'mobile'), backup)
    atomic_json(download_config,config)
    atomic_json(policy_file,merged)
    print(publication_id.upper()+'_IN_APP_UPDATE_PUBLISHED; original desktop/web policies and old APKs retained')
    print('PUBLICATION_BACKUP='+str(backup))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--config',required=True); parser.add_argument('--apk',required=True)
    web = parser.add_mutually_exclusive_group()
    web.add_argument('--web'); web.add_argument('--web-zip')
    args=parser.parse_args()
    if os.name != 'posix' or os.getuid() != 0: raise SystemExit('Human-run ECS root only')
    import fcntl
    os.umask(0o077)
    with no_links('/run/lock/xiquan-release-publication.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        publish(args.config,args.apk,args.web,args.web_zip)
