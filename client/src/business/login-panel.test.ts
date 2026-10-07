import { expect, test } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus, { ElMessage } from 'element-plus'
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
