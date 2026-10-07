const test = require('node:test')
const assert = require('node:assert/strict')
const crypto = require('node:crypto')
const { signingPlan, targets } = require('./desktop-045.cjs')
const { makeReleasePayload } = require('./desktop-release.cjs')
const { getTarget } = require('../../client/electron/target-profiles.cjs')

function fixture() {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('ed25519')
  const trust = { testOnly: false, publicKeyPem: publicKey.export({ type: 'spki', format: 'pem' }),
    keyId: crypto.createHash('sha256').update(publicKey.export({ type: 'spki', format: 'der' })).digest('hex').slice(0,16) }
  const previous = new Map()
  targets.forEach((id, index) => {
    const name = `Xiquan-Bathhouse-Setup-0.4.4-${id}.exe`
    const hash = 'a'.repeat(64), sha512 = Buffer.alloc(64, 1).toString('base64')
    const payload = makeReleasePayload({ profile: getTarget(id), version: '0.4.4', buildId: 'fixture-old', releaseTrust: trust,
      artifact: {fileName:name,size:120,sha256:hash,sha512},
      blockmap:{fileName:name+'.blockmap',size:50,sha256:hash},updaterManifest:{fileName:'latest.yml',sha256:hash} },
      {sequence:20+index, minimumVersion:'0.4.2',required:false,releaseNotes:[]})
    const bytes = Buffer.from(JSON.stringify(payload))
    previous.set(id, { payload:bytes.toString('base64'),signature:crypto.sign(null,bytes,privateKey).toString('base64') })
  })
  return {trust, previous}
}
test('four matching signed channels advance past the highest sequence, preserve minimums and exclude Win7', async () => {
  const f=fixture(), read=[]
  const plan=await signingPlan({readPolicy:async id=>{read.push(id);return f.previous.get(id)},trust:f.trust})
  assert.deepEqual(read,['win10-x86','win10-x64','win11-x86','win11-x64'])
  assert.equal(plan.sequence,24)
  assert.deepEqual(plan.previous.map(row=>row.minimum_version),['0.4.2','0.4.2','0.4.2','0.4.2'])
})
test('unavailable, forged, wrong-target and not-newer policies never infer bootstrap or sequence one', async () => {
  const f=fixture()
  await assert.rejects(signingPlan({trust:f.trust,readPolicy:async()=>{throw Error('offline')}}),/offline/)
  await assert.rejects(signingPlan({trust:f.trust,readPolicy:async()=>null}))
  await assert.rejects(signingPlan({trust:f.trust,readPolicy:async()=>f.previous.get('win11-x64')}))
  const forged={...f.previous.get('win10-x86'),signature:Buffer.alloc(64).toString('base64')}
  await assert.rejects(signingPlan({trust:f.trust,readPolicy:async()=>forged}))
  await assert.rejects(signingPlan({trust:f.trust,version:'0.4.4',readPolicy:async id=>f.previous.get(id)}),/newer/)
})
