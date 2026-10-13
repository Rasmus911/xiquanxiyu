import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { AxiosError } from 'axios'
import { useRuntimeStore } from '../stores/runtime'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus, { ElDialog, ElInputNumber, ElMessage } from 'element-plus'
import CheckoutView from './CheckoutView.vue'
import CardScanDialog from '../components/members/CardScanDialog.vue'
import { http } from '../api/http'
import { acceptBusinessState, clearBusinessSession } from '../business/state'

let requests: any[] = []
let finish!: () => void
let passDue = '10.00'
const member = { id:'m1',name:'会员甲',phone:'13800000246',balance:'100.00',is_active:true,
  holder_surname:null,card_binding:{ id:'c1',member_id:'m1',card_uid:'000315346091',is_active:true,created_at:'2026-10-12',revoked_at:null,replaced_by_id:null,version:1 },
  passes:[{ id:'p1',name:'洗浴次卡',remaining_count:5,valid_until:null,is_active:true }] }
beforeEach(() => {
  clearBusinessSession(); setActivePinia(createPinia())
  acceptBusinessState({ period_id:'test',policy_version:1,business_revision:0,maintenance:false,owner_reset_allowed:false }, ['*'])
  requests = []
  passDue = '10.00'
  http.defaults.adapter = async config => {
    const body = config.data ? JSON.parse(config.data) : undefined
    requests.push({ url:config.url,body })
    if (config.url === '/checkout') await new Promise<void>(resolve => { finish = resolve })
    const redemption = passDue === '0.00' ? '160.00' : '150.00'
    const data = config.url === '/checkout/preview' ? { visits:[{ visit_id:'v1',wristband_number:'001',amount:'160.00',version:1,party_id:'party1' }],total_amount:'160.00',amount_due:body.pass_use ? passDue : '160.00',pass_redemption_amount:body.pass_use ? redemption : '0.00',pass_redemption_count:body.pass_use ? 1 : 0,pass_redemptions:body.pass_use ? [{visit_id:'v1',order_item_id:'i1',member_pass_id:'p1',count:1,amount:redemption}] : [] }
      : config.url === '/members/lookup' ? member
      : config.url === '/checkout' ? { id:'s1',number:'TEST' } : {}
    return { config,headers:{},status:200,statusText:'',data:{ data } }
  }
})
afterEach(() => { vi.restoreAllMocks(); ElMessage.closeAll(); clearBusinessSession() })
async function view() {
  const router = createRouter({ history:createMemoryHistory(),routes:[
    { path:'/checkout',component:CheckoutView },{ path:'/print-jobs',component:{ template:'<div />' } },{ path:'/login',component:{ template:'<div>登录</div>' } },
  ] })
  await router.push('/checkout?visits=v1')
  const wrapper = mount({ template: '<router-view />' },{ global:{ plugins:[ElementPlus,router],stubs:{ teleport:true } } })
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

async function choosePass(wrapper: Awaited<ReturnType<typeof view>>) {
  await wrapper.find('input[maxlength="11"]').setValue('13800000246')
  await wrapper.findAll('button').find(node => node.text() === '查询会员')!.trigger('click'); await flushPromises()
  await wrapper.find('[data-testid="pass-select"]').setValue('p1')
  await wrapper.find('[data-testid="pass-visit-v1"] input').setValue(true); await flushPromises()
}
it.each(['10.00','0.00'])('uses authoritative pass amount_due %s and permits full redemption with no monetary payments', async due => {
  passDue = due
  const wrapper = await view()
  try {
    await choosePass(wrapper)
    expect(wrapper.findAllComponents(ElInputNumber)[0].props('modelValue')).toBe(Number(due))
    expect(wrapper.text()).toContain(due === '0.00' ? '160.00' : '150.00')
    await wrapper.findAll('button').find(node => node.text().includes('确认收款 ¥'))!.trigger('click'); await flushPromises()
    expect(requests.filter(row => row.url === '/checkout')[0].body).toMatchObject({
      member_id:'m1',pass_use:{ member_pass_id:'p1',visit_ids:['v1'] },
      member_verification:{ method:'phone',surname_confirmed:false },
      payments:due === '0.00' ? [] : [{ method:'cash',amount:'10.00',reference:'' }],
    })
    finish(); await flushPromises()
  } finally { wrapper.unmount() }
})
it('card Enter only identifies and a timed-out pass checkout retries the original body and key', async () => {
  const adapter=http.defaults.adapter as any
  let writes=0
  http.defaults.adapter=async config => {
    if(config.url === '/checkout') {
      requests.push({url:config.url,body:JSON.parse(config.data),key:config.headers['Idempotency-Key']})
      if(++writes === 1) throw new AxiosError('timeout','ECONNABORTED',config)
      return {config,headers:{},status:200,statusText:'',data:{data:{id:'s1',number:'TEST'}}}
    }
    return adapter(config)
  }
  const wrapper=await view()
  try {
    await wrapper.findAll('button').find(node => node.text() === '刷实体卡')!.trigger('click'); await flushPromises()
    const input=wrapper.find('input[name="card_uid"]')
    await input.setValue('000315346091'); await input.trigger('keydown',{key:'Enter'}); await flushPromises()
    expect(requests.filter(row => row.url === '/checkout')).toHaveLength(0)
    await wrapper.find('[data-testid="pass-select"]').setValue('p1')
    await wrapper.find('[data-testid="pass-visit-v1"] input').setValue(true); await flushPromises()
    await wrapper.findAll('button').find(node => node.text().includes('确认收款 ¥'))!.trigger('click'); await flushPromises()
    expect(wrapper.find('input[maxlength="11"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="pass-select"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.checkout-step fieldset').attributes('disabled')).toBeDefined()
    expect(useRuntimeStore().businessBusyReason).not.toBeNull()
    await wrapper.findAll('button').find(node => node.text() === '确认上次收款结果')!.trigger('click'); await flushPromises()
    const writesSent=requests.filter(row => row.url === '/checkout')
    expect(writesSent).toHaveLength(2)
    expect(writesSent[1]).toEqual(writesSent[0])
    expect(writesSent[0].body.member_verification).toEqual({method:'card',card_binding_id:'c1',surname_confirmed:false})
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

it('keeps a manually entered amount when pass preview changes and fills only the actual residual', async () => {
  const wrapper=await view()
  try {
    await wrapper.findAllComponents(ElInputNumber)[0].setValue(4)
    await choosePass(wrapper)
    expect(wrapper.findAllComponents(ElInputNumber)[0].props('modelValue')).toBe(4)
    expect(wrapper.text()).toContain('还需收款 ¥6.00')
    await wrapper.findAll('[data-testid="fill-payment"]')[2].trigger('click')
    expect(wrapper.findAllComponents(ElInputNumber)[2].props('modelValue')).toBe(6)
  } finally {wrapper.unmount()}
})
it('uses only available balance with another payment for the residual and rejects an excessive balance', async () => {
  const adapter=http.defaults.adapter as any
  http.defaults.adapter=async config=>{
    if(config.url==='/members/lookup') return {config,headers:{},status:200,statusText:'',data:{data:{...member,balance:'6.00'}}}
    return adapter(config)
  }
  const wrapper=await view()
  try {
    await choosePass(wrapper)
    await wrapper.findAll('[data-testid="fill-payment"]')[3].trigger('click')
    const amounts=wrapper.findAllComponents(ElInputNumber)
    expect(amounts[0].props('modelValue')).toBe(0); expect(amounts[3].props('modelValue')).toBe(6)
    await amounts[3].setValue(10)
    await wrapper.findAll('button').find(b=>b.text().includes('确认收款 ¥'))!.trigger('click'); await flushPromises()
    expect(requests.filter(r=>r.url==='/checkout')).toHaveLength(0)
    await amounts[3].setValue(6)
    await wrapper.findAll('[data-testid="fill-payment"]')[0].trigger('click')
    await wrapper.findAll('button').find(b=>b.text().includes('确认收款 ¥'))!.trigger('click'); await flushPromises()
    expect(requests.filter(r=>r.url==='/checkout')[0].body.payments).toEqual([{method:'cash',amount:'4.00',reference:''},{method:'balance',amount:'6.00',reference:''}])
    finish(); await flushPromises()
  } finally {wrapper.unmount()}
})
it('previews only the selected linked person for pass use and clears member benefits when checkout people change', async () => {
  const adapter=http.defaults.adapter as any
  const visits=[{visit_id:'v1',wristband_number:'001',amount:'25.00'},{visit_id:'v2',wristband_number:'002',amount:'15.00'}]
  http.defaults.adapter=async config=>{
    if(config.url==='/checkout/preview') {
      const body=JSON.parse(config.data); requests.push({url:config.url,body})
      const selected=body.checkout_scope==='party' ? visits : visits.filter(v=>body.visit_ids.includes(v.visit_id))
      return {config,headers:{},status:200,statusText:'',data:{data:{visits:selected,total_amount:selected.length===2?'40.00':'25.00',amount_due:body.pass_use?'25.00':selected.length===2?'40.00':'25.00',pass_redemption_amount:body.pass_use?'15.00':'0.00',pass_redemption_count:body.pass_use?1:0,pass_redemptions:body.pass_use?[{visit_id:'v2',order_item_id:'i2',member_pass_id:'p1',count:1,amount:'15.00'}]:[]}}}
    }
    return adapter(config)
  }
  const wrapper=await view()
  try {
    await wrapper.find('input[maxlength="11"]').setValue('13800000246')
    await wrapper.findAll('button').find(b=>b.text()==='查询会员')!.trigger('click'); await flushPromises()
    expect((wrapper.find('[data-testid="pass-select"]').element as HTMLSelectElement).value).toBe('')
    await wrapper.find('[data-testid="pass-select"]').setValue('p1')
    await wrapper.find('[data-testid="pass-visit-v2"] input').setValue(true); await flushPromises()
    expect(requests.filter(r=>r.url==='/checkout/preview').at(-1).body).toMatchObject({visit_ids:['v1','v2'],pass_use:{member_pass_id:'p1',visit_ids:['v2']}})
    expect(wrapper.text()).toContain('002 号门票抵扣 ¥15.00')
    expect(wrapper.findAllComponents(ElInputNumber)[0].props('modelValue')).toBe(25)
    await wrapper.findAll('.visit-selector > button')[1].trigger('click'); await flushPromises()
    expect(wrapper.text()).not.toContain('会员甲')
    expect(requests.filter(r=>r.url==='/checkout/preview').at(-1).body).toMatchObject({visit_ids:['v1'],member_id:null,pass_use:null,member_verification:null})
  } finally {wrapper.unmount()}
})
it.each(['lookup','preview'])('locks payment, visit changes, navigation and updater while %s is in flight', async phase=>{
  const wrapper=await view()
  const adapter=http.defaults.adapter as any
  let release!:()=>void
  http.defaults.adapter=async config=>{
    if(config.url === (phase==='lookup'?'/members/lookup':'/checkout/preview')) await new Promise<void>(resolve=>{release=resolve})
    return adapter(config)
  }
  try {
    await wrapper.find('input[maxlength="11"]').setValue('13800000246')
    await wrapper.findAll('button').find(b=>b.text()==='查询会员')!.trigger('click'); await flushPromises()
    expect(wrapper.findAllComponents(ElInputNumber).every(input=>input.props('disabled'))).toBe(true)
    expect(wrapper.find('.checkout-step fieldset').attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('button').find(b=>b.text().includes('确认收款 ¥'))!.attributes('disabled')).toBeDefined()
    expect(useRuntimeStore().businessBusyReason).not.toBeNull()
    await wrapper.vm.$router.push('/login'); await flushPromises()
    expect(wrapper.vm.$router.currentRoute.value.path).toBe('/checkout')
    release(); await flushPromises()
    expect(useRuntimeStore().businessBusyReason).toBeNull()
  } finally {wrapper.unmount()}
})
it.each(['logout','period'])('clears membership and drops a late preview after %s, allowing login navigation',async kind=>{
  const wrapper=await view()
  const adapter=http.defaults.adapter as any
  let release!:()=>void
  try {
    await choosePass(wrapper)
    http.defaults.adapter=async config=>{
      if(config.url==='/checkout/preview') {
        await new Promise<void>(resolve=>{release=resolve})
        const response=await adapter(config)
        if(kind==='period') response.headers={'x-business-period':'next-period'}
        return response
      }
      return adapter(config)
    }
    await wrapper.find('[data-testid="pass-visit-v1"] input').setValue(false); await flushPromises()
    if(kind==='logout') clearBusinessSession()
    release(); await flushPromises()
    expect(wrapper.text()).not.toContain('会员甲')
    expect(wrapper.findAll('button').find(b=>b.text().includes('确认收款 ¥'))!.attributes('disabled')).toBeDefined()
    await wrapper.vm.$router.push('/login'); await flushPromises()
    expect(wrapper.vm.$router.currentRoute.value.path).toBe('/login')
    expect(requests.filter(r=>r.url==='/checkout')).toHaveLength(0)
  } finally {wrapper.unmount()}
})

it('sends binding and explicit surname confirmation even for a no-phone balance-only card payment',async()=>{
  const adapter=http.defaults.adapter as any
  http.defaults.adapter=async config=>config.url==='/members/lookup'
    ? {config,headers:{},status:200,statusText:'',data:{data:{...member,phone:'',holder_surname:'陈',balance:'200.00'}}}
    : adapter(config)
  const wrapper=await view()
  try {
    await wrapper.findAll('button').find(b=>b.text()==='刷实体卡')!.trigger('click'); await flushPromises()
    await wrapper.find('input[name="card_uid"]').setValue('000315346091')
    await wrapper.find('input[name="card_uid"]').trigger('keydown',{key:'Enter'}); await flushPromises()
    expect(wrapper.text()).toContain('无手机号')
    expect(wrapper.findAll('button').find(b=>b.text().includes('确认收款 ¥'))!.attributes('disabled')).toBeDefined()
    await wrapper.find('[data-testid="surname-confirm"] input').setValue(true); await flushPromises()
    expect(requests.filter(r=>r.url==='/checkout/preview').at(-1).body).toMatchObject({member_id:'m1',pass_use:null,member_verification:{method:'card',card_binding_id:'c1',surname_confirmed:true}})
    await wrapper.findAll('[data-testid="fill-payment"]')[3].trigger('click')
    await wrapper.findAll('button').find(b=>b.text().includes('确认收款 ¥'))!.trigger('click'); await flushPromises()
    expect(requests.filter(r=>r.url==='/checkout')[0].body).toMatchObject({pass_use:null,member_verification:{method:'card',card_binding_id:'c1',surname_confirmed:true},payments:[{method:'balance',amount:'160.00',reference:''}]})
    finish(); await flushPromises()
  } finally {wrapper.unmount()}
})
it.each(['balance','pass'])('can collect a physical-card %s payment after the scanner closing animation',async method=>{
  const wrapper=await view()
  try {
    await wrapper.findAll('button').find(b=>b.text()==='刷实体卡')!.trigger('click'); await flushPromises()
    const scanner=wrapper.findComponent(CardScanDialog)
    const dialog=scanner.findComponent(ElDialog)
    await scanner.find('input[name="card_uid"]').setValue('000315346091')
    await scanner.find('input[name="card_uid"]').trigger('keydown',{key:'Enter'}); await flushPromises()
    // Finish the actual ElDialog afterLeave hook (CSS transitions are stubbed
    // by jsdom), including its delayed update:modelValue=false notification.
    dialog.findComponent({name:'transition'}).vm.$.vnode.props!.onAfterLeave()
    await flushPromises()
    expect(dialog.emitted('closed')).toHaveLength(1)
    expect(wrapper.text()).toContain('会员甲')
    expect(requests.filter(r=>r.url==='/checkout')).toHaveLength(0)
    if(method==='pass') {
      await wrapper.find('[data-testid="pass-select"]').setValue('p1')
      await wrapper.find('[data-testid="pass-visit-v1"] input').setValue(true); await flushPromises()
    } else {
      await wrapper.findAllComponents(ElInputNumber)[0].setValue(60)
      await wrapper.findAll('button').find(b=>b.text()==='使用可用余额')!.trigger('click'); await flushPromises()
    }
    await wrapper.findAll('button').find(b=>b.text().includes('确认收款 ¥'))!.trigger('click'); await flushPromises()
    const payments=requests.filter(r=>r.url==='/checkout')
    expect(payments).toHaveLength(1)
    expect(payments[0].body).toMatchObject({
      member_id:'m1',
      member_verification:{method:'card',card_binding_id:'c1',surname_confirmed:false},
      pass_use:method==='pass' ? {member_pass_id:'p1',visit_ids:['v1']} : null,
      payments:method==='pass' ? [{method:'cash',amount:'10.00',reference:''}]
        : [{method:'cash',amount:'60.00',reference:''},{method:'balance',amount:'100.00',reference:''}],
    })
    finish(); await flushPromises()
  } finally {wrapper.unmount()}
})
it.each(['ineligible ticket','revoked binding','missing amount_due'])('blocks collection when the server preview rejects %s without falling back to visit amounts',async reason=>{
  const wrapper=await view(), adapter=http.defaults.adapter as any
  http.defaults.adapter=async config=>{
    if(config.url==='/checkout/preview' && JSON.parse(config.data).pass_use) {
      if(reason==='missing amount_due') return {config,headers:{},status:200,statusText:'',data:{data:{visits:[{visit_id:'v1',wristband_number:'001',amount:'160.00'}],total_amount:'160.00'}}}
      throw new AxiosError(reason,'ERR_BAD_REQUEST',config,undefined,{config,headers:{},status:409,statusText:'',data:{message:reason}})
    }
    return adapter(config)
  }
  try {
    await choosePass(wrapper)
    const submit=wrapper.findAll('button').find(b=>b.text().includes('确认收款 ¥'))!
    expect(submit.attributes('disabled')).toBeDefined()
    await submit.trigger('click'); await flushPromises()
    expect(requests.filter(r=>r.url==='/checkout')).toHaveLength(0)
    expect(useRuntimeStore().businessBusyReason).toBeNull()
    await wrapper.find('[data-testid="pass-select"]').setValue(''); await flushPromises()
    expect(wrapper.findAllComponents(ElInputNumber)[0].props('modelValue')).toBe(160)
    expect(wrapper.findAll('button').find(b=>b.text().includes('确认收款 ¥'))!.attributes('disabled')).toBeUndefined()
  } finally {wrapper.unmount()}
})
