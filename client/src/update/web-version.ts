export type WebUpdateDecision = 'none' | 'ready' | 'deferred' | 'required'

export interface WebReleasePolicy {
  buildId: string
  required: boolean
  releaseNotes: string[]
  publishedAt: string
}

export function normalizeWebRelease(value: unknown): WebReleasePolicy | null {
  if (!value || typeof value !== 'object') return null
  const source = value as Record<string, unknown>
  const buildId = String(source.buildId || '').trim()
  if (!buildId || !Array.isArray(source.releaseNotes)) return null
  return {
    buildId,
    required: Boolean(source.required),
    releaseNotes: source.releaseNotes.map(String).filter(Boolean),
    publishedAt: String(source.publishedAt || ''),
  }
}

export function webUpdateDecision(
  currentBuildId: string,
  remote: Pick<WebReleasePolicy, 'buildId' | 'required'>,
  businessBusyReason: string | null,
): WebUpdateDecision {
  if (!remote.buildId || remote.buildId === currentBuildId) return 'none'
  if (businessBusyReason) return 'deferred'
  return remote.required ? 'required' : 'ready'
}
