import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia } from 'pinia'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import {useRuntimeStore} from '../stores/runtime'
import VisitView from './VisitView.vue'
import { http } from '../api/http'
import { acceptBusinessState, businessState, clearBusinessSession } from '../business/state'
import { dispatchRealtimeChange } from '../realtime/events'
import { useConnectivityStore } from '../stores/connectivity'
import type { Visit } from '../types'

const visits = ['a', 'b', 'c'].map((id, index) => ({ id, version: index + 3, wristband_number: String(index + 1).padStart(3, '0'),
  wristband_id: id, status: 'open', opened_at: '2026-10-04T10:00:00Z', total_amount: '15.00', items: [] })) as Visit[]
const product = { id: 'soap', kind: 'product', category: '洗浴', name: '搓泥宝', price: '10.00', is_active: true,
  stock_tracked: true, stock_quantity: '10', sort_order: 10, low_stock_threshold: '1' }
const tickets = ['adult','child'].map((id,index) => ({ id,kind:'ticket',reference_code:`ticket.${id}`,
  name:index ? '儿童门票（一米以下）' : '门票',price:index ? '10.00' : '15.00',is_active:true }))
let finish: Map<string, () => void>
let posts: any[]
beforeEach(() => {
  clearBusinessSession()
  acceptBusinessState({ period_id: 'fixture', policy_version: 1, business_revision: 0, maintenance: false,
    owner_reset_allowed: false, capabilities: { visit_order: true }, ui_pages: ['wristbands'] }, ['visit:order'])
  finish = new Map(); posts = []
  http.defaults.adapter = config => {
    const response = (data: unknown) => ({ config, headers: {}, status: 200, statusText: '', data: { data } })
    if (config.method === 'post') { posts.push({ url: config.url, body: JSON.parse(config.data) }); return Promise.resolve(response([])) }
    if (config.method === 'patch') { posts.push({url:config.url,body:JSON.parse(config.data)}); return Promise.resolve(response(visits[0])) }
    if (config.url === '/catalog') return Promise.resolve(response([product,...tickets]))
    if (config.url === '/inventory/consumables') return Promise.resolve(response([{id:'s1',name:'奶浴袋',category:'耗材',base_unit:'袋',package_spec:'1*200',stock_quantity:'0.000',version:1}]))
    const id = String(config.url).split('/').at(-1)
    return new Promise(resolve => finish.set(id!, () => resolve(response({ ...visits.find(row => row.id === id), linked_visits: visits }))))
  }
})
afterEach(() => { clearBusinessSession(); ElMessage.closeAll(); delete window.xiquan; vi.restoreAllMocks() })
async function render() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/visits/:id', component: VisitView }] })
  await router.push('/visits/a'); await router.isReady()
  const pinia = createPinia()
  const wrapper = mount(VisitView, { global: { plugins: [pinia, router, ElementPlus] } })
  useConnectivityStore().setRealtimeStatus('connected')
  await flushPromises()
  return { wrapper, router }
}
it('0.5.5 submits directly without a consumable choice and ignores zero stock',async()=>{
 const {wrapper}=await render()
 try{
  finish.get('a')!();await flushPromises()
  wrapper.findComponent({name:'CatalogPicker'}).vm.$emit('select',product);await flushPromises()
  await wrapper.get('[data-testid="submit-order"]').trigger('click');await flushPromises()
  expect(posts).toHaveLength(1)
  expect(posts[0]).toMatchObject({url:'/visits/a/items/batch',body:{items:[{catalog_item_id:'soap',quantity:1,inventory_mode:'manual',inventory_consumption:[]}]}})
  expect(wrapper.find('[data-testid="order-materials-dialog"]').exists()).toBe(false)
 }finally{wrapper.unmount()}
})
it('clearing a selection before submit cannot create an order',async()=>{
 const {wrapper}=await render()
 try{finish.get('a')!();await flushPromises();const picker=wrapper.findComponent({name:'CatalogPicker'});picker.vm.$emit('quantity',product,2);await flushPromises();picker.vm.$emit('quantity',product,0);await flushPromises();await wrapper.get('[data-testid="submit-order"]').trigger('click');await flushPromises();expect(posts).toEqual([])}finally{wrapper.unmount()}
})
it('a successful staff batch prints once and USB failure never submits the order again',async()=>{
 const previous = http.defaults.adapter as any
 const print = vi.fn(async () => ({success:false,error:'USB offline'}))
 window.xiquan = {printReceipt:print,setBusinessBusy:vi.fn(async () => ({}))} as any
 http.defaults.adapter = async config => {
  if(config.url==='/visits/a/items/batch') {
   posts.push({url:config.url,body:JSON.parse(config.data)})
   return {config,headers:{},status:201,statusText:'',data:{data:[],meta:{service_print_job:{id:'job',kind:'order',created_at:'2026-10-11T01:00:00Z',expires_at:'2026-10-11T16:00:00Z'}}}}
  }
  if(String(config.url).startsWith('/service-print-jobs/')) {
   posts.push({url:config.url,body:JSON.parse(config.data)})
   return {config,headers:{},status:201,statusText:'',data:{data:{id:'attempt',print_allowed:true,receipt:{receipt_kind:'order',wristband_number:'001'}}}}
  }
  return previous(config)
 }
 const {wrapper}=await render()
 try {
  finish.get('a')!();await flushPromises()
  wrapper.findComponent({name:'CatalogPicker'}).vm.$emit('select',product);await flushPromises()
  await wrapper.get('[data-testid="submit-order"]').trigger('click');await flushPromises()
  finish.get('a')!();await flushPromises()
  expect(print).toHaveBeenCalledTimes(1)
  expect(posts.filter(row=>row.url==='/visits/a/items/batch')).toHaveLength(1)
  expect(posts.at(-1)).toMatchObject({url:'/service-print-jobs/job/attempts/attempt/result',body:{success:false,error:'USB offline'}})
  expect(useRuntimeStore().businessBusyReason).toBeNull()
 } finally {wrapper.unmount()}
})
it.each([{period_id:'next-period'},{policy_version:2},{maintenance:true},{capabilities:{visit_order:false}}])('security change %j prevents a subsequent order',async(change)=>{
 const {wrapper}=await render()
 try{finish.get('a')!();await flushPromises();wrapper.findComponent({name:'CatalogPicker'}).vm.$emit('select',product);await flushPromises();acceptBusinessState({...businessState.value!,...change});await flushPromises();await wrapper.get('[data-testid="submit-order"]').trigger('click');await flushPromises();expect(posts).toEqual([])}finally{wrapper.unmount()}
})
it('session invalidation drops the sales draft without sending it',async()=>{
 const {wrapper}=await render()
 try{finish.get('a')!();await flushPromises();wrapper.findComponent({name:'CatalogPicker'}).vm.$emit('select',product);await flushPromises();clearBusinessSession();await flushPromises();await wrapper.get('[data-testid="submit-order"]').trigger('click');await flushPromises();expect(posts).toEqual([]);expect(wrapper.findComponent({name:'ConsumptionEditor'}).exists()).toBe(false)}finally{wrapper.unmount()}
})
it('waits for one package replacement decision and revokes it if the target changes',async()=>{
 acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,owner_reset_allowed:false,capabilities:{visit_order:true,package_write:true}},['visit:order','visit:package'])
 let resolve!:(value:any)=>void
 const confirm=vi.spyOn(ElMessageBox,'confirm').mockImplementation(()=>new Promise(done=>{resolve=done}))
 const replacement={...product,id:'package-new',kind:'package',name:'新套票'}
 const previous=http.defaults.adapter as any
 http.defaults.adapter=config=>config.url==='/catalog'?Promise.resolve({config,headers:{},status:200,statusText:'',data:{data:[replacement]}}):config.url==='/visits/a'?Promise.resolve({config,headers:{},status:200,statusText:'',data:{data:{...visits[0],items:[{id:'old',kind:'package',catalog_item_id:'package-old',status:'active'}]}}}):previous(config)
 const {wrapper,router}=await render()
 try{
  wrapper.findComponent({name:'CatalogPicker'}).vm.$emit('select',replacement);await flushPromises()
  await wrapper.get('[data-testid="submit-order"]').trigger('click');await flushPromises()
  expect(confirm).toHaveBeenCalledTimes(1)
  await router.push('/visits/b');await flushPromises();resolve('confirm');await flushPromises()
  expect(posts).toEqual([])
 }finally{wrapper.unmount()}
})
it('A → B → C stays on C when responses finish C, B, A', async () => {
  const { wrapper, router } = await render()
  try {
    await router.push('/visits/b'); await flushPromises()
    await router.push('/visits/c'); await flushPromises()
    expect(finish.has('b')).toBe(true)
    finish.get('c')!(); await flushPromises()
    finish.get('b')!(); await flushPromises()
    finish.get('a')!(); await flushPromises()
    expect(wrapper.text()).toContain('003 号手牌')
    expect(wrapper.find('.party-tabs button.active').text()).toContain('003')
  } finally { wrapper.unmount() }
})
it('a delayed desktop busy handshake cannot redirect A submission into B', async () => {
  const { wrapper, router } = await render()
  try {
    finish.get('a')!(); await flushPromises()
    // Default mixed mode; use the picker event to exercise the real selection handlers.
    const picker = wrapper.findComponent({ name: 'CatalogPicker' })
    picker.vm.$emit('select', product); picker.vm.$emit('select', product); await flushPromises()
    let release!: () => void
    window.xiquan = { setBusinessBusy: vi.fn(reason => reason ? new Promise(resolve => { release = () => resolve({ businessBusyReason: reason } as any) }) : Promise.resolve({} as any)) } as any
    await wrapper.get('[data-testid="submit-order"]').trigger('click')
    await flushPromises()
    await router.push('/visits/b'); await flushPromises()
    release(); await flushPromises()
    expect(posts[0]).toMatchObject({ url: '/visits/a/items/batch', body: { version: 3, items: [{ catalog_item_id: 'soap', quantity: 2 }] } })
    finish.get('b')!(); await flushPromises()
    picker.vm.$emit('select', product); await flushPromises()
    await router.push('/visits/a'); await flushPromises(); finish.get('a')!(); await flushPromises()
    expect(wrapper.findComponent({ name: 'CatalogPicker' }).props('quantities')).toEqual({})
    await router.push('/visits/b'); await flushPromises(); finish.get('b')!(); await flushPromises()
    expect(wrapper.findComponent({ name: 'CatalogPicker' }).props('quantities')).toEqual({ soap: 1 })
  } finally { wrapper.unmount() }
})

