import { registerPlugin, type PluginListenerHandle } from '@capacitor/core'

export type { PluginListenerHandle } from '@capacitor/core'

export interface DownloadProgress {
  percent: number
  bytesDownloaded: number
  totalBytes: number
}

export interface ApkUpdaterPlugin {
  download(options: { url: string; sha256: string; fileName: string }): Promise<{ path: string }>
  install(options: { path: string }): Promise<void>
  canInstallPackages(): Promise<{ allowed: boolean }>
  openInstallSettings(): Promise<void>
  clearDownload(options: { path?: string }): Promise<void>
  addListener(
    eventName: 'downloadProgress',
    listener: (event: DownloadProgress) => void,
  ): Promise<PluginListenerHandle>
}

export const ApkUpdater = registerPlugin<ApkUpdaterPlugin>('ApkUpdater')
