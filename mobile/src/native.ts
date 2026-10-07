import { App } from '@capacitor/app'
import { Browser } from '@capacitor/browser'
import { Capacitor } from '@capacitor/core'
import version from '../version.json'

export function isNativeApp() {
  return Capacitor.isNativePlatform()
}

export function isNativeAndroidApp() {
  return Capacitor.isNativePlatform() && Capacitor.getPlatform() === 'android'
}

export async function getInstalledBuildNumber() {
  if (!isNativeApp()) return version.versionCode
  const info = await App.getInfo()
  const build = Number.parseInt(info.build, 10)
  return Number.isFinite(build) ? build : version.versionCode
}

export async function openExternal(url: string) {
  if (isNativeApp()) {
    await Browser.open({ url })
    return
  }
  location.assign(url)
}

export async function onAppResume(listener: () => void | Promise<void>) {
  if (!isNativeApp()) return async () => undefined
  const handle = await App.addListener('appStateChange', ({ isActive }) => {
    if (isActive) void listener()
  })
  return () => handle.remove()
}