it('linked targets retain distinct drafts and new orders submit no stock deductions',async()=>{
 const {wrapper}=await render()
 try{finish.get('a')!();await flushPromises();wrapper.findComponent({name:'CatalogPicker'}).vm.$emit('quantity',product,2);await flushPromises();wrapper.findComponent({name:'PartyTabs'}).vm.$emit('select','b');await flushPromises();finish.get('b')!();await flushPromises();expect(wrapper.findComponent({name:'CatalogPicker'}).props('quantities')).toEqual({});wrapper.findComponent({name:'CatalogPicker'}).vm.$emit('quantity',product,3);await flushPromises();await wrapper.get('[data-testid="submit-order"]').trigger('click');await flushPromises();expect(posts[0]).toMatchObject({url:'/visits/b/items/batch',body:{items:[{catalog_item_id:'soap',quantity:3,inventory_mode:'manual',inventory_consumption:[]}]}})}finally{wrapper.unmount()}
})
it('the latest selected sale quantity is submitted without ever fetching consumables',async()=>{
 const paths:string[]=[];const previous=http.defaults.adapter as any;http.defaults.adapter=config=>{paths.push(String(config.url));return previous(config)}
 const {wrapper}=await render()
 try{finish.get('a')!();await flushPromises();const picker=wrapper.findComponent({name:'CatalogPicker'});picker.vm.$emit('quantity',product,2);picker.vm.$emit('quantity',product,3);await flushPromises();await wrapper.get('[data-testid="submit-order"]').trigger('click');await flushPromises();expect(posts[0].body.items).toEqual([{catalog_item_id:'soap',quantity:3,inventory_mode:'manual',inventory_consumption:[]}]);expect(paths).not.toContain('/inventory/consumables')}finally{wrapper.unmount()}
})
it('quick-order submit is in the header and disabled without selection or connectivity', async () => {
  const { wrapper } = await render()
  try {
    finish.get('a')!(); await flushPromises()
    const button = wrapper.find('[data-testid="quick-order-header"] [data-testid="submit-order"]')
    expect(button.exists()).toBe(true)
    expect(button.attributes('disabled')).toBeDefined()
    wrapper.findComponent({ name: 'CatalogPicker' }).vm.$emit('select', product); await flushPromises()
    expect(button.attributes('disabled')).toBeUndefined()
    useConnectivityStore().setRealtimeStatus('disconnected'); await flushPromises()
    expect(button.attributes('disabled')).toBeDefined()
  } finally { wrapper.unmount() }
})

