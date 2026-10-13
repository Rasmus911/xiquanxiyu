// @vitest-environment jsdom
import { afterEach, expect, it } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { clearBusinessSession } from '../../business/state'
import { useSessionStore } from '../../stores/session'
import MobileBottomNav from './MobileBottomNav.vue'

let dispose = () => {}
afterEach(() => { dispose(); clearBusinessSession(); localStorage.clear() })

async function render(username: string, capability: boolean | undefined, authenticated = true) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const session = useSessionStore()
  session.authenticated = authenticated
  session.setEmployee({
    id: 'employee', username, display_name: '管理员', role: 'admin', role_label: '系统管理员',
    capabilities: { registration_token_view: capability },
  })
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/orders', name: 'orders', component: { template: '<p>手牌</p>' } },
    { path: '/registration-token', name: 'registration-token', component: { template: '<p>令牌页面</p>' } },
    { path: '/profile', name: 'profile', component: { template: '<p>我的</p>' } },
  ] })
  await router.push('/orders')
  await router.isReady()
  const root = document.createElement('div')
  document.body.append(root)
  const app = createApp({ render: () => h(MobileBottomNav) })
  app.use(pinia)
  app.use(router)
  app.mount(root)
  dispose = () => { app.unmount(); root.remove() }
  await nextTick()
  return { root, router, session }
}

it.each(['18631459666', '18603346509'])('shows the registration-token bottom link and opens its route for %s', async (username) => {
  const { root, router } = await render(username, true)
  const link = root.querySelector<HTMLAnchorElement>('a[href="/registration-token"]')
  expect(link).not.toBeNull()
  expect(link!.textContent).toContain('注册令牌')
  link!.click()
  await router.isReady()
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(router.currentRoute.value.name).toBe('registration-token')
  expect(link!.classList.contains('active')).toBe(true)
})

it.each([
  ['15133863898', true, true],
  ['于在跃', true, true],
  ['18631459666', false, true],
  ['18603346509', undefined, true],
  ['18631459666', true, false],
] as const)('hides the bottom entry for username=%s capability=%s authenticated=%s', async (username, capability, authenticated) => {
  const { root } = await render(username, capability, authenticated)
  expect(root.querySelector('a[href="/registration-token"]')).toBeNull()
})

it('removes the entry when authorization is revoked or the account changes', async () => {
  const { root, session } = await render('18631459666', true)
  expect(root.querySelector('a[href="/registration-token"]')).not.toBeNull()
  session.setEmployee({ ...session.employee!, capabilities: { registration_token_view: false } })
  await nextTick()
  expect(root.querySelector('a[href="/registration-token"]')).toBeNull()
  session.setEmployee({ ...session.employee!, username: '15133863898', capabilities: { registration_token_view: true } })
  await nextTick()
  expect(root.querySelector('a[href="/registration-token"]')).toBeNull()
})
