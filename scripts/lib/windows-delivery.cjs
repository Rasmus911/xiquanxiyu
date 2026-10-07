const fs = require('node:fs')
const path = require('node:path')
const { verifyReleaseSet, fileRecord } = require('./desktop-release.cjs')

async function prepareDelivery({ releaseRoot, outputRoot, targets, candidate = false, projectRoot = path.resolve(__dirname, '../..') }) {
  const index = await verifyReleaseSet(releaseRoot, targets, { mode: candidate ? 'candidate' : 'release' })
  if (!index.complete) throw new Error('请求安装包不完整，不能生成交付ZIP')
  if (fs.existsSync(outputRoot)) throw new Error('交付暂存目录已存在，不会覆盖')
  fs.mkdirSync(outputRoot, { recursive: true })
  const files = []
  function copy(source, relative) {
    fs.mkdirSync(path.dirname(path.join(outputRoot, relative)), { recursive: true })
    fs.copyFileSync(source, path.join(outputRoot, relative)); files.push(relative)
  }
  for (const report of index.targets) {
    const id = report.profile.targetId
    for (const key of ['artifact', 'blockmap', 'updaterManifest']) copy(path.join(releaseRoot, id, report[key].fileName), `${id}/${report[key].fileName}`)
    if (!candidate) copy(path.join(releaseRoot, id, 'release.json'), `${id}/release.json`)
  }
  for (const name of ['2026-10-03六版本安装与更新.md', '2026-10-03六版本兼容验收.md']) {
    const source = path.join(projectRoot, 'docs', name)
    if (fs.existsSync(source)) copy(source, 'docs/' + name)
  }
  const publicFiles = ['scripts/build-windows-release.ps1', 'scripts/new-desktop-release-key.ps1', 'scripts/sign-windows-release.ps1',
    'scripts/publish-windows-release.ps1', 'scripts/build-windows-delivery.ps1', 'scripts/test-windows-compat.ps1']
  for (const relative of publicFiles) {
    const source = path.join(projectRoot, relative)
    if (fs.existsSync(source)) copy(source, 'reference/' + relative)
  }
  fs.writeFileSync(path.join(outputRoot, 'release-public-key.pem'), index.releaseTrust.publicKeyPem, 'utf8'); files.push('release-public-key.pem')
  fs.writeFileSync(path.join(outputRoot, 'delivery-index.json'), JSON.stringify(index, null, 2), 'utf8'); files.push('delivery-index.json')
  const smokePath = path.join(releaseRoot, 'runtime-smoke.json')
  if (fs.existsSync(smokePath)) copy(smokePath, 'runtime-smoke.json')
  fs.writeFileSync(path.join(outputRoot, 'README.txt'), candidate
    ? 'COMPATIBILITY CANDIDATE - not a signed production release. Do not upload to production update channels.\nInstall the correct target without uninstalling the existing client. Real OS/USB/in-place update acceptance is still required.\nReference scripts must be run from the original project with its dependencies, not from this installer bundle.\n'
    : `WINDOWS INSTALLERS (${index.requestedTargets.join(', ')}) - release manifests verified. Review delivery-index.json and OS/USB acceptance before rollout.\nReference scripts require the original project and its dependencies.\n`); files.push('README.txt')
  const checksums = []
  for (const file of files) checksums.push(`${(await fileRecord(outputRoot, file)).sha256}  ${file}`)
  fs.writeFileSync(path.join(outputRoot, 'SHA256SUMS'), checksums.join('\n') + '\n'); files.push('SHA256SUMS')
  return { index, files, outputRoot }
}
if (require.main === module) {
  const [releaseRoot, outputRoot, mode, selected] = process.argv.slice(2)
  prepareDelivery({ releaseRoot, outputRoot, targets: selected === undefined ? undefined : selected.split(','), candidate: mode === 'candidate' }).then(result => console.log(JSON.stringify(result)))
    .catch(error => { console.error(error.message); process.exitCode = 1 })
}
module.exports = { prepareDelivery }