it('read-only visit does not request order-only consumables or block the catalog',async()=>{
 acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,owner_reset_allowed:false,capabilities:{},ui_pages:['wristbands']},['visit:read'])
 const requested:string[]=[];const previous=http.defaults.adapter as any
 http.defaults.adapter=config=>{requested.push(String(config.url));return previous(config)}
 const {wrapper}=await render()
 try{finish.get('a')!();await flushPromises();expect(requested).not.toContain('/inventory/consumables');expect(wrapper.find('[data-catalog-id="soap"]').exists()).toBe(true)}finally{wrapper.unmount()}
})

it('lack of ordering permission never opens or submits material/order controls',async()=>{
 acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,owner_reset_allowed:false,capabilities:{},ui_pages:['wristbands']},['visit:read'])
 const {wrapper}=await render()
 try{finish.get('a')!();await flushPromises();wrapper.findComponent({name:'CatalogPicker'}).vm.$emit('select',product);await flushPromises();expect(posts).toEqual([]);expect(wrapper.findComponent({name:'ConsumptionEditor'}).exists()).toBe(false)}finally{wrapper.unmount()}
})
it('an in-flight manual order freezes selection and duplicate submit events cannot invalidate its success',async()=>{
 const {wrapper}=await render()
 try{
  finish.get('a')!();await flushPromises()
  const picker=wrapper.findComponent({name:'CatalogPicker'})
  picker.vm.$emit('quantity',product,2);await flushPromises()
  let complete!:()=>void
  const previous=http.defaults.adapter as any
  http.defaults.adapter=config=>config.method==='post'?new Promise(resolve=>{complete=()=>resolve({config,headers:{},status:200,statusText:'',data:{data:[]}})}):previous(config)
  await wrapper.get('[data-testid="submit-order"]').trigger('click');await flushPromises()
  picker.vm.$emit('quantity',product,3);await flushPromises()
  expect(picker.props('quantities')).toEqual({soap:2})
  wrapper.findComponent({name:'OrderCart'}).vm.$emit('submit');await flushPromises()
  complete();await flushPromises();finish.get('a')!();await flushPromises()
  expect(picker.props('quantities')).toEqual({})
  expect(wrapper.get('[data-testid="submit-order"]').attributes('disabled')).toBeDefined()
 }finally{wrapper.unmount()}
})

