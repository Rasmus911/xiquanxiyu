// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import LoginView from './LoginView.vue'

afterEach(() => vi.restoreAllMocks())
it('retains a stable mobile form, inline errors and the in-app update event', async () => {
  const root=document.createElement('div');document.body.appendChild(root)
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/login',component:LoginView}]})
  await router.push('/login')
  const app=createApp(LoginView).use(createPinia()).use(router);app.mount(root)
  try {
    expect(root.querySelector('h1')?.textContent).toBe('平泉市溪泉洗浴')
    expect(root.querySelector('input[type=password]')?.getAttribute('autocomplete')).toBe('current-password')
    root.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles:true,cancelable:true }));await nextTick()
    expect(root.querySelector('[role=alert]')?.textContent).toBe('请输入账号和密码')
    const update=vi.fn();window.addEventListener('xiquan:check-update',update)
    try { (root.querySelector('.update-button') as HTMLButtonElement).click();expect(update).toHaveBeenCalledOnce() }
    finally { window.removeEventListener('xiquan:check-update',update) }
    expect(root.querySelector('.login-scene__form')?.getAttribute('style')).toBeNull()
  } finally { app.unmount();root.remove() }
})
