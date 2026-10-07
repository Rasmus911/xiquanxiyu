import { describe, expect, it } from 'vitest'
import { decideAndroidUpdate, normalizeAndroidPolicy } from './release-policy'

const policy = {
  latestVersion: '1.1.0',
  latestVersionCode: 5,
  minimumVersionCode: 4,
  required: false,
  downloadUrl: 'https://api.pqxqxy.xyz/mobile/downloads/xiquan-mobile-ordering-1.1.0.apk',
  sha256: 'a'.repeat(64),
  releaseNotes: ['应用内覆盖更新'],
  publishedAt: '2026-09-27T12:00:00+08:00',
}

describe('Android release policy', () => {
  it('requires a build below minimum', () => {
    expect(decideAndroidUpdate(3, policy)).toBe('required')
  })

  it('offers a compatible newer build', () => {
    expect(decideAndroidUpdate(4, policy)).toBe('optional')
  })

  it('does not downgrade current or newer builds', () => {
    expect(decideAndroidUpdate(5, policy)).toBe('none')
    expect(decideAndroidUpdate(6, policy)).toBe('none')
  })

  it('normalizes the unified policy entry', () => {
    expect(normalizeAndroidPolicy(policy)).toEqual(policy)
  })

  it('normalizes the legacy download config for one-release fallback', () => {
    expect(normalizeAndroidPolicy({
      version: '1.1.0',
      versionCode: 5,
      minimumVersionCode: 4,
      androidApkUrl: policy.downloadUrl,
      sha256: policy.sha256,
      releaseNotes: '应用内覆盖更新',
    })).toEqual({ ...policy, publishedAt: '' })
  })

  it('accepts the root-relative APK URL emitted by the release builder', () => {
    expect(normalizeAndroidPolicy({
      version: '1.1.0',
      versionCode: 5,
      minimumVersionCode: 4,
      androidApkUrl: '/mobile/downloads/xiquan-mobile-ordering-1.1.0.apk',
      sha256: policy.sha256,
    })?.downloadUrl).toBe(policy.downloadUrl)
  })

  it('rejects unsafe URLs and invalid hashes', () => {
    expect(normalizeAndroidPolicy({ ...policy, downloadUrl: 'http://example.com/app.apk' })).toBeNull()
    expect(normalizeAndroidPolicy({ ...policy, sha256: 'bad' })).toBeNull()
  })
})