it('package replacement keeps the return to the server and new package consumes nothing',async()=>{
 acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,owner_reset_allowed:false,capabilities:{visit_order:true,package_write:true},ui_pages:['wristbands']},['visit:order','visit:package'])
 vi.spyOn(ElMessageBox,'confirm').mockResolvedValue('confirm' as any)
 const replacement={...product,id:'package-new',kind:'package',name:'新套票',stock_tracked:false}
 const previous=http.defaults.adapter as any
 http.defaults.adapter=config=>{
  if(config.url==='/catalog')return Promise.resolve({config,headers:{},status:200,statusText:'',data:{data:[replacement]}})
  if(config.url==='/visits/a')return Promise.resolve({config,headers:{},status:200,statusText:'',data:{data:{...visits[0],items:[{id:'old-order',catalog_item_id:'package-old',kind:'package',name:'旧套票',quantity:'1',unit_price:'30.00',total_amount:'30.00',status:'active',inventory_mode:'manual',inventory_consumption:[{stock_item_id:'s1',name:'奶浴袋',base_unit:'袋',quantity:'1.000'}]}]}}})
  return previous(config)
 }
 const {wrapper}=await render()
 try{
  await wrapper.get('[data-catalog-id="package-new"]').trigger('click');await flushPromises()
  await wrapper.get('[data-testid="submit-order"]').trigger('click');await flushPromises()
  expect(posts[0]).toMatchObject({url:'/visits/a/items/batch',body:{confirm_replace:true,items:[{catalog_item_id:'package-new',quantity:1,inventory_mode:'manual',inventory_consumption:[]}]}})
 }finally{wrapper.unmount()}
})

