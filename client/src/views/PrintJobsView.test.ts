import {afterEach,beforeEach,expect,it} from 'vitest'
import {flushPromises,mount} from '@vue/test-utils'
import {createPinia} from 'pinia'
import ElementPlus,{ElMessage} from 'element-plus'
import PrintJobsView from './PrintJobsView.vue'
import {http} from '../api/http'
import {acceptBusinessState,clearBusinessSession} from '../business/state'
const original=http.defaults.adapter
beforeEach(()=>clearBusinessSession())
afterEach(()=>{http.defaults.adapter=original;ElMessage.closeAll();clearBusinessSession()})
async function render(service:boolean,settlement:boolean,adapter?:any){
 acceptBusinessState({period_id:'test',business_revision:0,policy_version:1,maintenance:false,owner_reset_allowed:false,
  ui_pages:['print-jobs'],capabilities:{service_receipt_reprint:service,settlement_receipt_reprint:settlement}},service&&settlement?['*']:[])
 http.defaults.adapter=adapter|| (async config=>({config,headers:{},status:200,statusText:'',data:{data:{
  items:[{id:'job',settlement_id:'settlement',settlement_number:'XS-TEST',wristband_number:'001',employee_name:'隔离员工',
   status:'success',attempts:1,created_at:'2026-10-11T01:00:00Z'}],total:1,page:1,page_size:10,
  server_time:'2026-10-11T01:00:00Z',expires_at:'2026-10-11T16:00:00Z'}}}))
 const wrapper=mount(PrintJobsView,{global:{plugins:[createPinia(),ElementPlus]}});await flushPromises();return wrapper
}
it.each([[true,false],[false,true],[true,true]])('shows only independently authorized receipt categories (%s,%s)',async(service,settlement)=>{
 const wrapper=await render(service,settlement)
 try {
  expect(wrapper.find('[data-testid="receipt-tab-order"]').exists()).toBe(service)
  expect(wrapper.find('[data-testid="receipt-tab-settlement"]').exists()).toBe(settlement)
  expect(wrapper.text()).toContain('已打印')
  expect(wrapper.find('[data-testid="receipt-reprint-job"]').exists()).toBe(true)
 }finally{wrapper.unmount()}
})
it('late service response never overwrites the selected settlement table',async()=>{
 let serviceFinish!:()=>void
 const wrapper=await render(true,true,(config:any)=>{
  const value={config,headers:{},status:200,statusText:'',data:{data:{items:[{id:'job',status:'success',
   settlement_number:'SETTLEMENT-ONLY',wristband_number:'ORDER-ONLY'}],total:1,
   server_time:'2026-10-11T01:00:00Z',expires_at:'2026-10-11T16:00:00Z'}}}
  return config.url==='/service-print-jobs'?new Promise(resolve=>{serviceFinish=()=>resolve(value)}):Promise.resolve(value)
 })
 try{
  await wrapper.get('[data-testid="receipt-tab-settlement"]').trigger('click');await flushPromises()
  serviceFinish();await flushPromises()
  expect(wrapper.text()).toContain('SETTLEMENT-ONLY');expect(wrapper.text()).not.toContain('ORDER-ONLY')
 }finally{wrapper.unmount()}
})
