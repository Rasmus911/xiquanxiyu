import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { createRouter, createMemoryHistory } from 'vue-router'
import { http } from '../api/http'
import { acceptBusinessState, clearBusinessSession } from '../business/state'
import CatalogView from './CatalogView.vue'
import MembersView from './MembersView.vue'
import WristbandCard from '../components/wristbands/WristbandCard.vue'
import * as icons from '@element-plus/icons-vue'
import { createPinia } from 'pinia'
import LoginView from './LoginView.vue'
import DashboardView from './DashboardView.vue'
import { useRuntimeStore } from '../stores/runtime'

afterEach(() => { clearBusinessSession(); vi.restoreAllMocks(); delete window.xiquan; ElMessage.closeAll() })
it.each(['catalog', 'members'])('%s deletion sends own password, rejects without removing, then removes on success', async resource => {
  acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,owner_reset_allowed:false,capabilities:{catalog_write:true,catalog_delete:true,member_delete:true}}, ['catalog:read','catalog:write','catalog:delete','member:read','member:delete'])
  const row = {id:'one',name:'测试记录',phone:'13800000000',kind:'service',category:'洗浴',price:'20',is_active:true,can_edit:true,balance:'0',has_pass:false,has_stored_value:false}
  const writes:any[] = []; let reject = true
  http.defaults.adapter = async config => {
    if(config.method==='delete') { writes.push({url:config.url,body:JSON.parse(config.data)}); if(reject) throw {response:{data:{message:'存在未结账记录'}}} }
    return {config,headers:{},status:200,statusText:'',data:{data:[row]}}
  }
  vi.spyOn(ElMessageBox,'prompt').mockResolvedValue({value:'own-password',action:'confirm'} as any)
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{template:'<div />'}}]}); await router.push('/'); await router.isReady()
  const wrapper=mount(resource==='catalog'?CatalogView:MembersView,{global:{plugins:[ElementPlus,router]}})
  try {
    await flushPromises(); const button=`[data-testid="${resource==='catalog'?'catalog':'member'}-delete"]`
    await wrapper.get(button).trigger('click');await flushPromises()
    expect(writes).toEqual([{url:`/${resource}/one`,body:{password:'own-password'}}]);expect(wrapper.text()).toContain('测试记录')
    reject=false;await wrapper.get(button).trigger('click');await flushPromises();expect(wrapper.text()).not.toContain('测试记录')
  } finally {wrapper.unmount()}
})
it.each(['in_use','lost'])('renders a direct clear button for %s', status => {
  const wrapper=mount(WristbandCard,{props:{row:{id:'band',number:'001',status,visit_id:'visit',amount:'0'} as any,selected:false,batchActive:false,selectable:false,elapsed:'',canClear:true,canManage:true},global:{plugins:[ElementPlus],components:icons}})
  try {expect(wrapper.find('[data-testid="force-clear"]').exists()).toBe(true);expect(wrapper.text()).not.toContain('更多')}finally{wrapper.unmount()}
})
it.each(['catalog','members'])('%s duplicate prompts are blocked and session change aborts deletion', async resource => {
  acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,owner_reset_allowed:false,capabilities:{catalog_delete:true,member_delete:true}},['catalog:read','catalog:delete','member:read','member:delete'])
  let resolve!:(value:any)=>void;const prompt=vi.spyOn(ElMessageBox,'prompt').mockImplementation(()=>new Promise(done=>{resolve=done}))
  const writes:string[]=[]
  http.defaults.adapter=async config=>{if(config.method==='delete')writes.push(config.url!);return {config,headers:{},status:200,statusText:'',data:{data:[{id:'one',name:'记录',phone:'138',kind:'service',category:'服务',is_active:true,balance:'0'}]}}}
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{template:'<div />'}}]});await router.push('/');await router.isReady()
  const wrapper=mount(resource==='catalog'?CatalogView:MembersView,{global:{plugins:[ElementPlus,router]}})
  try {await flushPromises();const button=wrapper.get(`[data-testid="${resource==='catalog'?'catalog':'member'}-delete"]`);await button.trigger('click');await button.trigger('click');expect(prompt).toHaveBeenCalledTimes(1);clearBusinessSession();resolve({value:'old-password'});await flushPromises();expect(writes).toEqual([])}finally{wrapper.unmount()}
})
it('login checks updates through the desktop IPC before login and opens the existing center',async()=>{
  let resolve!:(value:UpdateState)=>void
  const check=vi.fn(()=>new Promise<UpdateState>(done=>{resolve=done}))
  window.xiquan={getConfig:async()=>({}),checkForUpdates:check,setBusinessBusy:async()=>({} as UpdateState)} as any
  const pinia=createPinia();const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{template:'<div />'}}]});await router.push('/');await router.isReady()
  const wrapper=mount(LoginView,{global:{plugins:[ElementPlus,pinia,router]}})
  try {await flushPromises();const button=wrapper.get('[data-testid="login-check-updates"]');await button.trigger('click');await button.trigger('click');expect(check).toHaveBeenCalledTimes(1);expect(useRuntimeStore(pinia).updateCenterVisible).toBe(true);resolve({status:'not-available',businessBusyReason:null} as UpdateState);await flushPromises();expect(useRuntimeStore(pinia).updateState?.status).toBe('not-available')}finally{wrapper.unmount()}
})
it('staff dashboard displays only in-use and lost bands with a live visit',async()=>{
  acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,owner_reset_allowed:false,capabilities:{visit_order:true}},['visit:read','visit:order'])
  const rows=[{id:'active',number:'001',status:'in_use',visit_id:'v1'},{id:'lost',number:'002',status:'lost',visit_id:'v2'},{id:'empty',number:'003',status:'available'},{id:'oldlost',number:'004',status:'lost'},{id:'disabled',number:'005',status:'disabled'}].map(row=>({...row,bath_area:'male',amount:'0',version:1}))
  const urls:string[]=[];http.defaults.adapter=async config=>{urls.push(config.url!);return {config,headers:{},status:200,statusText:'',data:{data:rows}}}
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{template:'<div />'}}]});await router.push('/');await router.isReady()
  const wrapper=mount(DashboardView,{global:{plugins:[ElementPlus,createPinia(),router],components:icons}})
  try {await flushPromises();expect(wrapper.findAllComponents(WristbandCard).map(card=>card.props('row').id)).toEqual(['active','lost']);expect(wrapper.text()).not.toContain('空闲');expect(wrapper.text()).not.toContain('批量操作');expect(wrapper.text()).not.toContain('强制清空');expect(urls).toEqual(['/wristbands'])}finally{wrapper.unmount()}
})