async function losePackageReplacementReply() {
  acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,owner_reset_allowed:false,capabilities:{visit_order:true,package_write:true},ui_pages:['wristbands']},['visit:order','visit:package'])
  vi.spyOn(ElMessageBox,'confirm').mockResolvedValue('confirm' as any)
  const replacement={...product,id:'package-new',kind:'package',name:'新套票',stock_tracked:false}
  const requests:Array<{url:string;raw:string;body:any;key:unknown}>=[]
  const previous=http.defaults.adapter as any
  let applied=false
  http.defaults.adapter=async config=>{
    const response=(data:unknown)=>({config,headers:{},status:200,statusText:'',data:{data}})
    if(config.url==='/catalog')return response([replacement,product])
    if(/^\/visits\/[^/]+$/.test(String(config.url))){
      const group=visits.map(row=>row.id==='a'?{...row,version:applied?4:3,items:[{id:'package-order',catalog_item_id:applied?'package-new':'package-old',kind:'package',name:applied?'新套票':'旧套票',quantity:'1',unit_price:'30.00',total_amount:'30.00',status:'active'}]}:row)
      return response({...group.find(row=>row.id===String(config.url).split('/').at(-1)),linked_visits:group})
    }
    if(config.method==='post'){
      requests.push({url:String(config.url),raw:config.data,body:JSON.parse(config.data),key:config.headers['Idempotency-Key']})
      if(!applied){applied=true;throw new Error('server applied replacement; response lost')}
      return response([])
    }
    return previous(config)
  }
  const rendered=await render()
  await rendered.wrapper.get('[data-catalog-id="package-new"]').trigger('click')
  await rendered.wrapper.get('[data-testid="submit-order"]').trigger('click');await flushPromises()
  expect(requests[0].body).toMatchObject({version:3,confirm_replace:true,items:[{catalog_item_id:'package-new',quantity:1,inventory_mode:'manual',inventory_consumption:[]}]})
  return {...rendered,requests}
}

it('retries the saved package replacement unchanged after realtime shows the already-applied new package',async()=>{
  const {wrapper,requests}=await losePackageReplacementReply()
  try{
    dispatchRealtimeChange('visit.changed',{visit_id:'a'});await flushPromises()
    expect(wrapper.text()).toContain('新套票')
    await wrapper.get('[data-testid="retry-order"]').trigger('click');await flushPromises()
    expect(requests).toHaveLength(2)
    expect(requests[1]).toEqual(requests[0])
    expect(wrapper.find('[data-testid="retry-order"]').exists()).toBe(false)
    expect(wrapper.findComponent({name:'CatalogPicker'}).props('quantities')).toEqual({})
    expect(ElMessageBox.confirm).toHaveBeenCalledTimes(1)
  }finally{wrapper.unmount()}
})

