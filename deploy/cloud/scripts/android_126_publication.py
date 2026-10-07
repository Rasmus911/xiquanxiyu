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
import uuid


def merge_policy(previous, config):
    if previous.get('schemaVersion') != 1 or not all(key in previous for key in ('desktop','web','android')):
        raise ValueError('Existing release policy is incomplete; no guessed replacement')
    if (config.get('version') != '1.2.6' or config.get('versionCode') != 13
        or config.get('minimumVersionCode') != 9
        or config.get('androidApkUrl') != '/mobile/downloads/xiquan-mobile-ordering-1.2.6.apk'
        or not re.fullmatch('[0-9a-f]{64}', str(config.get('sha256','')))):
        raise ValueError('Exact signed Android 1.2.6/code13 identity required')
    old=previous['android']
    if int(old.get('latestVersionCode',0)) > 13:
        raise ValueError('A newer Android version is already live; do not downgrade')
    if int(old.get('latestVersionCode',0)) == 13 and (old.get('sha256') != config['sha256'] or old.get('latestVersion') != '1.2.6'):
        raise ValueError('VersionCode 13 already has different immutable APK bytes')
    minimum=max(int(old.get('minimumVersionCode',1)),int(config.get('minimumVersionCode',1)))
    if not 1 <= minimum <= 13:
        raise ValueError('Invalid minimum installed version code')
    result=copy.deepcopy(previous)
    result['android']={'latestVersion':'1.2.6','latestVersionCode':13,'minimumVersionCode':minimum,
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


def publish(config_file, incoming_apk):
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
    final=no_links(downloads/'xiquan-mobile-ordering-1.2.6.apk')
    if final.exists():
        if file_hash(final) != digest:
            raise ValueError('Existing immutable APK differs; no replacement')
    backup=no_links('/opt/xiquan-backups')/('android126-publication-'+uuid.uuid4().hex)
    backup.mkdir(mode=0o700)
    shutil.copy2(policy_file,backup/'client-policy.json')
    download_config=no_links(cloud/'mobile/download-config.json')
    if download_config.exists(): shutil.copy2(download_config,backup/'download-config.json')
    if not final.exists():
        staged=no_links(downloads/('.android126-'+uuid.uuid4().hex))
        shutil.copyfile(incoming,staged); staged.chmod(0o644); os.replace(staged,final)
    # APK must be reachable before either old-app discovery document points to it.
    from urllib.request import Request,urlopen
    with urlopen(Request('https://api.pqxqxy.xyz'+config['androidApkUrl'],method='HEAD'),timeout=30) as response:
        if response.status != 200 or int(response.headers.get('Content-Length','0')) != final.stat().st_size:
            raise ValueError('Public APK route not ready; feeds were not changed')
    atomic_json(download_config,config)
    atomic_json(policy_file,merged)
    print('ANDROID126_IN_APP_UPDATE_PUBLISHED; original desktop/web policies and old APKs retained')
    print('PUBLICATION_BACKUP='+str(backup))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--config',required=True); parser.add_argument('--apk',required=True)
    args=parser.parse_args()
    if os.name != 'posix' or os.getuid() != 0: raise SystemExit('Human-run ECS root only')
    import fcntl
    os.umask(0o077)
    with no_links('/run/lock/xiquan-stock-cutover.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        publish(args.config,args.apk)
