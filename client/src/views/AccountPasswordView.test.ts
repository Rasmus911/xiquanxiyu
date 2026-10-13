import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus, { ElMessage } from 'element-plus'
import AccountPasswordView from './AccountPasswordView.vue'
import { http } from '../api/http'
import { useAuthStore } from '../stores/auth'
import { getAccessToken, setAccessToken } from '../auth/session'
import { acceptBusinessState, clearBusinessSession } from '../business/state'

const originalAdapter = http.defaults.adapter
beforeEach(() => clearBusinessSession())
afterEach(() => { http.defaults.adapter = originalAdapter; ElMessage.closeAll(); clearBusinessSession(); vi.restoreAllMocks() })

async function setup() {
  const pinia = createPinia()
  useAuthStore(pinia).employee = { id:'fixture', username:'13800000001',
    display_name:'隔离员工', role:'male_scrubber', is_active:true } as any
  setAccessToken('fixture-access')
  acceptBusinessState({ period_id:'fixture', policy_version:1, business_revision:0,
    maintenance:false, owner_reset_allowed:false,
    ui_pages:['wristbands','account-password'], capabilities:{account_password_change:true} }, ['visit:order'])
  const router = createRouter({history:createMemoryHistory(), routes:[
    {path:'/account-password', component:AccountPasswordView},
    {path:'/login', component:{template:'<div>login</div>'}}]})
  await router.push('/account-password'); await router.isReady()
  const wrapper = mount(AccountPasswordView, {global:{plugins:[pinia, router, ElementPlus]}})
  return {wrapper,router}
}
async function fill(wrapper: any, confirm = 'new-fixture-password') {
  await wrapper.find('[data-testid="account-old-password"]').setValue('old-fixture-password')
  await wrapper.find('[data-testid="account-new-password"]').setValue('new-fixture-password')
  await wrapper.find('[data-testid="account-confirm-password"]').setValue(confirm)
}
it('mismatched passwords never submit to the server', async () => {
  const adapter = vi.fn()
  http.defaults.adapter = adapter
  const {wrapper} = await setup()
  try {
    await fill(wrapper,'different-password')
    await wrapper.find('[data-testid="account-password-submit"]').trigger('click'); await flushPromises()
    expect(adapter).not.toHaveBeenCalled()
    expect(document.body.textContent + wrapper.text()).toContain('两次新密码不一致')
  } finally { wrapper.unmount() }
})
it('changes only the current password and returns to login with no old token', async () => {
  const adapter = vi.fn(async (config: any) => ({config,headers:{},status:200,statusText:'OK',
    data:{success:true,data:{relogin_required:true}}}))
  http.defaults.adapter = adapter
  const {wrapper,router} = await setup()
  try {
    expect(wrapper.text()).toContain('13800000001')
    await fill(wrapper)
    await wrapper.find('[data-testid="account-password-submit"]').trigger('click'); await flushPromises()
    expect(adapter).toHaveBeenCalledTimes(1)
    expect(adapter.mock.calls[0]![0].url).toBe('/auth/change-password')
    expect(JSON.parse(adapter.mock.calls[0]![0].data)).toEqual({old_password:'old-fixture-password',
      new_password:'new-fixture-password',confirm_password:'new-fixture-password'})
    expect(getAccessToken()).toBe('')
    expect(router.currentRoute.value.path).toBe('/login')
  } finally { wrapper.unmount() }
})
it('a late password response cannot clear a newly logged-in account', async () => {
  let resolve!: (value: any) => void
  http.defaults.adapter = config => new Promise(done => { resolve = value => done({config,headers:{},
    status:200,statusText:'OK',data:value}) })
  const {wrapper,router} = await setup()
  try {
    await fill(wrapper)
    await wrapper.find('[data-testid="account-password-submit"]').trigger('click'); await flushPromises()
    clearBusinessSession(); setAccessToken('new-account-token')
    resolve({success:true,data:{relogin_required:true}}); await flushPromises()
    expect(getAccessToken()).toBe('new-account-token')
    expect(router.currentRoute.value.path).toBe('/account-password')
    expect(wrapper.find('[data-testid="account-old-password"]').element).toHaveProperty('value','')
  } finally { wrapper.unmount() }
})
