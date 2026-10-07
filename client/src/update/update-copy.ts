export interface UpdatePresentationState {
  status: UpdateStatus
  decision: 'none' | 'optional' | 'required'
  required: boolean
  percent: number
  availableVersion: string | null
  businessBusyReason: string | null
  downloadUrl: string
}

export interface UpdatePresentation {
  title: string
  primaryAction: string | null
  secondaryAction: string | null
  allowDismiss: boolean
  primaryDisabled: boolean
  blockReason: string | null
  showManualDownload: boolean
}

export function updateDialogVisible(state: UpdatePresentationState | null, opened: boolean, dismissedVersion: string | null): boolean {
  if (!state || state.businessBusyReason) return false
  if (opened) return true
  if (['disabled', 'unconfigured'].includes(state.status)) return false
  if (state.required || state.decision === 'required') return true
  return state.decision === 'optional' && dismissedVersion !== state.availableVersion
}

export function updatePresentation(state: UpdatePresentationState): UpdatePresentation {
  const required = state.required || state.decision === 'required'
  const blockReason = state.businessBusyReason || null
  let primaryAction: string | null = null
  let secondaryAction: string | null = null

  if (state.status === 'downloaded') {
    primaryAction = '重启安装'
    if (!required) secondaryAction = '营业结束后安装'
  } else if (state.status === 'error') {
    primaryAction = '重新检查'
  } else if (['idle', 'not-available'].includes(state.status)) {
    primaryAction = '检查更新'
  }

  return {
    title: required ? '必须更新后才能继续' : '发现溪泉洗浴新版本',
    primaryAction,
    secondaryAction,
    allowDismiss: !required,
    primaryDisabled: Boolean(blockReason) || ['checking', 'downloading'].includes(state.status),
    blockReason,
    // A browser download would bypass the verified desktop installation path.
    showManualDownload: false,
  }
}
