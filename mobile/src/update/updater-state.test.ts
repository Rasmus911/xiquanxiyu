import { describe, expect, it } from 'vitest'
import { initialNativeUpdateState, reduceUpdater } from './updater-state'

describe('native updater state', () => {
  it('tracks bounded download progress', () => {
    expect(reduceUpdater(initialNativeUpdateState(), { type: 'progress', percent: 42 }).percent).toBe(42)
    expect(reduceUpdater(initialNativeUpdateState(), { type: 'progress', percent: 140 }).percent).toBe(100)
  })

  it('turns a hash mismatch into a recoverable error', () => {
    const downloading = reduceUpdater(initialNativeUpdateState(), { type: 'progress', percent: 70 })
    expect(reduceUpdater(downloading, { type: 'hash-mismatch' })).toEqual({
      status: 'error',
      percent: 70,
      error: '安装包校验失败，请重新下载',
      path: null,
    })
  })

  it('moves through downloaded, permission and installing states', () => {
    const downloaded = reduceUpdater(initialNativeUpdateState(), { type: 'downloaded', path: '/cache/update.apk' })
    expect(downloaded.status).toBe('downloaded')
    expect(reduceUpdater(downloaded, { type: 'permission-required' }).status).toBe('needs-install-permission')
    expect(reduceUpdater(downloaded, { type: 'installing' }).status).toBe('installing')
  })
})
