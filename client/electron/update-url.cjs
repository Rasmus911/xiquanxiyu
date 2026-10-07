function deriveServerRoot(serverUrl) {
  try {
    const url = new URL(String(serverUrl || '').trim())
    if (url.protocol !== 'https:' || url.username || url.password) return null
    const apiPath = url.pathname.replace(/\/+$/, '')
    if (!apiPath.endsWith('/api')) return null
    url.pathname = `${apiPath.slice(0, -4)}/`.replace(/\/{2,}/g, '/')
    url.search = ''
    url.hash = ''
    return url
  } catch {
    return null
  }
}

function deriveUpdateUrl(serverUrl) {
  const url = deriveServerRoot(serverUrl)
  if (!url) return null
  url.pathname = `${url.pathname}updates/`.replace(/\/{2,}/g, '/')
  return url.toString()
}

function derivePolicyUrl(serverUrl) {
  const url = deriveServerRoot(serverUrl)
  if (!url) return null
  url.pathname = `${url.pathname}releases/client-policy.json`.replace(/\/{2,}/g, '/')
  return url.toString()
}

function deriveTargetUrls(serverUrl, targetId) {
  try {
    require('./target-profiles.cjs').getTarget(targetId)
    const api = new URL(String(serverUrl))
    if (api.origin !== 'https://api.pqxqxy.xyz' || api.username || api.password ||
        api.pathname.replace(/\/+$/, '') !== '/api' || api.search || api.hash) return null
    return {
      feedUrl: `${api.origin}/updates/desktop/${targetId}/`,
      policyUrl: `${api.origin}/releases/desktop/${targetId}.json`,
      origin: api.origin,
    }
  } catch { return null }
}

module.exports = { derivePolicyUrl, deriveUpdateUrl, deriveTargetUrls }

