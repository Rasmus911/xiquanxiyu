import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus, { ElButton, ElDialog, ElMessage } from 'element-plus'
import { Download, Right } from '@element-plus/icons-vue'
import UpdateCenter from './UpdateCenter.vue'
import ReleaseHistory from './ReleaseHistory.vue'
import { compileStyle, parse } from '@vue/compiler-sfc'
import historySource from './ReleaseHistory.vue?raw'
import dialogSource from './UpdateCenter.vue?raw'
import { useRuntimeStore } from '../../stores/runtime'

const wrappers: VueWrapper[] = []
afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  delete window.xiquan
  ElMessage.closeAll()
  vi.restoreAllMocks()
})

function state(overrides: Partial<UpdateState> = {}): UpdateState {
  return { status: 'idle', decision: 'none', required: false, currentVersion: '0.5.1', availableVersion: null,
    releaseVersion: null, releasePublishedAt: null, percent: 0, message: '可以检查更新', releaseNotes: [],
    downloadUrl: '', businessBusyReason: null, ...overrides }
}

async function open(initial: () => Promise<UpdateState> = async () => state(), stubTeleport = true) {
  let listener!: (value: UpdateState) => void
  const pinia = createPinia()
  const runtime = useRuntimeStore(pinia)
  runtime.openUpdateCenter()
  window.xiquan = { getUpdateState: initial, onUpdateState: callback => { listener = callback; return () => {} },
    checkForUpdates: async () => state(), installUpdate: async () => ({ ok: true }) } as NonNullable<Window['xiquan']>
  const wrapper = mount(UpdateCenter, { attachTo: document.body, global: {
    plugins: [pinia, ElementPlus], components: { Download, Right }, stubs: { teleport: stubTeleport },
  } })
  wrappers.push(wrapper)
  await flushPromises()
  return { wrapper, runtime, emit: (value: UpdateState) => listener(value) }
}

it('shows offline history when the initial desktop state request fails and receives later state events', async () => {
  const { wrapper, emit } = await open(async () => { throw Error('offline') })
  expect(wrapper.text()).toContain('增加实体卡消费功能')
  expect(wrapper.text()).toContain('发布日期未核实')
  expect(wrapper.findComponent(ElDialog).props('modelValue')).toBe(true)
  emit(state({ status: 'not-available', message: '当前已是最新版', releaseVersion: '0.5.1', releasePublishedAt: '2026-10-12T01:02:03Z' }))
  await flushPromises()
  expect(wrapper.text()).toContain('当前已是最新版')
  expect(wrapper.text()).toContain('2026/10/12 09:02')
  const entries = wrapper.findAll('.release-history article')
  const released = entries.find(entry => entry.find('strong').text() === '0.5.1')!
  expect(released.text()).not.toContain('待发布')
  expect(released.text()).toContain('2026/10/12 09:02')
  expect(entries.find(entry => entry.find('strong').text() === '0.5.2')!.text()).toContain('待发布')
})

it('keeps built-in history visible when already latest, with footer controls outside the keyboard scroll region', async () => {
  const { wrapper } = await open(async () => state({ status: 'not-available', message: '当前已是最新版' }))
  const history = wrapper.get('.release-history')
  expect(history.attributes('tabindex')).toBe('0')
  expect(history.attributes('role')).toBe('region')
  expect(history.findAll('article')).toHaveLength(10)
  expect(history.text()).toContain('0.5.5')
  expect(history.text()).toContain('0.4.7')
  expect(history.find('.dialog-actions').exists()).toBe(false)
  expect(wrapper.get('.dialog-actions').text()).toContain('检查更新')
  const close = wrapper.findAllComponents(ElButton).find(button => button.text() === '关闭')!
  await close.trigger('click')
  expect(wrapper.findComponent(ElDialog).props('modelValue')).toBe(false)
})

it('keeps long history notes as escaped text and gives the region keyboard focus', async () => {
  const notes = Array.from({ length: 100 }, (_, index) => `日志 ${index} <img src=x onerror=alert(1)>`)
  const wrapper = mount(ReleaseHistory, { attachTo: document.body, props: {
    entries: [{ version: '0.5.1', state: 'pending', source: 'user', publishedAt: null, notes }],
  } })
  wrappers.push(wrapper)
  expect(wrapper.findAll('ol li')).toHaveLength(100)
  expect(wrapper.text()).toContain('<img src=x onerror=alert(1)>')
  expect(wrapper.find('img').exists()).toBe(false)
  ;(wrapper.get('.release-history').element as HTMLElement).focus()
  expect(document.activeElement).toBe(wrapper.get('.release-history').element)
})

