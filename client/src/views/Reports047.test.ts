import { afterEach, beforeEach, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { createPinia } from 'pinia'
import ReportsView from './ReportsView.vue'
import { http } from '../api/http'
import { acceptBusinessState, clearBusinessSession } from '../business/state'

const summary={operating_revenue:'160.00',actual_cash_inflow:'60.00',member_recharge:'0.00',stored_value_recharge:'0.00',pass_card_sales:'0.00',stored_value_consumed:'100.00',settlement_count:1,cashflow_totals:{cash:'20.00',alipay:'40.00'}}
let calls:any[]
beforeEach(()=>{
  calls=[];clearBusinessSession()
  acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,
    owner_reset_allowed:false,capabilities:{}},['report:read'])
  http.defaults.adapter=async config=>{
    calls.push({url:config.url,params:config.params})
    const data=config.url==='/reports/summary'?summary:config.url==='/reports/insights'?{
      current:summary,previous:{...summary,operating_revenue:'100.00'},visit_count:2,average_visit_revenue:'80.00',
      member_visit_count:1,nonmember_visit_count:1,member_visit_share:50,
      hours:Array.from({length:24},(_,hour)=>({hour,visits:hour===10?2:0,gross_amount:hour===10?'160.00':'0.00'})),
      purchase_cost:{recorded_amount:'480.00',unpriced_receipts:1,receipt_count:2},
    }:config.url==='/reports/items'?[{kind:'package',name:'套票A',quantity:'2',amount:'90.00'},{kind:'service',name:'按摩',quantity:'1',amount:'70.00'}]:[{date:'2026-10-07',revenue:'160.00',recharge:'0.00',cash_inflow:'60.00',settlement_count:1}]
    return {config,headers:{},status:200,statusText:'',data:{data}}
  }
})
afterEach(()=>{clearBusinessSession();ElMessage.closeAll()})
it('shows per-visit average, comparable growth, member denominator and separate unpriced costs',async()=>{
  const wrapper=mount(ReportsView,{global:{plugins:[ElementPlus,createPinia()]}})
  try {
    await flushPromises()
    expect(wrapper.get('[data-testid="visit-count"]').text()).toContain('2')
    expect(wrapper.get('[data-testid="visit-average"]').text()).toContain('80.00')
    expect(wrapper.get('[data-testid="revenue-comparison"]').text()).toContain('+60.0%')
    expect(wrapper.text()).toContain('50.0%')
    expect(wrapper.get('[data-testid="purchase-cost"]').text()).toContain('480.00')
    expect(wrapper.get('[data-testid="purchase-cost"]').text()).toContain('1笔未设置')
    expect(wrapper.find('svg[aria-label="已结账手牌入场时段"]').exists()).toBe(true)
  }finally{wrapper.unmount()}
})
it('period selection refreshes all dimensions using the same explicit timezone window',async()=>{
  const wrapper=mount(ReportsView,{global:{plugins:[ElementPlus,createPinia()]}})
  try {
    await flushPromises();calls=[]
    await wrapper.get('[data-testid="report-period-1"]').trigger('click');await flushPromises()
    expect(calls.map(row=>row.url).sort()).toEqual(['/reports/insights','/reports/items','/reports/summary','/reports/trend'])
    expect(calls.every(row=>row.params.start===calls[0].params.start&&row.params.end===calls[0].params.end)).toBe(true)
    expect(calls[0].params.start).toMatch(/Z$/)
  }finally{wrapper.unmount()}
})
