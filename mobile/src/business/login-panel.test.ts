// @vitest-environment jsdom
import { afterEach, expect, test } from 'vitest'
import { createApp, nextTick, type App } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { AxiosError } from 'axios'
import Login from '../views/LoginView.vue'
import { http } from '../api'
import { clearBusinessSession } from './state'
import { useSessionStore } from '../stores/session'
let app: App; let host: HTMLDivElement
afterEach(() => { app.unmount(); host.remove() })
test('mobile login offers an update check before entering credentials', async () => {
  const pinia = createPinia(); setActivePinia(pinia); clearBusinessSession()
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/login', component: Login }] })
  await router.push('/login')
  app = createApp(Login); app.use(pinia); app.use(router); host = document.createElement('div'); document.body.append(host); app.mount(host)
  let checks = 0
  const listener = () => { checks++ }
  window.addEventListener('xiquan:check-update', listener)
  try {
    const button = [...host.querySelectorAll('button')].find(button => button.textContent === '检查应用更新')
    expect(button).toBeDefined()
    button!.click(); await nextTick()
    expect(checks).toBe(1)
    expect(useSessionStore().authenticated).toBe(false)
  } finally { window.removeEventListener('xiquan:check-update', listener) }
})
test('mobile login clears password immediately and displays a real credential denial', async () => {
  const pinia = createPinia(); setActivePinia(pinia); clearBusinessSession()
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/login', component: Login }, { path: '/orders', component: { template: '<div />' } }] })
  await router.push('/login')
  http.defaults.adapter = async config => {
    if (config.url === '/auth/login') throw new AxiosError('denied', '', config, undefined, { config, headers: {}, status: 401, statusText: '', data: { success: false, message: '账号或密码错误', error: { code: 'INVALID_CREDENTIALS', details: {} } } })
    return { config, headers: {}, status: 200, statusText: '', data: { data: {} } }
  }
  app = createApp(Login); app.use(pinia); app.use(router); host = document.createElement('div'); document.body.append(host); app.mount(host)
  const inputs = host.querySelectorAll('input')
  inputs[0]!.value = 'worker'; inputs[0]!.dispatchEvent(new Event('input'))
  inputs[1]!.value = 'secret'; inputs[1]!.dispatchEvent(new Event('input')); await nextTick()
  ;(host.querySelector('.primary-button') as HTMLButtonElement).click(); await nextTick()
  expect(inputs[1]!.value).toBe('')
  await new Promise(resolve => setTimeout(resolve, 0)); await nextTick()
  expect(host.textContent).toContain('账号或密码错误')
})
test('a rejected old bootstrap cannot display errors or finalize a replacement login', async () => {
  const pinia = createPinia(); setActivePinia(pinia); clearBusinessSession()
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/login', component: Login }, { path: '/orders', component: { template: '<div />' } }] })
  await router.push('/login')
  let reject!: (cause: Error) => void
  http.defaults.adapter = config => {
    if (config.url === '/mobile/bootstrap') return new Promise((_resolve, fail) => { reject = fail })
    return Promise.resolve({ config, headers: {}, status: 200, statusText: '', data: { data: config.url === '/auth/login' ? {
      access_token: 'access', refresh_token: 'refresh', employee: { id: 'e1', username: 'worker', display_name: '员工', role: 'male_scrubber', role_label: '搓澡师', capabilities: { order_all: true } }, business_state: { period_id: 'p1', business_revision: 1, policy_version: 1, maintenance: false, owner_reset_allowed: false }, permissions: ['mobile:order'],
    } : {} } })
  }
  app = createApp(Login); app.use(pinia); app.use(router); host = document.createElement('div'); document.body.append(host); app.mount(host)
  const inputs = host.querySelectorAll('input')
  inputs[0]!.value = 'worker'; inputs[0]!.dispatchEvent(new Event('input'))
  inputs[1]!.value = 'secret'; inputs[1]!.dispatchEvent(new Event('input')); await nextTick()
  ;(host.querySelector('.primary-button') as HTMLButtonElement).click()
  await new Promise(resolve => setTimeout(resolve, 0))
  await useSessionStore().login('new-worker', 'new-secret')
  reject(new Error('old network failure'))
  await new Promise(resolve => setTimeout(resolve, 0)); await nextTick()
  expect(host.textContent).not.toContain('old network failure')
  expect((host.querySelector('.primary-button') as HTMLButtonElement).disabled).toBe(true)
})
test('a current bootstrap period denial still displays its Chinese failure after cleanup', async () => {
  const pinia = createPinia(); setActivePinia(pinia); clearBusinessSession()
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/login', component: Login }] })
  await router.push('/login')
  http.defaults.adapter = async config => {
    if (config.url === '/mobile/bootstrap') throw new AxiosError('denied', '', config, undefined, { config, headers: {}, status: 409, statusText: '', data: { success: false, message: '经营期已变化，请重新登录', error: { code: 'BUSINESS_PERIOD_CHANGED', details: {} } } })
    return { config, headers: {}, status: 200, statusText: '', data: { data: config.url === '/auth/login' ? {
      access_token: 'access', refresh_token: 'refresh', employee: { id: 'e1', username: 'worker', display_name: '员工', role: 'male_scrubber', role_label: '搓澡师', capabilities: { order_all: true } }, business_state: { period_id: 'p1', business_revision: 1, policy_version: 1, maintenance: false, owner_reset_allowed: false }, permissions: ['mobile:order'],
    } : {} } }
  }
  app = createApp(Login); app.use(pinia); app.use(router); host = document.createElement('div'); document.body.append(host); app.mount(host)
  const inputs = host.querySelectorAll('input')
  inputs[0]!.value = 'worker'; inputs[0]!.dispatchEvent(new Event('input'))
  inputs[1]!.value = 'secret'; inputs[1]!.dispatchEvent(new Event('input')); await nextTick()
  ;(host.querySelector('.primary-button') as HTMLButtonElement).click()
  await new Promise(resolve => setTimeout(resolve, 0)); await nextTick()
  expect(host.textContent).toContain('经营期已变化，请重新登录')
  expect((host.querySelector('.primary-button') as HTMLButtonElement).disabled).toBe(false)
})
