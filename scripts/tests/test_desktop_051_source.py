import json
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def test_new_required_modules_are_real_and_in_source_allowlist():
    code="const m=require('./scripts/lib/desktop-051.cjs'),s=require('./scripts/lib/source-security.cjs'),fs=require('node:fs');console.log(JSON.stringify(m.requiredSource.map(f=>({f,exists:fs.existsSync(f),allowed:s.allowed(f)}))))"
    result=subprocess.run(['node','-e',code],cwd=ROOT,capture_output=True,text=True,check=True)
    rows=json.loads(result.stdout)
    assert len(rows)>15 and all(r['exists'] and r['allowed'] for r in rows)

def test_actual_source_versions_and_current_android_are_not_relabelled():
    pkg=json.loads((ROOT/'client/package.json').read_text(encoding='utf-8'))
    lock=json.loads((ROOT/'client/package-lock.json').read_text(encoding='utf-8'))
    mobile=json.loads((ROOT/'mobile/version.json').read_text(encoding='utf-8-sig'))
    assert pkg['version']==lock['version']==lock['packages']['']['version']=='0.5.1'
    assert mobile['version']=='1.2.9' and mobile['versionCode']==16