it('preserves required download dismissal protection and disables installation when a payment becomes busy', async () => {
  const { wrapper, emit } = await open(async () => state({ status: 'downloading', required: true, decision: 'required', availableVersion: '0.5.2', percent: 40 }))
  expect(wrapper.findComponent(ElDialog).props('closeOnPressEscape')).toBe(false)
  expect(wrapper.findComponent(ElDialog).props('closeOnClickModal')).toBe(false)
  emit(state({ status: 'downloaded', decision: 'optional', availableVersion: '0.5.2' }))
  await flushPromises()
  expect(wrapper.findAllComponents(ElButton).find(button => button.text() === '重启安装')!.props('disabled')).toBe(false)
  emit(state({ status: 'downloaded', decision: 'optional', availableVersion: '0.5.2', businessBusyReason: '正在确认收款' }))
  await flushPromises()
  expect(wrapper.findAllComponents(ElButton).find(button => button.text() === '重启安装')!.props('disabled')).toBe(true)
  expect(wrapper.findComponent(ElDialog).props('modelValue')).toBe(false)
})

it('does not expose the local fallback dialog over an active business operation', async () => {
  const { wrapper, runtime } = await open(async () => { throw Error('offline') })
  runtime.businessBusyReason = '正在结账'
  await flushPromises()
  expect(wrapper.findComponent(ElDialog).props('modelValue')).toBe(false)
})

it('keeps offline history and close controls usable after a retry request fails', async () => {
  const { wrapper } = await open(async () => { throw Error('offline') })
  window.xiquan!.checkForUpdates = async () => { throw Error('offline') }
  const retry = wrapper.findAllComponents(ElButton).find(button => button.text() === '重新检查')!
  await retry.trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('检查更新失败，请稍后重试')
  expect(wrapper.get('.release-history').text()).toContain('0.4.7')
  expect(wrapper.get('.dialog-actions').text()).toContain('关闭')
})

it('protects a downloaded update while the local busy operation waits for its desktop acknowledgement', async () => {
  const { wrapper, runtime } = await open(async () => state({ status: 'downloaded', decision: 'optional', availableVersion: '0.5.2' }))
  let finish!: (value: UpdateState) => void
  window.xiquan!.setBusinessBusy = () => new Promise(resolve => { finish = resolve })
  const pending = runtime.setBusinessBusy('正在确认收款')
  await flushPromises()
  expect(wrapper.findComponent(ElDialog).props('modelValue')).toBe(false)
  expect(wrapper.findAllComponents(ElButton).find(button => button.text() === '重启安装')!.props('disabled')).toBe(true)
  finish(state({ status: 'downloaded', decision: 'optional', availableVersion: '0.5.2', businessBusyReason: '正在确认收款' }))
  await pending
})

it('does not overwrite a newer event with the delayed initial snapshot', async () => {
  let resolve!: (value: UpdateState) => void
  const { wrapper, emit } = await open(() => new Promise(done => { resolve = done }))
  emit(state({ status: 'downloading', message: '新版下载中 40%', percent: 40 }))
  resolve(state())
  await flushPromises()
  expect(wrapper.text()).toContain('新版下载中 40%')
})

it('applies the scroll cap and viewport limit to the real dialog while keeping the footer from shrinking', async () => {
  await open(undefined, false)
  // Compile the actual SFC styles so this catches selectors that miss the
  // teleported Element Plus dialog, rather than checking CSS source text.
  const compiledStyles = (source: string, element: Element) => {
    const id = element.getAttributeNames().find(name => name.startsWith('data-v-')) || ''
    return parse(source).descriptor.styles.map(style => compileStyle({
      source: style.content, filename: 'component.vue', id, scoped: Boolean(style.scoped),
    }).code).join('\n')
  }
  const css = document.createElement('style')
  const historyElement = document.querySelector('.release-history')!
  css.textContent = `${compiledStyles(historySource, historyElement)}\n${compiledStyles(dialogSource, document.querySelector('.dialog-actions')!)}`
  document.head.append(css)
  try {
    const history = getComputedStyle(historyElement)
    expect(history.maxHeight).toBe('min(40vh, 360px)')
    expect(history.overflowY).toBe('auto')
    expect(history.overscrollBehavior).toBe('contain')
    const dialog = getComputedStyle(document.querySelector('.update-center-dialog')!)
    expect(dialog.maxHeight).toBe('calc(100vh - 24px)')
    expect(dialog.display).toBe('flex')
    expect(getComputedStyle(document.querySelector('.el-dialog__footer')!).flexShrink).toBe('0')
  } finally { css.remove() }
})
