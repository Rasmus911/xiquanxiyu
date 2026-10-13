import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { http } from '../../api/http'
import { acceptBusinessState, clearBusinessSession } from '../../business/state'
import WristbandReaderPanel from './WristbandReaderPanel.vue'

const originalAdapter=http.defaults.adapter
afterEach(()=>{http.defaults.adapter=originalAdapter;clearBusinessSession();vi.restoreAllMocks()})
function scan(uid='000315346091', target:EventTarget=window) {
  for(const key of uid) target.dispatchEvent(new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true}))
  target.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}))
}
function state(open=true) {
  acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,
    owner_reset_allowed:false,ui_pages:['wristbands'],capabilities:{visit_open:open}},['visit:read','visit:write'])
}
it('opens a scanned band and refreshes without leaving the dashboard',async()=>{
  state(); const requests:any[]=[]
  http.defaults.adapter=async config=>{requests.push(JSON.parse(config.data));return {config,headers:{},status:200,statusText:'OK',
    data:{success:true,data:{opened:true,wristband_number:'001',visit_id:'visit-one',session:null,server_time:new Date().toISOString()}}}}
  const wrapper=mount(WristbandReaderPanel,{props:{enabled:true,paused:false},global:{plugins:[ElementPlus]}})
  try {
    scan();await flushPromises()
    expect(requests).toHaveLength(1);expect(requests[0].chip_uid).toBe('000315346091');expect(requests[0].link_mode).toBe(false)
    expect(requests[0].idempotency_key).toMatch(/^[0-9a-f-]{36}$/)
    expect(wrapper.emitted('changed')).toHaveLength(1);expect(wrapper.text()).toContain('001 号已开牌')
  }finally{wrapper.unmount()}
})
it('staff without opening capability, paused modal and editable targets never submit',async()=>{
  state(false);const adapter=vi.fn();http.defaults.adapter=adapter
  const wrapper=mount(WristbandReaderPanel,{attachTo:document.body,props:{enabled:true,paused:false},global:{plugins:[ElementPlus]}})
  const input=document.createElement('input');document.body.appendChild(input)
  try {
    scan();await flushPromises();expect(adapter).not.toHaveBeenCalled()
    state();await wrapper.setProps({paused:true});scan();await flushPromises();expect(adapter).not.toHaveBeenCalled()
    await wrapper.setProps({paused:false});input.focus();scan('000315346091',input);await flushPromises();expect(adapter).not.toHaveBeenCalled()
  }finally{input.remove();wrapper.unmount()}
})
it('rapid linked scans serialize and use the session returned by the prior response',async()=>{
  state();const bodies:any[]=[];const done:Array<(value:any)=>void>=[]
  http.defaults.adapter=config=>new Promise(resolve=>{bodies.push(JSON.parse(config.data));done.push(data=>resolve({config,headers:{},status:200,statusText:'OK',data:{success:true,data}}))})
  const wrapper=mount(WristbandReaderPanel,{props:{enabled:true,paused:false},global:{plugins:[ElementPlus]}})
  try{
    await wrapper.get('[data-testid="scan-link"]').setValue(true)
    scan('12345001');scan('12345051');await flushPromises();expect(bodies).toHaveLength(1)
    done[0]!({opened:true,wristband_number:'001',visit_id:'one',server_time:new Date().toISOString(),session:{id:'owned-session',numbers:['001'],expires_at:new Date(Date.now()+60000).toISOString()}})
    await flushPromises();expect(bodies).toHaveLength(2);expect(bodies[1].session_id).toBe('owned-session')
    done[1]!({opened:true,wristband_number:'051',visit_id:'two',server_time:new Date().toISOString(),session:{id:'owned-session',numbers:['001','051'],expires_at:new Date(Date.now()+60000).toISOString()}})
    await flushPromises();expect(wrapper.text()).toContain('001、051');expect(wrapper.text()).toContain('2 人')
    await wrapper.get('[data-testid="scan-link"]').setValue(false);expect(wrapper.text()).not.toContain('001、051')
  }finally{wrapper.unmount()}
})

it('retry after a lost response keeps the exact opening identity and body',async()=>{
  state();const requests:any[]=[];let fail=true
  http.defaults.adapter=async config=>{
    requests.push(JSON.parse(config.data))
    if(fail) throw new Error('response lost')
    return {config,headers:{},status:200,statusText:'OK',data:{success:true,data:{opened:true,
      wristband_number:'001',visit_id:'one',session:null,server_time:new Date().toISOString()}}}
  }
  const wrapper=mount(WristbandReaderPanel,{props:{enabled:true,paused:false},global:{plugins:[ElementPlus]}})
  try{
    scan();await flushPromises();expect(requests).toHaveLength(1)
    scan('12345051');await flushPromises();expect(requests).toHaveLength(1)
    fail=false
    await wrapper.findAll('button').find(button=>button.text()==='重试同一请求')!.trigger('click');await flushPromises()
    expect(requests).toHaveLength(2);expect(requests[1]).toEqual(requests[0]);expect(wrapper.emitted('changed')).toHaveLength(1)
  }finally{wrapper.unmount()}
})

it('leaving the component invalidates in-flight UI success and removes the listener',async()=>{
  state();let done!:(value:any)=>void;const requests:any[]=[]
  http.defaults.adapter=config=>new Promise(resolve=>{requests.push(JSON.parse(config.data));done=data=>resolve({config,headers:{},status:200,statusText:'OK',data:{success:true,data}})})
  const wrapper=mount(WristbandReaderPanel,{props:{enabled:true,paused:false},global:{plugins:[ElementPlus]}})
  scan();await flushPromises();wrapper.unmount();scan();expect(requests).toHaveLength(1)
  done({opened:true,wristband_number:'001',visit_id:'one',session:null,server_time:new Date().toISOString()})
  await flushPromises();expect(wrapper.emitted('changed')).toBeUndefined()
})

it('manual requery clears an unconfirmed request and accepts the next fresh scan',async()=>{
  state();let fail=true
  http.defaults.adapter=async config=>{
    if(fail) throw new Error('response lost')
    return {config,headers:{},status:200,statusText:'OK',data:{success:true,data:{opened:true,
      wristband_number:'051',visit_id:'fresh-visit',session:null,server_time:new Date().toISOString()}}}
  }
  const wrapper=mount(WristbandReaderPanel,{props:{enabled:true,paused:false},global:{plugins:[ElementPlus]}})
  try{
    scan();await flushPromises()
    expect(wrapper.text()).toContain('上次请求未确认')
    await wrapper.findAll('button').find(button=>button.text()==='重新查询后继续刷卡')!.trigger('click')
    expect(wrapper.text()).toContain('准备刷卡')
    expect(wrapper.text()).not.toContain('重试同一请求')
    fail=false;scan('12345051');await flushPromises()
    expect(wrapper.text()).toContain('051 号已开牌')
    expect(wrapper.emitted('changed')).toHaveLength(2)
  }finally{wrapper.unmount()}
})
