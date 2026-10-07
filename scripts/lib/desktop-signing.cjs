const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')

function generateReleaseKey(passphrase) {
  if (typeof passphrase !== 'string' || passphrase.length < 16) throw new Error('发布密钥密码至少16个字符')
  const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519')
  return { publicKeyPem: publicKey.export({ type: 'spki', format: 'pem' }),
    privateKeyPem: privateKey.export({ type: 'pkcs8', format: 'pem', cipher: 'aes-256-cbc', passphrase }),
    keyId: crypto.createHash('sha256').update(publicKey.export({ type: 'spki', format: 'der' })).digest('hex').slice(0, 16) }
}
function unlockKey(privateKeyPem, passphrase, publicKeyPem) {
  let key
  try {
    if (!privateKeyPem.startsWith('-----BEGIN ENCRYPTED PRIVATE KEY-----')) throw new Error()
    key = crypto.createPrivateKey({ key: privateKeyPem, passphrase })
  } catch { throw new Error('发布私钥格式或密码错误，已停止签名') }
  const publicKey = crypto.createPublicKey(key)
  if (key.asymmetricKeyType !== 'ed25519' || publicKey.export({ type: 'spki', format: 'pem' }) !== publicKeyPem) throw new Error('私钥与安装包发布公钥不匹配')
  return key
}
function signReleasePayload(payload, privateKeyPem, passphrase, publicKeyPem) {
  const key = unlockKey(privateKeyPem, passphrase, publicKeyPem)
  const bytes = Buffer.from(JSON.stringify(payload), 'utf8')
  return { payload: bytes.toString('base64'), signature: crypto.sign(null, bytes, key).toString('base64') }
}
async function cli(input) {
  if (input.action === 'new-key') {
    const privatePath = path.resolve(input.privatePath), publicPath = path.resolve(input.publicPath)
    if (privatePath === publicPath || fs.existsSync(privatePath) || fs.existsSync(publicPath)) throw new Error('密钥文件已存在，不会覆盖')
    const keys = generateReleaseKey(input.passphrase)
    fs.mkdirSync(path.dirname(privatePath), { recursive: true }); fs.mkdirSync(path.dirname(publicPath), { recursive: true })
    fs.writeFileSync(privatePath, keys.privateKeyPem, { flag: 'wx', mode: 0o600 })
    fs.writeFileSync(publicPath, keys.publicKeyPem, { flag: 'wx' })
    console.log(`Public key ID: ${keys.keyId}. Keep the encrypted private key offline.`)
    return
  }
  if (input.action !== 'sign') throw new Error('签名操作无效')
  const { createRequire } = require('node:module')
  const fromClient = createRequire(path.resolve(__dirname, '../../client/package.json'))
  const { targetIds, getTarget } = require('../../client/electron/target-profiles.cjs')
  const { publicTrust } = require('../../client/build/windows-pack.cjs')
  const { inspectPayload, fileRecord, makeReleasePayload, verifyReleaseSet } = require('./desktop-release.cjs')
  const { verifySignedRelease, validVersion } = require('../../client/electron/desktop-release.cjs')
  const { buildBlockMap } = fromClient('app-builder-lib/out/targets/blockmap/blockmap')
  const yaml = fromClient('js-yaml')
  const root = fs.realpathSync(input.releaseRoot), trust = publicTrust(path.join(root, 'release-public-key.pem'))
  const selected = input.targets === undefined ? targetIds : input.targets
  if (!Array.isArray(selected) || !selected.length || new Set(selected).size !== selected.length) throw new Error('签名目标集无效')
  selected.forEach(getTarget)
  if (!Number.isSafeInteger(input.sequence) || input.sequence < 1 || !validVersion(input.minimumVersion)) throw new Error('签名发布序号或最低版本无效')
  let version, buildId
  for (const id of selected) {
    const directory = path.join(root, id), report = inspectPayload(directory, getTarget(id), trust)
    version ||= report.version; buildId ||= report.identity.buildId
    if (report.version !== version || report.identity.buildId !== buildId || report.identity.releaseTrust.testOnly) throw new Error('测试包或构建目标不一致，拒绝正式签名')
    if (fs.existsSync(path.join(directory, 'release.json'))) throw new Error('此构建已签名，请使用新构建目录；现有签名不会覆盖')
  }
  // This user-only CLI reads a private key only after every requested public payload passes preflight.
  const privatePem = fs.readFileSync(input.privatePath, 'utf8')
  unlockKey(privatePem, input.passphrase, trust.publicKeyPem)
  for (const id of selected) {
    const directory = path.join(root, id), fileName = `Xiquan-Bathhouse-Setup-${version}-${id}.exe`
    await buildBlockMap(path.join(directory, fileName), 'gzip', path.join(directory, fileName + '.blockmap'))
    const artifact = await fileRecord(directory, fileName), blockmap = await fileRecord(directory, fileName + '.blockmap')
    const manifest = { version, files: [{ url: fileName, sha512: artifact.sha512, size: artifact.size }], path: fileName, sha512: artifact.sha512, releaseDate: new Date().toISOString() }
    fs.writeFileSync(path.join(directory, 'latest.yml'), yaml.dump(manifest), 'utf8')
    const report = { profile: getTarget(id), version, buildId, releaseTrust: trust, artifact, blockmap, updaterManifest: await fileRecord(directory, 'latest.yml') }
    const payload = makeReleasePayload(report, { sequence: input.sequence, minimumVersion: input.minimumVersion,
      required: input.required === true, releaseNotes: input.releaseNotes || [] })
    const envelope = signReleasePayload(payload, privatePem, input.passphrase, trust.publicKeyPem)
    verifySignedRelease(envelope, { trust, profile: getTarget(id), currentVersion: version })
    fs.writeFileSync(path.join(directory, 'release.json'), JSON.stringify(envelope), { flag: 'wx' })
  }
  const index = await verifyReleaseSet(root, selected, { mode: 'release', trust })
  fs.writeFileSync(path.join(root, 'delivery-index.json'), JSON.stringify(index, null, 2), 'utf8')
  console.log(`Release manifests verified (${selected.join(', ')}): ${root}`)
}
if (require.main === module) {
  let text = ''
  process.stdin.setEncoding('utf8'); process.stdin.on('data', chunk => { text += chunk })
  process.stdin.on('end', () => {
    let input
    try { input = JSON.parse(text.replace(/^\uFEFF/, '')); text = '' } catch { console.error('签名输入无效'); process.exitCode = 1; return }
    cli(input).catch(error => { console.error(error.message); process.exitCode = 1 }).finally(() => { input.passphrase = '' })
  })
}
module.exports = { generateReleaseKey, signReleasePayload }