it('linked switching clears materials but returning can retry the stored operation without rebuilding the form',async()=>{
  const {wrapper,router,requests}=await losePackageReplacementReply()
  try{
    wrapper.findComponent({name:'PartyTabs'}).vm.$emit('select','b');await flushPromises()
    expect(wrapper.find('[data-testid="retry-order"]').exists()).toBe(false)
    await router.push('/visits/a');await flushPromises()
    expect(wrapper.findComponent({name:'ConsumptionEditor'}).exists()).toBe(false)
    await wrapper.get('[data-testid="retry-order"]').trigger('click');await flushPromises()
    expect(requests[1]).toEqual(requests[0])
    expect(wrapper.find('[data-testid="retry-order"]').exists()).toBe(false)
  }finally{wrapper.unmount()}
})

it('remount restores the pending retry separately from a new draft and session clear revokes it',async()=>{
  const first=await losePackageReplacementReply()
  first.wrapper.unmount()
  const {wrapper}=await render()
  try{
    expect(wrapper.findComponent({name:'CatalogPicker'}).props('quantities')).toEqual({})
    expect(wrapper.find('[data-testid="retry-order"]').exists()).toBe(true)
    wrapper.findComponent({name:'CatalogPicker'}).vm.$emit('quantity',product,2);await flushPromises()
    await wrapper.get('[data-testid="retry-order"]').trigger('click');await flushPromises()
    expect(first.requests[1]).toEqual(first.requests[0])
    expect(wrapper.findComponent({name:'CatalogPicker'}).props('quantities')).toEqual({soap:2})
    expect(wrapper.findComponent({name:'ConsumptionEditor'}).exists()).toBe(false)
  }finally{wrapper.unmount()}
  const second=await losePackageReplacementReply()
  try{
    expect(second.wrapper.find('[data-testid="retry-order"]').exists()).toBe(true)
    clearBusinessSession();await flushPromises()
    expect(second.wrapper.find('[data-testid="retry-order"]').exists()).toBe(false)
  }finally{second.wrapper.unmount()}
})

function enableTicketChange() {
  acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,
    owner_reset_allowed:false,capabilities:{visit_order:true,visit_manage:true},ui_pages:['wristbands']},['visit:order','visit:write'])
}
it('changing ticket submits the current visit version and server ticket ID, never a price', async () => {
  enableTicketChange()
  const {wrapper}=await render()
  try {
    finish.get('a')!(); await flushPromises()
    await wrapper.get('[data-testid="change-ticket"]').trigger('click'); await flushPromises()
    wrapper.findComponent({name:'AdmissionDialog'}).vm.$emit('confirm',{a:'child'})
    await flushPromises()
    expect(posts[0]).toMatchObject({url:'/visits/a/ticket',body:{ticket_catalog_item_id:'child',version:3}})
    expect(posts[0].body).not.toHaveProperty('price')
  } finally {wrapper.unmount()}
})
it('a linked visit switch cancels pending ticket choice instead of altering the next person', async () => {
  enableTicketChange()
  const {wrapper,router}=await render()
  try {
    finish.get('a')!(); await flushPromises()
    await wrapper.get('[data-testid="change-ticket"]').trigger('click'); await flushPromises()
    await router.push('/visits/b'); await flushPromises()
    expect(wrapper.findComponent({name:'AdmissionDialog'}).props('modelValue')).toBe(false)
    expect(posts).toEqual([])
  } finally {wrapper.unmount()}
})

it('an old ticket change cannot clear a newer desktop busy operation',async()=>{
  enableTicketChange()
  const {wrapper}=await render()
  try {
    finish.get('a')!();await flushPromises()
    let resolvePatch!:()=>void
    const previous=http.defaults.adapter as any
    http.defaults.adapter=config=>config.method==='patch'?new Promise(resolve=>{
      resolvePatch=()=>resolve({config,headers:{},status:200,statusText:'',data:{data:visits[0]}})
    }):previous(config)
    await wrapper.get('[data-testid="change-ticket"]').trigger('click')
    wrapper.findComponent({name:'AdmissionDialog'}).vm.$emit('confirm',{a:'child'})
    await flushPromises()
    const runtime=useRuntimeStore()
    await runtime.setBusinessBusy('正在处理另一笔交易')
    resolvePatch();await flushPromises()
    finish.get('a')!();await flushPromises()
    expect(runtime.businessBusyReason).toBe('正在处理另一笔交易')
  } finally {wrapper.unmount()}
})
