const fs = require('node:fs')
const path = require('node:path')
const { targetIds, getTarget } = require('../../client/electron/target-profiles.cjs')
const { verifySignedRelease } = require('../../client/electron/desktop-release.cjs')
const { verifyReleaseSet, fileRecord } = require('./desktop-release.cjs')

function activationScript({ remoteStage, remoteCloudDir, targets = targetIds }) {
  if (!Array.isArray(targets) || !targets.length || new Set(targets).size !== targets.length) throw new Error('发布目标集无效')
  targets.forEach(getTarget)
  const legacy = targetIds.every(id => targets.includes(id))
  if (!/^\/tmp\/xiquan-windows-[A-Za-z0-9._-]+$/.test(remoteStage) || remoteStage.includes('..') ||
      !/^\/opt\/[A-Za-z0-9/_.-]+\/deploy\/cloud$/.test(remoteCloudDir) || remoteCloudDir.split('/').includes('..')) throw new Error('远端发布路径无效')
  return `#!/bin/bash
set -euo pipefail
STAGE='${remoteStage}'
CLOUD='${remoteCloudDir}'
test -d "$CLOUD/updates"
test -d "$CLOUD/releases"
cd "$STAGE"
sha256sum -c SHA256SUMS
# Preflight all immutable names before activating any channel.
while IFS= read -r file; do
  if test -f "$CLOUD/$file"; then
    cmp -s "$STAGE/$file" "$CLOUD/$file" || { printf 'Immutable file conflict: %s\\n' "$file"; exit 1; }
  fi
done < immutable-files.txt
python3 check-sequences.py "$STAGE" "$CLOUD"
while IFS= read -r file; do
  mkdir -p "$CLOUD/$(dirname "$file")"
  if ! test -f "$CLOUD/$file"; then cp "$STAGE/$file" "$CLOUD/$file.new"; mv -f "$CLOUD/$file.new" "$CLOUD/$file"; fi
done < immutable-files.txt
# Requested EXEs and blockmaps now exist; expose only their YAML and signed policies.
for id in ${targets.join(' ')}; do
  mkdir -p "$CLOUD/updates/desktop/$id" "$CLOUD/releases/desktop"
  cp "$STAGE/updates/desktop/$id/latest.yml" "$CLOUD/updates/desktop/$id/latest.yml.new"
  mv -f "$CLOUD/updates/desktop/$id/latest.yml.new" "$CLOUD/updates/desktop/$id/latest.yml"
  cp "$STAGE/releases/desktop/$id.json" "$CLOUD/releases/desktop/$id.json.new"
  mv -f "$CLOUD/releases/desktop/$id.json.new" "$CLOUD/releases/desktop/$id.json"
  printf 'Activated: %s\\n' "$id"
done
${legacy ? `# Preserve the currently deployed mobile/web entries, not a stale local policy copy.
python3 merge-legacy-policy.py "$STAGE" "$CLOUD"
cp updates/latest.yml "$CLOUD/updates/latest.yml.new"
mv -f "$CLOUD/updates/latest.yml.new" "$CLOUD/updates/latest.yml"
mv -f "$CLOUD/releases/client-policy.json.new" "$CLOUD/releases/client-policy.json"
cp delivery-index.json "$CLOUD/releases/desktop/delivery-index.json.new"
mv -f "$CLOUD/releases/desktop/delivery-index.json.new" "$CLOUD/releases/desktop/delivery-index.json"` : targets.map(id => `cp delivery-index.json "$CLOUD/releases/desktop/${id}-delivery-index.json.new"
mv -f "$CLOUD/releases/desktop/${id}-delivery-index.json.new" "$CLOUD/releases/desktop/${id}-delivery-index.json"`).join('\n')}
printf 'Requested channels activated. Existing data and unrequested channels preserved.\\n'
`
}
const sequenceScript = `import sys,json,base64,pathlib
stage,cloud=map(pathlib.Path,sys.argv[1:])
for file in (stage/'releases/desktop').glob('win*.json'):
    old=cloud/'releases/desktop'/file.name
    if old.exists():
        a=json.loads(base64.b64decode(json.loads(old.read_text())['payload']))
        b=json.loads(base64.b64decode(json.loads(file.read_text())['payload']))
        if b['sequence']<a['sequence'] or (b['sequence']==a['sequence'] and old.read_bytes()!=file.read_bytes()):
            raise SystemExit('Release sequence rollback/conflict: '+file.name)
`
const legacyScript = `import sys,json,pathlib
stage,cloud=map(pathlib.Path,sys.argv[1:])
current=cloud/'releases/client-policy.json'
if not current.is_file(): raise SystemExit('Existing public mobile/web policy is missing; no legacy activation')
policy=json.loads(current.read_text(encoding='utf-8-sig'))
if policy.get('schemaVersion')!=1: raise SystemExit('Existing legacy policy schema is not 1')
new=json.loads((stage/'releases/client-policy.json').read_text(encoding='utf-8'))
policy['desktop']=new['desktop']
(cloud/'releases/client-policy.json.new').write_text(json.dumps(policy,ensure_ascii=False,indent=2),encoding='utf-8')
`
async function stageWindowsRelease({ releaseRoot, outputRoot, targets = targetIds, legacyPolicy, dryRun = false, remoteCloudDir = '/opt/xiquan/xiquan/deploy/cloud' }) {
  const index = await verifyReleaseSet(releaseRoot, targets, { mode: 'release' })
  if (!index.complete) throw new Error('请求安装包不完整，不能发布')
  const legacy = index.allTargets
  const remoteStage = `/tmp/${path.basename(outputRoot)}`
  const activate = activationScript({ remoteStage, remoteCloudDir, targets })
  if (dryRun) return { dryRun: true, index, outputRoot }
  if (fs.existsSync(outputRoot)) throw new Error('暂存目录已存在，不会覆盖')
  if (legacy && (!legacyPolicy || legacyPolicy.schemaVersion !== 1)) throw new Error('缺少现有公开手机/Web版本策略')
  const paths = [], immutable = []
  const copy = (source, relative, fixed = false) => {
    fs.mkdirSync(path.dirname(path.join(outputRoot, relative)), { recursive: true }); fs.copyFileSync(source, path.join(outputRoot, relative))
    paths.push(relative); if (fixed) immutable.push(relative)
  }
  for (const report of index.targets) {
    const id = report.profile.targetId, directory = path.join(releaseRoot, id)
    for (const key of ['artifact', 'blockmap', 'updaterManifest']) copy(path.join(directory, report[key].fileName), `updates/desktop/${id}/${report[key].fileName}`, key !== 'updaterManifest')
    copy(path.join(directory, 'release.json'), `releases/desktop/${id}.json`)
  }
  if (legacy) {
  const bootstrap = index.targets.find(report => report.profile.targetId === 'win10-x64')
  for (const key of ['artifact', 'blockmap', 'updaterManifest']) copy(path.join(releaseRoot, 'win10-x64', bootstrap[key].fileName), `updates/${bootstrap[key].fileName}`, key !== 'updaterManifest')
  const envelope = JSON.parse(fs.readFileSync(path.join(releaseRoot, 'win10-x64/release.json'), 'utf8'))
  const release = verifySignedRelease(envelope, { trust: index.releaseTrust, profile: bootstrap.profile, currentVersion: index.version })
  const policy = { ...legacyPolicy, desktop: { ...release.desktop,
    downloadUrl: `https://api.pqxqxy.xyz/updates/${bootstrap.artifact.fileName}` } }
  fs.writeFileSync(path.join(outputRoot, 'releases/client-policy.json'), JSON.stringify(policy, null, 2)); paths.push('releases/client-policy.json')
  fs.writeFileSync(path.join(outputRoot, 'merge-legacy-policy.py'), legacyScript); paths.push('merge-legacy-policy.py')
  }
  fs.writeFileSync(path.join(outputRoot, 'delivery-index.json'), JSON.stringify(index, null, 2)); paths.push('delivery-index.json')
  fs.writeFileSync(path.join(outputRoot, 'check-sequences.py'), sequenceScript); paths.push('check-sequences.py')
  fs.writeFileSync(path.join(outputRoot, 'immutable-files.txt'), immutable.join('\n') + '\n'); paths.push('immutable-files.txt')
  fs.writeFileSync(path.join(outputRoot, 'activate.sh'), activate); paths.push('activate.sh')
  const checksums = []
  for (const file of paths) checksums.push(`${(await fileRecord(outputRoot, file)).sha256}  ${file}`)
  fs.writeFileSync(path.join(outputRoot, 'SHA256SUMS'), checksums.join('\n') + '\n')
  return { index, outputRoot, remoteStage }
}
if (require.main === module) {
  const [releaseRoot, outputRoot, policyPath, remoteCloudDir, dry, selected] = process.argv.slice(2)
  const targets = selected === undefined ? targetIds : selected.split(',')
  stageWindowsRelease({ releaseRoot, outputRoot, remoteCloudDir,
    targets, legacyPolicy: targetIds.every(id => targets.includes(id)) ? JSON.parse(fs.readFileSync(policyPath, 'utf8').replace(/^\uFEFF/, '')) : undefined, dryRun: dry === 'dry' })
    .then(result => console.log(JSON.stringify(result))).catch(error => { console.error(error.message); process.exitCode = 1 })
}
module.exports = { stageWindowsRelease, activationScript }
