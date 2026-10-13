"""Human-run immutable web assets, no API stop or database access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import uuid
from zipfile import ZipFile

def safe(path):
    path=Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('Unsafe linked publication path')
    return path

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def publish(archive_path, expected_hash, source_commit):
    archive=safe(archive_path)
    if not re.fullmatch('[a-f0-9]{40}',source_commit) or digest(archive)!=expected_hash:raise ValueError('Reviewed web identity mismatch')
    cloud=safe('/opt/xiquan/xiquan/deploy/cloud');live=safe(cloud/'web')
    backup=safe('/opt/xiquan-backups')/('static056-'+uuid.uuid4().hex);backup.mkdir(mode=0o700)
    live.mkdir(mode=0o755,exist_ok=True);live.chmod(0o755)
    incoming=backup/'incoming';incoming.mkdir(mode=0o700)
    hashes={}
    with ZipFile(archive) as zipped:
        entries=zipped.infolist()
        if len(entries)>1500 or sum(e.file_size for e in entries)>20*1024*1024:raise ValueError('Web archive oversized')
        names=set()
        for entry in entries:
            name=entry.filename.replace('\\','/')
            if name in names or stat.S_ISLNK(entry.external_attr>>16):raise ValueError('Duplicate or linked archive')
            names.add(name)
            if entry.is_dir():
                if name not in ('assets/',):raise ValueError('Unexpected web directory')
                continue
            if name not in ('index.html','version.json','favicon.ico','icon.svg') and not re.fullmatch(r'assets/[A-Za-z0-9_.-]+\.(?:js|css|svg|png|jpg|woff2?)',name):raise ValueError('Unexpected web file')
            target=safe(incoming/name);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(zipped.read(entry))
            hashes['/app/'+name]=digest(target)
            existing=safe(live/name)
            if name.startswith('assets/') and existing.exists() and digest(existing)!=digest(target):raise ValueError('Immutable asset differs')
    html=(incoming/'index.html').read_text(encoding='utf-8')
    assets=re.findall(r'(?:\./)?(assets/[A-Za-z0-9_.-]+\.(?:js|css))',html)
    if not assets or any(not (incoming/n).is_file() for n in assets):raise ValueError('Web entry assets missing')
    for path in sorted(incoming.rglob('*'),key=lambda p:p.name=='index.html'):
        if not path.is_file():continue
        relative=path.relative_to(incoming);final=safe(live/relative);final.parent.mkdir(parents=True,exist_ok=True,mode=0o755);final.parent.chmod(0o755)
        if final.exists():
            saved=backup/'before'/relative;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(final,saved)
        temp=final.with_name(final.name+'.new-'+uuid.uuid4().hex);shutil.copyfile(path,temp);temp.chmod(0o644);os.replace(temp,final)
    # Preserve desktop/Android policies. Web uses the committed source build ID.
    policy_path=safe(cloud/'releases/client-policy.json');policy=json.loads(policy_path.read_text(encoding='utf-8'))
    if policy.get('schemaVersion')!=1 or not all(k in policy for k in ('web','desktop','android')):raise ValueError('Existing policy incomplete')
    shutil.copy2(policy_path,backup/'client-policy.before.json')
    policy['web']={'buildId':source_commit,'required':False,'releaseNotes':['给桌面端的图标做出更换','优化“库存”页面布局']}
    temporary=policy_path.with_name('client-policy.new-'+uuid.uuid4().hex);temporary.write_text(json.dumps(policy,ensure_ascii=False),encoding='utf-8');temporary.chmod(0o644);os.replace(temporary,policy_path)
    receipt={'version':'0.5.6','source_commit':source_commit,'web_sha256':expected_hash,'hashes':hashes,'database_changed':False}
    (backup/'completed.json').write_text(json.dumps(receipt),encoding='utf-8')
    print('STATIC056_RECEIPT='+str(backup/'completed.json'),flush=True)
    print(json.dumps(receipt),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--archive',required=True);parser.add_argument('--sha256',required=True);parser.add_argument('--commit',required=True);args=parser.parse_args()
    if os.name!='posix' or os.getuid()!=0:raise SystemExit('Human-run ECS root only')
    import fcntl
    os.umask(0o077)
    with safe('/run/lock/xiquan-release-publication.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);publish(args.archive,args.sha256,args.commit)
