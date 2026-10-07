export type NativeUpdateState =
  | { status: 'idle'; percent: 0; error: null; path: null }
  | { status: 'downloading'; percent: number; error: null; path: null }
  | { status: 'downloaded'; percent: 100; error: null; path: string }
  | { status: 'needs-install-permission'; percent: 100; error: null; path: string }
  | { status: 'installing'; percent: 100; error: null; path: string }
  | { status: 'error'; percent: number; error: string; path: string | null }

export type NativeUpdateEvent =
  | { type: 'reset' }
  | { type: 'progress'; percent: number }
  | { type: 'downloaded'; path: string }
  | { type: 'permission-required' }
  | { type: 'installing' }
  | { type: 'hash-mismatch' }
  | { type: 'error'; message: string }

export function initialNativeUpdateState(): NativeUpdateState {
  return { status: 'idle', percent: 0, error: null, path: null }
}

export function reduceUpdater(state: NativeUpdateState, event: NativeUpdateEvent): NativeUpdateState {
  if (event.type === 'reset') return initialNativeUpdateState()
  if (event.type === 'progress') {
    const percent = Math.max(0, Math.min(100, Math.round(Number(event.percent) || 0)))
    return { status: 'downloading', percent, error: null, path: null }
  }
  if (event.type === 'downloaded') {
    return { status: 'downloaded', percent: 100, error: null, path: event.path }
  }
  if (event.type === 'permission-required') {
    return {
      status: 'needs-install-permission',
      percent: 100,
      error: null,
      path: state.path || '',
    }
  }
  if (event.type === 'installing') {
    return { status: 'installing', percent: 100, error: null, path: state.path || '' }
  }
  if (event.type === 'hash-mismatch') {
    return {
      status: 'error',
      percent: state.percent,
      error: '安装包校验失败，请重新下载',
      path: null,
    }
  }
  return {
    status: 'error',
    percent: state.percent,
    error: event.message || '更新失败，请重试',
    path: state.path,
  }
}
