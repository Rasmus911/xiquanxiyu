import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import DesktopCompatibility from './DesktopCompatibility.vue'

vi.mock('element-plus', () => ({ ElMessage: { error: vi.fn() }, ElMessageBox: { confirm: vi.fn().mockResolvedValue(true) } }))
afterEach(() => { delete window.xiquan })
describe('desktop compatibility controls', () => {
  it('shows packaged identity and asks the main process before a rendering restart', async () => {
    const restart = vi.fn().mockResolvedValue({ ok: false, reason: '正在充值，完成后再重启' })
    window.xiquan = { getDesktopDiagnostics: vi.fn().mockResolvedValue({ targetId: 'win7-x86', appArch: 'ia32',
      electronVersion: '22.3.27', chromiumVersion: '108', nodeVersion: '16', osRelease: '6.1.7601', buildId: 'test-build',
      softwareRendering: false, testOnly: true }), restartWithSoftwareRendering: restart } as unknown as NonNullable<Window['xiquan']>
    const wrapper = mount(DesktopCompatibility)
    await flushPromises()
    expect(wrapper.text()).toContain('win7-x86')
    expect(wrapper.text()).toContain('兼容测试候选')
    await wrapper.get('button').trigger('click'); await flushPromises()
    expect(restart).toHaveBeenCalledWith(true)
    expect(wrapper.text()).toContain('正在充值')
    wrapper.unmount()
  })
  it('does not offer native controls to a browser or an older bridge', async () => {
    const wrapper = mount(DesktopCompatibility)
    await flushPromises()
    expect(wrapper.find('button').exists()).toBe(false)
    wrapper.unmount()
  })
})
