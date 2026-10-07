import { describe, expect, it } from 'vitest'
import { updatePresentation, updateDialogVisible, type UpdatePresentationState } from './update-copy'

function state(overrides: Partial<UpdatePresentationState> = {}): UpdatePresentationState {
  return {
    status: 'idle',
    decision: 'none',
    required: false,
    percent: 0,
    availableVersion: null,
    businessBusyReason: null,
    downloadUrl: '',
    ...overrides,
  }
}

describe('updatePresentation', () => {
  it('keeps an in-flight payment page visible even when an update becomes required', () => {
    const required = state({ required: true, decision: 'required', status: 'downloaded', businessBusyReason: '正在确认收款' })
    expect(updateDialogVisible(required, true, null)).toBe(false)
    expect(updateDialogVisible({ ...required, businessBusyReason: null }, false, null)).toBe(true)
  })
  it('makes required downloads non-dismissible', () => {
    const actual = updatePresentation(state({
      status: 'downloading',
      decision: 'required',
      required: true,
      percent: 35,
      availableVersion: '0.3.0',
    }))

    expect(actual.title).toBe('必须更新后才能继续')
    expect(actual.allowDismiss).toBe(false)
    expect(actual.secondaryAction).toBeNull()
  })

  it('offers restart now or install after business for an optional download', () => {
    const actual = updatePresentation(state({
      status: 'downloaded',
      decision: 'optional',
      availableVersion: '0.3.0',
    }))

    expect(actual.primaryAction).toBe('重启安装')
    expect(actual.secondaryAction).toBe('营业结束后安装')
    expect(actual.allowDismiss).toBe(true)
  })

  it('disables installation and explains an active business write', () => {
    const actual = updatePresentation(state({
      status: 'downloaded',
      decision: 'required',
      required: true,
      businessBusyReason: '正在确认收款',
    }))

    expect(actual.primaryDisabled).toBe(true)
    expect(actual.blockReason).toBe('正在确认收款')
  })

  it('offers retry without bypassing signed installation through a manual download', () => {
    const actual = updatePresentation(state({
      status: 'error',
      decision: 'optional',
      downloadUrl: 'https://api.pqxqxy.xyz/updates/client.exe',
    }))

    expect(actual.primaryAction).toBe('重新检查')
    expect(actual.showManualDownload).toBe(false)
  })
})
