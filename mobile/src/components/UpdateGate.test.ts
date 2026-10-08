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
