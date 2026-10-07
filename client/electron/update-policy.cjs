function parseSemver(value) {
  const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(String(value || ''))
  return match ? match.slice(1).map(Number) : null
}

function compareSemver(left, right) {
  const a = parseSemver(left)
  const b = parseSemver(right)
  if (!a || !b) throw new TypeError('Versions must use x.y.z format.')
  for (let index = 0; index < 3; index += 1) {
    if (a[index] !== b[index]) return a[index] < b[index] ? -1 : 1
  }
  return 0
}

function decideDesktopUpdate(currentVersion, policy) {
  if (compareSemver(currentVersion, policy.minimumVersion) < 0) return 'required'
  if (compareSemver(currentVersion, policy.latestVersion) < 0) return 'optional'
  return 'none'
}

function normalizeDesktopPolicy(value) {
  if (!value || !parseSemver(value.latestVersion) || !parseSemver(value.minimumVersion)) return null
  if (compareSemver(value.minimumVersion, value.latestVersion) > 0) return null
  if (typeof value.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(value.sha256)) return null

  let downloadUrl
  try {
    downloadUrl = new URL(String(value.downloadUrl || ''))
  } catch {
    return null
  }
  if (downloadUrl.protocol !== 'https:' || downloadUrl.username || downloadUrl.password) return null

  return {
    latestVersion: value.latestVersion,
    minimumVersion: value.minimumVersion,
    required: Boolean(value.required),
    downloadUrl: downloadUrl.toString(),
    sha256: value.sha256,
    releaseNotes: Array.isArray(value.releaseNotes) ? value.releaseNotes.map(String) : [],
    publishedAt: String(value.publishedAt || ''),
  }
}

module.exports = {
  compareSemver,
  decideDesktopUpdate,
  normalizeDesktopPolicy,
  parseSemver,
}
