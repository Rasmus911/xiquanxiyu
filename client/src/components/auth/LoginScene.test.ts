import { afterEach, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import LoginScene from './LoginScene.vue'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
function media(reduced = false) {
  vi.stubGlobal('matchMedia', vi.fn((query: string) => ({ matches: query.includes('reduce') ? reduced : true,
    addEventListener: vi.fn(), removeEventListener: vi.fn() })))
  vi.stubGlobal('requestAnimationFrame', (fn: FrameRequestCallback) => { fn(0); return 1 })
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
}
it('moves only the decorative backdrop while keeping the slotted form stable', async () => {
  media()
  const wrapper = mount(LoginScene, { slots: { default: '<input aria-label="账号" /><button>登录</button>' } })
  try {
    Object.defineProperty(wrapper.element, 'getBoundingClientRect', { value: () => ({ left: 0, top: 0, width: 1000, height: 800 }) })
    await wrapper.trigger('pointermove', { clientX: 800, clientY: 400, pointerType: 'mouse' })
    await nextTick()
    expect(wrapper.attributes('style')).toContain('--pointer-x: 80%')
    expect(wrapper.attributes('data-motion')).toBe('active')
    expect(wrapper.get('.login-scene__form').attributes('style')).toBeUndefined()
    expect(wrapper.get('input').attributes('aria-label')).toBe('账号')
    await wrapper.trigger('pointerleave')
    expect(wrapper.attributes('data-pointer')).toBe('off')
  } finally { wrapper.unmount() }
})
it('uses a static background for reduced motion and ignores mouse movement', async () => {
  media(true)
  const wrapper = mount(LoginScene)
  try {
    await wrapper.trigger('pointermove', { clientX: 800, clientY: 400, pointerType: 'mouse' })
    expect(wrapper.attributes('data-motion')).toBe('static')
    expect(wrapper.attributes('data-pointer')).toBe('off')
    expect(wrapper.attributes('style')).not.toContain('--pointer-x: 80%')
  } finally { wrapper.unmount() }
})
it('pauses motion when hidden and removes the visibility listener on unmount', async () => {
  media()
  const remove = vi.spyOn(document, 'removeEventListener')
  const wrapper = mount(LoginScene)
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => true })
  document.dispatchEvent(new Event('visibilitychange')); await nextTick()
  expect(wrapper.attributes('data-motion')).toBe('static')
  wrapper.unmount()
  expect(remove).toHaveBeenCalledWith('visibilitychange', expect.any(Function))
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })
})
