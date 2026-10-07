const { requestHttpsJson } = require('../../client/electron/https-json.cjs')
const { verifySignedRelease, validVersion } = require('../../client/electron/desktop-release.cjs')
const { compareSemver } = require('../../client/electron/update-policy.cjs')
const { getTarget } = require('../../client/electron/target-profiles.cjs')
const { trust: originalTrust } = require('./operations-release.cjs')

const targets = Object.freeze(['win10-x86','win10-x64','win11-x86','win11-x64'])
async function signingPlan({ version='0.4.5', trust=originalTrust, readPolicy=async id =>
  requestHttpsJson(`https://api.pqxqxy.xyz/releases/desktop/${id}.json`, {allowedOrigin:'https://api.pqxqxy.xyz'}) }={}) {
  if (!validVersion(version)) throw Error('Invalid next desktop version')
  const previous=[]
  for (const target of targets) {
    const envelope=await readPolicy(target)
    const release=verifySignedRelease(envelope,{trust,profile:getTarget(target),currentVersion:'0.0.0'})
    if (compareSemver(version,release.desktop.latestVersion)<=0) throw Error(`Next release must be newer: ${target}`)
    previous.push({target,sequence:release.sequence,minimum_version:release.desktop.minimumVersion,envelope})
  }
  const sequence=Math.max(...previous.map(row=>row.sequence))+1
  if (!Number.isSafeInteger(sequence)||sequence>2147483647) throw Error('Release sequence exhausted')
  return {schema:1,version,trust_key_id:trust.keyId,sequence,checked_at:new Date().toISOString(),previous}
}
async function verifyCandidates(root, version='0.4.5') {
  const result=await require('./desktop-release.cjs').verifyReleaseSet(root,targets,{mode:'candidate',trust:originalTrust})
  if(result.version!==version||result.releaseTrust.keyId!==originalTrust.keyId) throw Error('Candidate identity mismatch')
  return {version:result.version,targets,trust_key_id:originalTrust.keyId}
}
module.exports={signingPlan,targets,verifyCandidates}
if(require.main===module) (process.argv[2]==='verify-candidates' ? verifyCandidates(process.argv[3],process.argv[4]) : signingPlan({version:process.argv[3]||'0.4.5'})).then(plan=>console.log(JSON.stringify(plan)))
  .catch(error=>{console.error(error.message);process.exitCode=1})
