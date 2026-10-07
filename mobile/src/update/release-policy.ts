export type AndroidUpdateDecision = 'none' | 'optional' | 'required'

export interface AndroidReleasePolicy {
  latestVersion: string
  latestVersionCode: number
  minimumVersionCode: number
  required: boolean
  downloadUrl: string
  sha256: string
  releaseNotes: string[]
  publishedAt: string
}

function positiveInteger(value: unknown) {
  const number = Number(value)
  return Number.isInteger(number) && number > 0 ? number : null
}

function safeHttpsUrl(value: unknown, allowLegacyRelative = false) {
  try {
    const raw = String(value || '')
    const relative = raw.startsWith('/') && !raw.startsWith('//')
    const url = allowLegacyRelative && relative
      ? new URL(raw, 'https://api.pqxqxy.xyz')
      : new URL(raw)
    if (url.protocol !== 'https:' || url.username || url.password) return null
    return url.toString()
  } catch {
    return null
  }
}

export function normalizeAndroidPolicy(value: unknown): AndroidReleasePolicy | null {
  if (!value || typeof value !== 'object') return null
  const source = value as Record<string, unknown>
  const legacy = 'versionCode' in source && !('latestVersionCode' in source)
  const latestVersion = String(legacy ? source.version || '' : source.latestVersion || '')
  const latestVersionCode = positiveInteger(legacy ? source.versionCode : source.latestVersionCode)
  const minimumVersionCode = positiveInteger(source.minimumVersionCode)
  const downloadUrl = safeHttpsUrl(legacy ? source.androidApkUrl : source.downloadUrl, legacy)
  const sha256 = String(source.sha256 || '')
  if (!/^\d+\.\d+\.\d+$/.test(latestVersion)) return null
  if (!latestVersionCode || !minimumVersionCode || minimumVersionCode > latestVersionCode) return null
  if (!downloadUrl || !/^[0-9a-f]{64}$/.test(sha256)) return null

  const rawNotes = source.releaseNotes
  const releaseNotes = Array.isArray(rawNotes)
    ? rawNotes.map(String).filter(Boolean)
    : String(rawNotes || '').trim() ? [String(rawNotes).trim()] : []

  return {
    latestVersion,
    latestVersionCode,
    minimumVersionCode,
    required: Boolean(source.required),
    downloadUrl,
    sha256,
    releaseNotes,
    publishedAt: String(source.publishedAt || ''),
  }
}

export function decideAndroidUpdate(installedVersionCode: number, policy: AndroidReleasePolicy): AndroidUpdateDecision {
  if (installedVersionCode < policy.minimumVersionCode) return 'required'
  if (installedVersionCode < policy.latestVersionCode) return policy.required ? 'required' : 'optional'
  return 'none'
}
