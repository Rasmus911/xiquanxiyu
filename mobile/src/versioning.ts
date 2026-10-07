export type UpdateDecision = 'none' | 'optional' | 'required'

export interface VersionPolicy {
  version: string
  versionCode: number
  minimumVersionCode: number
}

export function decideUpdate(installedVersionCode: number, policy: VersionPolicy): UpdateDecision {
  if (installedVersionCode < policy.minimumVersionCode) return 'required'
  if (installedVersionCode < policy.versionCode) return 'optional'
  return 'none'
}
