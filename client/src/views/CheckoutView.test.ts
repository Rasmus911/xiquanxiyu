import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { AxiosError } from 'axios'
import { useRuntimeStore } from '../stores/runtime'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus, { ElInputNumber, ElMessage } from 'element-plus'
import CheckoutView from './CheckoutView.vue'
import { http } from '../api/http'
import { acceptBusinessState, clearBusinessSession } from '../business/state'

let requests: any[] = []
let finish!: () => void
beforeEach(() => {
  clearBusinessSession(); setActivePinia(createPinia())
  acceptBusinessState({ period_id:'test',policy_version:1,business_revision:0,maintenance:false,owner_reset_allowed:false }, ['*'])
  requests = []
  http.defaults.adapter = async config => {
    const body = config.data ? JSON.parse(config.data) : undefined
    requests.push({ url:config.url,body })
    if (config.url === '/checkout') await new Promise<void>(resolve => { finish = resolve })
    const data = config.url === '/checkout/preview' ? { visits:[{ visit_id:'v1',wristband_number:'001',amount:'160.00' }],total_amount:'160.00' }
      : config.url === '/members/lookup' ? { id:'m1',name:'会员甲',phone:'13800000246',balance:'100.00' }
      : config.url === '/checkout' ? { id:'s1',number:'TEST' } : {}
    return { config,headers:{},status:200,statusText:'',data:{ data } }
  }
})
afterEach(() => { vi.restoreAllMocks(); ElMessage.closeAll(); clearBusinessSession() })
async function view() {
  const router = createRouter({ history:createMemoryHistory(),routes:[
    { path:'/checkout',component:CheckoutView },{ path:'/print-jobs',component:{ template:'<div />' } },
  ] })
  await router.push('/checkout?visits=v1')
  const wrapper = mount({ template: '<router-view />' },{ global:{ plugins:[ElementPlus,router] } })
  await flushPromises()
  return wrapper
}
it('submits 20 cash + 40 alipay + 100 balance once and no zero-payment rows', async () => {
  const wrapper = await view()
  try {
    const amounts = wrapper.findAllComponents(ElInputNumber)
    expect(amounts).toHaveLength(4)
    await amounts[0].setValue(20); await amounts[2].setValue(40)
    await wrapper.find('input[maxlength="11"]').setValue('13800000246')
    await wrapper.findAll('button').find(node => node.text() === '查询会员')!.trigger('click'); await flushPromises()
    await wrapper.findAll('button').find(node => node.text() === '使用可用余额')!.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('金额已平')
    const submit = wrapper.findAll('button').find(node => node.text().includes('确认收款 ¥'))!
    await submit.trigger('click'); await submit.trigger('click'); await flushPromises()
    const checkout = requests.filter(row => row.url === '/checkout')
    expect(checkout).toHaveLength(1)
    expect(checkout[0].body).toMatchObject({ member_id:'m1',visit_ids:['v1'],payments:[
      { method:'cash',amount:'20.00',reference:'' },{ method:'alipay',amount:'40.00',reference:'' },{ method:'balance',amount:'100.00',reference:'' },
    ] })
    finish(); await flushPromises()
  } finally { wrapper.unmount() }
})
it('changing member phone clears previously selected balance, preventing accidental use of a remembered card', async () => {
  const wrapper = await view()
  try {
    const phone = wrapper.find('input[maxlength="11"]')
    await phone.setValue('13800000246')
    await wrapper.findAll('button').find(node => node.text() === '查询会员')!.trigger('click'); await flushPromises()
    await wrapper.findAll('button').find(node => node.text() === '使用可用余额')!.trigger('click'); await flushPromises()
    expect(wrapper.findAllComponents(ElInputNumber)[3].props('modelValue')).toBe(100)
    await phone.setValue('13800000247'); await flushPromises()
    expect(wrapper.findAllComponents(ElInputNumber)[3].props('modelValue')).toBe(0)
    expect(wrapper.text()).not.toContain('会员甲')
  } finally { wrapper.unmount() }
})
it('an uncertain payment keeps amounts and updater locked, and retries the identical original request', async () => {
  const adapter=http.defaults.adapter as any
  let writes=0
  http.defaults.adapter=async config => {
    if(config.url === '/checkout') {
      requests.push({url:config.url,body:JSON.parse(config.data)})
      if(++writes === 1) throw new AxiosError('timeout','ECONNABORTED',config)
      return {config,headers:{},status:200,statusText:'',data:{data:{id:'s1',number:'TEST'}}}
    }
    return adapter(config)
  }
  const wrapper=await view()
  try {
    await wrapper.findAll('button').find(button => button.text().includes('确认收款 ¥'))!.trigger('click'); await flushPromises()
    expect(wrapper.findAllComponents(ElInputNumber).every(input => input.props('disabled'))).toBe(true)
    expect(useRuntimeStore().businessBusyReason).not.toBeNull()
    const retry=wrapper.findAll('button').find(button => button.text() === '确认上次收款结果')
    expect(retry).toBeDefined()
    await retry!.trigger('click'); await flushPromises()
    const checkout=requests.filter(request => request.url === '/checkout')
    expect(checkout).toHaveLength(2)
    expect(checkout[1].body).toEqual(checkout[0].body)
    expect(useRuntimeStore().businessBusyReason).toBeNull()
  } finally {wrapper.unmount()}
})
