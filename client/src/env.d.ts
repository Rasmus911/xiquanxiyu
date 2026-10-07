/// <reference types="vite/client" />

declare const __XIQUAN_BUILD_ID__: string

interface PrintResult {
  success: boolean
  error?: string
}

type UpdateStatus = 'disabled' | 'unconfigured' | 'idle' | 'checking' | 'downloading' | 'not-available' | 'downloaded' | 'error'

interface UpdateState {
  status: UpdateStatus
  decision: 'none' | 'optional' | 'required'
  required: boolean
  currentVersion: string
  availableVersion: string | null
  percent: number
  message: string
  releaseNotes: string[]
  downloadUrl: string
  businessBusyReason: string | null
}

interface UpdateInstallResult {
  ok: boolean
  reason?: string
}

interface Window {
  xiquan?: {
    getConfig: () => Promise<Record<string, string>>
    getDesktopDiagnostics?: () => Promise<DesktopDiagnostics>
    restartWithSoftwareRendering?: (enabled: boolean) => Promise<UpdateInstallResult>
    setConfig: (config: Record<string, string>) => Promise<Record<string, string>>
    getPrinters: () => Promise<Array<{ name: string; displayName?: string; description?: string; status?: number; isDefault?: boolean }>>
    printReceipt: (receipt: unknown, printerName?: string) => Promise<PrintResult>
    getUpdateState: () => Promise<UpdateState>
    checkForUpdates: () => Promise<UpdateState>
    installUpdate: () => Promise<UpdateInstallResult>
    setBusinessBusy: (reason: string | null) => Promise<UpdateState>
    onUpdateState: (listener: (state: UpdateState) => void) => () => void
  }
}

interface DesktopDiagnostics {
  targetId: string
  appArch: string
  electronVersion: string
  chromiumVersion: string
  nodeVersion: string
  osRelease: string
  buildId: string
  softwareRendering: boolean
  testOnly: boolean
}
