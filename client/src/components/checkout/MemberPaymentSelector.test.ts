import { afterEach, beforeEach, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElDialog } from 'element-plus'
import { AxiosError } from 'axios'
import MemberPaymentSelector from './MemberPaymentSelector.vue'
import CardScanDialog from '../members/CardScanDialog.vue'
import { http } from '../../api/http'
import { acceptBusinessState, clearBusinessSession } from '../../business/state'

const cardMember = { id:'m1',phone:'',holder_surname:'陈',balance:'8.00',is_active:true,
  card_binding:{id:'c1',member_id:'m1',card_uid:'000315346091',is_active:true,created_at:'2026-10-12',revoked_at:null,replaced_by_id:null,version:1},
  passes:[{id:'p1',name:'洗浴次卡',remaining_count:2,valid_until:null,is_active:true}] }
let params: unknown[] = [], cleanup=()=>{}
beforeEach(() => {
  clearBusinessSession()
  acceptBusinessState({period_id:'test',policy_version:1,business_revision:0,maintenance:false,owner_reset_allowed:false},['*'])
  params=[]
  http.defaults.adapter=async config => {
    params.push(config.params)
    return {config,headers:{},status:200,statusText:'',data:{data:cardMember}}
  }
})
afterEach(() => { cleanup(); clearBusinessSession(); document.body.innerHTML='' })
async function render() {
  const w=mount(MemberPaymentSelector,{props:{visits:[{visit_id:'v1',wristband_number:'001'},{visit_id:'v2',wristband_number:'002'}],resetToken:0},
    attachTo:document.body,
    global:{plugins:[ElementPlus],stubs:{teleport:true}}})
  cleanup=()=>w.unmount(); await flushPromises(); return w
}
async function scan(w: Awaited<ReturnType<typeof render>>) {
  await w.findAll('button').find(b=>b.text()==='刷实体卡')!.trigger('click'); await flushPromises()
  await w.find('input[name="card_uid"]').setValue('000315346091')
  await w.find('input[name="card_uid"]').trigger('keydown',{key:'Enter'}); await flushPromises()
}
function last(w: Awaited<ReturnType<typeof render>>) { return w.emitted('selection')!.at(-1)![0] as any }
it('keeps the scanned member and card verification after ElDialog finishes closing',async()=>{
  const w=await render()
  await w.findAll('button').find(b=>b.text()==='刷实体卡')!.trigger('click'); await flushPromises()
  const dialog=w.findComponent(CardScanDialog).findComponent(ElDialog)
  await w.find('input[name="card_uid"]').setValue('000315346091')
  await w.find('input[name="card_uid"]').trigger('keydown',{key:'Enter'}); await flushPromises()
  // jsdom stubs CSS transitions; run the real ElDialog lifecycle callback,
  // which emits update:modelValue=false even after a programmatic close.
  const transition=dialog.findComponent({name:'transition'})
  const afterLeave=transition.vm.$.vnode.props!.onAfterLeave
  expect(afterLeave).toBeTypeOf('function')
  afterLeave()
  await flushPromises()
  expect(dialog.emitted('closed')).toHaveLength(1)
  expect(last(w).member?.id).toBe('m1')
  expect(last(w).benefits.member_verification).toEqual({method:'card',card_binding_id:'c1',surname_confirmed:false})
  expect(w.text()).toContain('无手机号')
  await w.find('[data-testid="surname-confirm"] input').setValue(true)
  await w.find('[data-testid="pass-select"]').setValue('p1')
  await w.find('[data-testid="pass-visit-v1"] input').setValue(true)
  expect(last(w).benefits).toEqual({pass_use:{member_pass_id:'p1',visit_ids:['v1']},member_verification:{method:'card',card_binding_id:'c1',surname_confirmed:true}})
})
it('looks up exact card UID, safely shows no phone, defaults pass off and requires explicit surname confirmation',async()=>{
  const w=await render(); await scan(w)
  expect(params).toEqual([{card_uid:'000315346091'}])
  expect(w.text()).toContain('无手机号'); expect(w.text()).toContain('8.00')
  expect(last(w).benefits).toEqual({pass_use:null,member_verification:{method:'card',card_binding_id:'c1',surname_confirmed:false}})
  await w.find('[data-testid="surname-confirm"] input').setValue(true)
  await w.find('[data-testid="pass-select"]').setValue('p1')
  await w.find('[data-testid="pass-visit-v2"] input').setValue(true)
  expect(last(w).benefits).toEqual({pass_use:{member_pass_id:'p1',visit_ids:['v2']},member_verification:{method:'card',card_binding_id:'c1',surname_confirmed:true}})
  await w.findAll('button').find(b=>b.text()==='刷实体卡')!.trigger('click'); await flushPromises()
  await w.findAll('button').find(b=>b.text()==='取消')!.trigger('click'); await flushPromises()
  expect(last(w)).toEqual({member:null,benefits:{pass_use:null,member_verification:null}})
})
it.each(['unknown','revoked'])('does not keep a member after %s card lookup fails',async kind=>{
  const w=await render(); await scan(w)
  http.defaults.adapter=async config=>{throw new AxiosError(kind,'ERR_BAD_REQUEST',config,undefined,{config,status:404,statusText:'',headers:{},data:{message:'实体卡不存在或已撤销'}})}
  await scan(w)
  expect(last(w).member).toBeNull(); expect(w.text()).toContain('实体卡不存在或已撤销')
})
it.each(['reset','session'])('discards a lookup arriving after %s invalidation',async kind=>{
  let resolve!: (value:any)=>void
  http.defaults.adapter=config=>new Promise(done=>{resolve=value=>done({config,headers:{},status:200,statusText:'',data:{data:value}})})
  const w=await render(); await scan(w)
  if(kind==='reset') await w.setProps({resetToken:1})
  else clearBusinessSession()
  resolve(cardMember); await flushPromises()
  expect(last(w).member).toBeNull()
  expect(w.text()).not.toContain('余额 ¥8.00')
})
