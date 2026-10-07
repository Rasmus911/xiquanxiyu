// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createApp, h } from 'vue'
import DownloadView from './DownloadView.vue'
import { openExternal } from '../native'
import type { DownloadConfig } from '../types'

vi.mock('../native', () => ({ openExternal: vi.fn().mockResolvedValue(undefined) }))

const release: DownloadConfig = {
  version: '1.2.2', versionCode: 9, minimumVersionCode: 9,
  androidApkUrl: 'https://api.pqxqxy.xyz/mobile/downloads/xiquan-mobile-ordering-1.2.2.apk',
  sha256: '869e52d5d76265591ff7936f27706eacbb690df5afb7952a11b128eeba6af04c',
  releaseNotes: '现有正式安装包',
}
let dispose = () => {}

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...release }) }))
})
afterEach(() => { dispose(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

async function render() {
  const root = document.createElement('div')
  document.body.append(root)
  const app = createApp({ render: () => h(DownloadView) })
  app.mount(root)
  dispose = () => { app.unmount(); root.remove() }
  await vi.waitFor(() => expect(root.querySelector('.release-card button')).not.toBeNull())
  return root
}

it.each([
  ['Android', 'Mozilla/5.0 (Linux; Android 14)'],
  ['鸿蒙', 'Mozilla/5.0 (HarmonyOS 5.0)'],
  ['iPhone', 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)'],
  ['Windows', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'],
  ['微信', 'Mozilla/5.0 (iPhone) MicroMessenger/8.0'],
  ['未知设备', ''],
])('%s visitor can click the same APK download without a device gate', async (_, agent) => {
  vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(agent)
  const root = await render()
  const button = root.querySelector<HTMLButtonElement>('.release-card button')!
  expect(button.disabled).toBe(false)
  expect(button.classList.contains('unsupported')).toBe(false)
  button.click()
  await vi.waitFor(() => expect(openExternal).toHaveBeenCalledExactlyOnceWith(release.androidApkUrl))
  expect(root.querySelector('.notice')).toBeNull()
})

it('does not read the user agent and shows WeChat guidance without intercepting download', async () => {
  const agent = vi.spyOn(navigator, 'userAgent', 'get').mockImplementation(() => {
    throw new Error('The download page must not inspect the device')
  })
  const root = await render()
  expect(agent).not.toHaveBeenCalled()
  expect(root.querySelector('.wechat-tip')?.textContent).toContain('在浏览器打开')
  root.querySelector<HTMLButtonElement>('.release-card button')!.click()
  await vi.waitFor(() => expect(openExternal).toHaveBeenCalledExactlyOnceWith(release.androidApkUrl))
})

it('still refuses an unpublished APK URL rather than navigating to an unrelated page', async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ ...release, androidApkUrl: '' }) } as Response)
  const root = await render()
  root.querySelector<HTMLButtonElement>('.release-card button')!.click()
  await vi.waitFor(() => expect(root.querySelector('.notice')?.textContent).toContain('安装包尚未发布'))
  expect(openExternal).not.toHaveBeenCalled()
})
