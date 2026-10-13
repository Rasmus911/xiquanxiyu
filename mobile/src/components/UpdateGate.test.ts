// @vitest-environment jsdom
import { createApp, nextTick } from 'vue'
import { afterEach, expect, test, vi } from 'vitest'
import UpdateGate from './UpdateGate.vue'

const native = vi.hoisted(() => ({ download:vi.fn(),install:vi.fn(),permission:vi.fn(),external:vi.fn(),listener:vi.fn() }))
vi.mock('../native', () => ({ isNativeAndroidApp:() => true,openExternal:native.external }))
vi.mock('../update/native-updater', () => ({ ApkUpdater:{ download:native.download,install:native.install,
  canInstallPackages:native.permission,openInstallSettings:vi.fn(),clearDownload:vi.fn(),
  addListener:native.listener } }))
let cleanup = () => {}
afterEach(() => { cleanup(); vi.clearAllMocks() })
test('Android downloads inside the old app, blocks duplicate download and opens system installer without a webpage', async () => {
  native.listener.mockResolvedValue({ remove:async () => {} })
  native.permission.mockResolvedValue({ allowed:true })
  native.install.mockResolvedValue(undefined)
  let complete!: (result:{path:string}) => void
  native.download.mockImplementation(() => new Promise(resolve => { complete = resolve }))
  const host=document.createElement('div'); document.body.append(host)
  const app=createApp(UpdateGate,{policy:{ latestVersion:'1.2.7',latestVersionCode:14,minimumVersionCode:9,required:false,
    downloadUrl:'https://api.pqxqxy.xyz/mobile/downloads/xiquan-mobile-ordering-1.2.7.apk',sha256:'a'.repeat(64),releaseNotes:['新增管理员注册授权码'] },
    decision:'optional',businessBusy:null })
  app.mount(host); cleanup=() => { app.unmount(); host.remove() }
  await nextTick()
  expect(host.textContent).toContain('1.2.7')
  expect(host.textContent).toContain('新增管理员注册授权码')
  const button=host.querySelector('.update-primary') as HTMLButtonElement
  button.click(); button.click(); await nextTick()
  expect(button.disabled).toBe(true)
  expect(native.download).toHaveBeenCalledTimes(1)
  complete({path:'/safe/app/cache/update.apk'})
  await new Promise(resolve => setTimeout(resolve,0)); await nextTick()
  expect(native.install).toHaveBeenCalledWith({path:'/safe/app/cache/update.apk'})
  expect(native.external).not.toHaveBeenCalled()
})

test('a late final progress event cannot erase the APK path while install permission is being checked', async () => {
  let progress!: (event:{percent:number;bytesDownloaded:number;totalBytes:number}) => void
  let allowInstall!: (result:{allowed:boolean}) => void
  native.listener.mockImplementation((_name, listener) => {
    progress = listener
    return Promise.resolve({remove:async () => {}})
  })
  native.permission.mockImplementation(() => new Promise(resolve => {allowInstall = resolve}))
  native.download.mockResolvedValue({path:'/storage/emulated/0/Android/data/com.xiquan.mobileordering/cache/updates/xiquan-mobile-ordering-1.2.8.apk'})
  native.install.mockImplementation(({path}) => {
    if (!path) return Promise.reject(new Error('无法打开系统安装器：安装包不在应用更新目录中'))
    return Promise.resolve()
  })
  const host = document.createElement('div'); document.body.append(host)
  const app = createApp(UpdateGate,{policy:{latestVersion:'1.2.8',latestVersionCode:15,minimumVersionCode:9,required:false,
    downloadUrl:'https://api.pqxqxy.xyz/mobile/downloads/xiquan-mobile-ordering-1.2.8.apk',sha256:'a'.repeat(64),releaseNotes:[]},
    decision:'optional',businessBusy:null})
  app.mount(host); cleanup=() => {app.unmount(); host.remove()}
  await new Promise(resolve => setTimeout(resolve,0))
  ;(host.querySelector('.update-primary') as HTMLButtonElement).click()
  await new Promise(resolve => setTimeout(resolve,0))
  // Native progress is dispatched on the UI thread independently of resolve.
  progress({percent:100,bytesDownloaded:3000000,totalBytes:3000000})
  allowInstall({allowed:true})
  await new Promise(resolve => setTimeout(resolve,0)); await nextTick()
  expect(native.install).toHaveBeenCalledWith({path:'/storage/emulated/0/Android/data/com.xiquan.mobileordering/cache/updates/xiquan-mobile-ordering-1.2.8.apk'})
  expect(host.textContent).not.toContain('安装包不在应用更新目录中')
  expect(host.querySelector('.update-primary')?.textContent).toBe('再次打开安装确认')
})
