import { expect, test } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus, { ElMessage } from 'element-plus'
import { vi } from 'vitest'
import { AxiosError } from 'axios'
import Login from '../views/LoginView.vue'
import { http } from '../api/http'
test('desktop login clears password immediately and displays a credential denial', async () => {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/login', component: Login }, { path: '/', component: { template: '<div />' } }] })
  await router.push('/login')
  http.defaults.adapter = async config => { throw new AxiosError('denied', '', config, undefined, { config, headers: {}, status: 401, statusText: '', data: { success: false, message: '账号或密码错误', error: { code: 'INVALID_CREDENTIALS', details: {} } } }) }
  const wrapper = mount(Login, { global: { plugins: [createPinia(), router, ElementPlus] } })
  try {
    const inputs = wrapper.findAll('input')
    await inputs[0]!.setValue('owner'); await wrapper.find('input[type="password"]').setValue('secret')
    await wrapper.find('form').trigger('submit')
    expect((wrapper.find('input[type="password"]').element as HTMLInputElement).value).toBe('')
    await flushPromises()
    expect(document.body.textContent).toContain('账号或密码错误')
  } finally { wrapper.unmount(); ElMessage.closeAll() }
})
test('registration is Electron-only and keeps logged-out update and terminal/bootstrap actions',async()=>{
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/login',component:Login}]});await router.push('/login')
  for (const desktop of [false,true]) {
    vi.stubGlobal('xiquan',undefined)
    const original=window.xiquan
    if(desktop)window.xiquan={getConfig:async()=>({}),setBusinessBusy:async()=>({})} as any
    const wrapper=mount(Login,{global:{plugins:[createPinia(),router,ElementPlus],stubs:{teleport:true}}})
    try {
      await flushPromises();expect(wrapper.find('[data-testid="login-register"]').exists()).toBe(desktop);expect(wrapper.find('[data-testid="login-check-updates"]').exists()).toBe(desktop)
      expect(wrapper.text()).toContain('服务器与终端设置');expect(wrapper.text()).toContain('首次初始化管理员')
      if(desktop){await wrapper.find('[data-testid="login-register"]').trigger('click');await flushPromises();expect(wrapper.text()).toContain('注册员工账号')}
    }finally{wrapper.unmount();window.xiquan=original;vi.unstubAllGlobals()}
  }
})
