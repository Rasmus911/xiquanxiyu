const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const { spawnSync } = require('node:child_process')
const { createRequire } = require('node:module')
const security = require('./source-security.cjs')
const migration = 'server/migrations/versions/20261005_independent_stock.py'
const schemaHead = '20261005_independent_stock'
const required = [migration, 'client/package.json', 'mobile/version.json', 'scripts/stock_import.py',
  'docs/inventory/2026-10-05-photo-stock-review.csv','docs/inventory/2026-10-05-photo-stock-notes.md',
  'docs/inventory/2026-10-05-photo-stock-import.md']
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex')
function windowsInputs(root) {
  const result=spawnSync('git',['ls-files','-z','--','client'],{cwd:root,encoding:'utf8',windowsHide:true})
  if(result.status!==0) throw Error('Windows input inventory unavailable')
  const files=result.stdout.split('\0').filter(file=>file && security.allowed(file)).sort()
  security.assertSourceSafe(root,files)
  return {schema:1,files:files.map(file=>{const bytes=fs.readFileSync(path.join(root,file));return {file,size:bytes.length,sha256:sha(bytes)}})}
}
function inspectSource(root) {
  function git(args) {
    const result = spawnSync('git',args,{cwd:root,encoding:'utf8',windowsHide:true,maxBuffer:32*1024*1024})
    if (result.status !== 0) throw Error('Uncommitted source or Git identity unavailable')
    return result.stdout
  }
  const commit = git(['rev-parse','HEAD']).trim()
  git(['diff','--quiet','HEAD','--'])
  const tracked = new Set(git(['ls-files','-z']).split('\0').filter(Boolean))
  const files = [...tracked].filter(file => security.allowed(file) && file !== 'mobile/public/download-config.json').sort()
  security.assertSourceSafe(root, files)
  for (const file of required) if (!files.includes(file)) throw Error(`Required committed stock source missing: ${file}`)
  const desktop = JSON.parse(fs.readFileSync(path.join(root,'client/package.json')))
  const android = JSON.parse(fs.readFileSync(path.join(root,'mobile/version.json')))
  if (desktop.version !== '0.4.4' || android.version !== '1.2.3' || android.versionCode !== 10) throw Error('Stock source versions mismatch')
  return {schema:1,label:'SOURCE/WEB',source_commit:commit,asset_source_commit:commit,schema_head:schemaHead,
    required_migration:migration,desktop_version:'0.4.4',android_version:'1.2.3',android_version_code:10,
    production_ready:false,files:files.map(file => {const bytes=fs.readFileSync(path.join(root,file));return {file,size:bytes.length,sha256:sha(bytes)}})}
}
async function readSourceArchive(file, expectedCommit) {
  if (!/^[0-9a-f]{40}$/.test(expectedCommit || '')) throw Error('Expected source commit required')
  const yauzl = createRequire(path.resolve(__dirname,'../../client/package.json'))('yauzl')
  // yauzl 2's fd-slicer streams can stall on current Node versions. Keep the
  // small SOURCE archive bounded and use its buffer reader, not that fd stream.
  const maximumArchiveSize = 64*1024*1024
  if (fs.statSync(file).size > maximumArchiveSize) throw Error('SOURCE archive exceeds size limit')
  const archiveBytes = fs.readFileSync(file)
  if (archiveBytes.length > maximumArchiveSize) throw Error('SOURCE archive exceeds size limit')
  const entries = new Map(), content = new Map()
  await new Promise((resolve,reject) => {
    let archive, settled = false
    const finish = error => {
      if (settled) return
      settled = true; clearTimeout(timer)
      if (error) {if (archive) archive.close(); reject(error)} else resolve()
    }
    const timer = setTimeout(() => finish(Error('SOURCE archive readback timed out')),60000)
    yauzl.fromBuffer(archiveBytes,{lazyEntries:true,validateEntrySizes:true},(error,zip) => {
    if (error) return finish(error)
    archive = zip
    const fail = finish
    zip.on('error',fail); zip.once('end',() => finish())
    zip.once('close',() => {if (!settled) fail(Error('SOURCE archive closed before readback finished'))})
    zip.on('entry', entry => {
      const name = entry.fileName
      if (!name.startsWith('xiquan/') || /\\|:/.test(name) || name.split('/').some(p => !p || p === '.' || p === '..') ||
          entries.has(name) || ((entry.externalFileAttributes >>> 16) & 0xf000) === 0xa000 || entry.uncompressedSize > 64*1024*1024) return fail(Error('Unexpected, duplicate or linked ZIP entry'))
      entries.set(name,null)
      zip.openReadStream(entry,(error,stream) => {
        if (error) return fail(error)
        const hash = crypto.createHash('sha256'), parts = []; let size=0
        const keep = ['xiquan/source-manifest.json','xiquan/client/package.json','xiquan/mobile/version.json'].includes(name)
        stream.on('error',fail); stream.on('data', bytes => {size+=bytes.length; hash.update(bytes);if(keep) parts.push(bytes)})
        stream.on('end',() => {entries.set(name,{size,sha256:hash.digest('hex')});if(keep) content.set(name,Buffer.concat(parts).toString('utf8'));zip.readEntry()})
      })
    });zip.readEntry()
    })
  })
  const manifest = JSON.parse(content.get('xiquan/source-manifest.json') || 'null')
  if (!manifest || manifest.schema !== 1 || manifest.source_commit !== expectedCommit || manifest.asset_source_commit !== expectedCommit ||
      manifest.schema_head !== schemaHead || manifest.required_migration !== migration || manifest.desktop_version !== '0.4.4' ||
      manifest.android_version !== '1.2.3' || manifest.android_version_code !== 10 || !Array.isArray(manifest.files)) throw Error('Stock archive source commit/schema/versions mismatch')
  const expected = new Set(['xiquan/source-manifest.json','xiquan/SOURCE-WEB-NOT-PRODUCTION.txt'])
  for (const record of manifest.files) {
    const name = 'xiquan/'+record.file
    const generated = /^(client|mobile)\/dist\//.test(record.file)
    if (expected.has(name) || (!generated && !security.allowed(record.file)) ||
        (generated && !/\.(html|js|css|json|svg|png|jpg|jpeg|webp|ico|woff|woff2|ttf|webmanifest)$/.test(record.file)) ||
        (generated && /(?:^|\/)(?:\.env|private|[^/]*secret)[^/]*|download-config\.json$/i.test(record.file))) throw Error('Unexpected stock source inventory entry')
    expected.add(name)
    const actual = entries.get(name)
    if (!actual || actual.size !== record.size || actual.sha256 !== record.sha256) throw Error('Stock ZIP inventory hash mismatch')
  }
  for (const file of [...required,'client/dist/index.html','mobile/dist/index.html']) if (!expected.has('xiquan/'+file)) throw Error('Required stock archive source missing')
  if (entries.size !== expected.size || [...entries.keys()].some(name => !expected.has(name))) throw Error('Unexpected ZIP inventory')
  const desktop = JSON.parse(content.get('xiquan/client/package.json')), android = JSON.parse(content.get('xiquan/mobile/version.json'))
  if (desktop.version !== '0.4.4' || android.version !== '1.2.3' || android.versionCode !== 10) throw Error('Actual archived versions mismatch')
  return manifest
}
module.exports = {inspectSource,readSourceArchive,windowsInputs,migration,schemaHead}
if (require.main === module) (async () => {
  const [command,input,commit] = process.argv.slice(2)
  if (!['inspect','archive','windows-inputs'].includes(command)) throw Error('Usage: stock-source.cjs inspect ROOT | archive ZIP COMMIT | windows-inputs ROOT')
  const result=JSON.stringify(command === 'windows-inputs' ? windowsInputs(input) : command === 'inspect' ? inspectSource(input) : await readSourceArchive(input,commit))
  const outputIndex=process.argv.indexOf('--output')
  if(outputIndex!==-1) {
    if(command!=='windows-inputs' || !process.argv[outputIndex+1]) throw Error('Only windows-inputs supports --output FILE')
    fs.writeFileSync(process.argv[outputIndex+1],result,{flag:'wx'})
  }
  console.log(result)
})().catch(error => {console.error(error.message);process.exitCode=1})
