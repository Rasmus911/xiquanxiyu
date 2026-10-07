// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {createApp,h,nextTick} from 'vue'
import {createPinia,setActivePinia} from 'pinia'
import {createMemoryHistory,createRouter} from 'vue-router'
import {acceptBusinessState,clearBusinessSession} from '../business/state'
import {http} from '../api'
import {useBusinessStore} from '../stores/business'
import {useConnectivityStore} from '../stores/connectivity'
import VisitOrderView from './VisitOrderView.vue'
import type {MobileCatalogItem} from '../types'

let destroy:()=>void
beforeEach(()=>{clearBusinessSession(); destroy=()=>{}; vi.spyOn(window,'confirm').mockReturnValue(true)})
afterEach(()=>{destroy(); clearBusinessSession(); vi.restoreAllMocks()})

async function render(){
  acceptBusinessState({period_id:'test',business_revision:1,policy_version:1,maintenance:false,owner_reset_allowed:false},['mobile:order','visit:package'])
  const pinia=createPinia(); setActivePinia(pinia)
  const business=useBusinessStore()
  business.wristbands=[{number:'001',visit_id:'a',version:3,bath_area:'male',amount:'45.00',
    opened_at:'2026-10-04T08:00:00Z',package_catalog_item_id:'packageA'}]
  business.catalog=[]
  useConnectivityStore().markSynced()
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/orders/:visitId',component:VisitOrderView}]})
  await router.push('/orders/a'); await router.isReady()
  const root=document.createElement('div');document.body.append(root)
  const app=createApp({render:()=>h(VisitOrderView)});app.use(pinia);app.use(router);app.mount(root)
  destroy=()=>{app.unmount();root.remove()}
  await nextTick()
  return {root,business,router,pinia}
}

const product={id:'product',kind:'product',name:'奶浴',category:'服务',mobile_scope:'scrub',price:'30.00',stock_tracked:true,stock_quantity:'0',low_stock_threshold:'0',sort_order:1} as MobileCatalogItem
function setInput(node: HTMLInputElement,value:string){node.value=value;node.dispatchEvent(new Event('input'))}
it('staff chooses TOTAL base consumables, retries the original body after remount, and starts the next order empty',async()=>{
  const writes:any[]=[];let uncertain=true
  http.defaults.adapter=async config=>{
    if(config.method==='post'){
      writes.push({url:config.url,body:JSON.parse(config.data),key:config.headers['Idempotency-Key']})
      if(uncertain)throw new Error('uncertain network')
    }
    return {config,headers:{},status:200,statusText:'',data:{data:config.url==='/inventory/consumables'?[{id:'s',name:'奶浴袋',category:'耗材',base_unit:'袋',package_spec:'1*200',stock_quantity:'0',version:1}]:config.method==='post'?{}:{employee:{id:'e'},catalog:[product],wristbands:[{number:'001',visit_id:'a',version:9,bath_area:'male',amount:'45.00',opened_at:'2026-10-04T08:00:00Z'}]}}}
  }
  const {root,business,router,pinia}=await render()
  business.catalog=[product];business.quantities={product:3}
  await vi.waitFor(()=>expect(business.consumables).toHaveLength(1))
  expect(root.querySelector('[data-testid="consumption-product"]')).toBeNull()
  root.querySelector<HTMLButtonElement>('[data-testid="submit-order"]')!.click();await nextTick()
  await vi.waitFor(()=>expect(root.querySelector('[data-testid="consumption-product"]')).not.toBeNull())
  const select=root.querySelector<HTMLSelectElement>('[data-testid="stock-select-product"]')!
  select.value='s';select.dispatchEvent(new Event('change'));await nextTick()
  const add=root.querySelector<HTMLButtonElement>('[data-testid="stock-add-product"]')!;add.click();await nextTick()
  setInput(root.querySelector<HTMLInputElement>('[data-testid="stock-quantity-product-s"]')!,'1.5');await nextTick()
  root.querySelector<HTMLButtonElement>('[data-testid="confirm-consumption"]')!.click()
  await vi.waitFor(()=>expect(writes).toHaveLength(1))
  expect(writes[0].body).toEqual({version:3,items:[{catalog_item_id:'product',quantity:'3',inventory_mode:'manual',inventory_consumption:[{stock_item_id:'s',quantity:'1.5'}]}]})
  await vi.waitFor(()=>expect(business.sending).toBe(false))
  expect(business.pendingOrder('a')).toBeDefined()
  destroy()
  business.catalog=[];business.wristbands[0]!.version=9; business.quantities={}
  const nextRoot=document.createElement('div');document.body.append(nextRoot)
  const app=createApp({render:()=>h(VisitOrderView)});app.use(pinia);app.use(router);app.mount(nextRoot)
  destroy=()=>{app.unmount();nextRoot.remove()};await router.push('/orders/a');await nextTick()
  expect(business.pendingOrder('a')).toBeDefined()
  uncertain=false
  const retry=nextRoot.querySelector<HTMLButtonElement>('[data-testid="retry-order"]');expect(retry).not.toBeNull();retry!.click()
  await vi.waitFor(()=>expect(writes).toHaveLength(2));expect(writes[1]).toEqual(writes[0])
  await vi.waitFor(()=>expect(business.sending).toBe(false))
  business.quantities={product:1};await nextTick()
  nextRoot.querySelector<HTMLButtonElement>('[data-testid="submit-order"]')!.click();await nextTick()
  expect(nextRoot.querySelector<HTMLInputElement>('[data-testid="no-consumption-product"]')!.checked).toBe(false)
  nextRoot.querySelector<HTMLButtonElement>('[data-testid="confirm-consumption"]')!.click();await nextTick()
  expect(writes).toHaveLength(2)
  nextRoot.querySelector<HTMLInputElement>('[data-testid="no-consumption-product"]')!.click();await nextTick()
  nextRoot.querySelector<HTMLButtonElement>('[data-testid="confirm-consumption"]')!.click()
  await vi.waitFor(()=>expect(writes).toHaveLength(3))
  expect(writes[2].body.items).toEqual([{catalog_item_id:'product',quantity:'1',inventory_mode:'manual',inventory_consumption:[]}])
  expect(writes[2].key).not.toBe(writes[0].key)
})

it('cancelling the consumables sheet sends nothing and keeps the selection for another confirmation',async()=>{
  const {root,business}=await render();const writes:any[]=[]
  http.defaults.adapter=async config=>{if(config.method==='post')writes.push(config);return {config,headers:{},status:200,statusText:'',data:{data:[]}}}
  business.catalog=[product];business.quantities={product:2};await nextTick()
  root.querySelector<HTMLButtonElement>('[data-testid="submit-order"]')!.click();await nextTick()
  expect(root.querySelector('[role="dialog"]')?.textContent).toContain('001')
  root.querySelector<HTMLInputElement>('[data-testid="no-consumption-product"]')!.click();await nextTick()
  root.querySelector<HTMLButtonElement>('[data-testid="cancel-consumption"]')!.click();await nextTick()
  expect(writes).toEqual([]);expect(business.pendingOrder('a')).toBeUndefined();expect(business.quantities).toEqual({product:2})
  expect(root.querySelector('[role="dialog"]')).toBeNull()
})

it('a changed visit closes the sheet and cannot attribute the previous selection to the new band',async()=>{
  const {root,business,router}=await render();const writes:any[]=[]
  http.defaults.adapter=async config=>{if(config.method==='post')writes.push(config);return {config,headers:{},status:200,statusText:'',data:{data:[]}}}
  business.wristbands.push({...business.wristbands[0]!,number:'002',visit_id:'b'})
  business.catalog=[product];business.quantities={product:2};await nextTick()
  root.querySelector<HTMLButtonElement>('[data-testid="submit-order"]')!.click();await nextTick()
  const confirm=root.querySelector<HTMLButtonElement>('[data-testid="confirm-consumption"]')
  expect(confirm).not.toBeNull()
  await router.push('/orders/b');await nextTick()
  expect(root.querySelector('[role="dialog"]')).toBeNull()
  confirm!.click();await nextTick();expect(writes).toEqual([]);expect(business.pendingOrder('b')).toBeUndefined()
})

it('confirmation uses the opened selection snapshot and double taps send only one frozen request',async()=>{
  const {root,business}=await render();const writes:any[]=[];let finish!:()=>void
  http.defaults.adapter=async config=>{
    if(config.method==='post')return new Promise(resolve=>{writes.push({url:config.url,body:JSON.parse(config.data)});finish=()=>resolve({config,headers:{},status:200,statusText:'',data:{data:{}}})})
    return {config,headers:{},status:200,statusText:'',data:{data:config.url==='/mobile/bootstrap'?{employee:{id:'e'},catalog:[product],wristbands:business.wristbands}:[]}}
  }
  business.catalog=[product];business.quantities={product:2};await nextTick()
  root.querySelector<HTMLButtonElement>('[data-testid="submit-order"]')!.click();await nextTick()
  business.quantities={product:8};business.wristbands[0]!.version=10
  root.querySelector<HTMLInputElement>('[data-testid="no-consumption-product"]')!.click();await nextTick()
  const confirm=root.querySelector<HTMLButtonElement>('[data-testid="confirm-consumption"]')!
  confirm.click();confirm.click();await vi.waitFor(()=>expect(writes).toHaveLength(1))
  expect(writes[0]).toEqual({url:'/mobile/visits/a/items',body:{version:3,items:[{catalog_item_id:'product',quantity:'2',inventory_mode:'manual',inventory_consumption:[]}]}})
  expect(business.pendingOrder('a')?.items[0]?.quantity).toBe('2')
  finish();await vi.waitFor(()=>expect(business.sending).toBe(false));expect(business.pendingOrder('a')).toBeUndefined()
})

it('mobile cancel sends the captured visit version and restores its server bill',async()=>{
  const requests:any[]=[]
  const {root,business}=await render()
  http.defaults.adapter=async config=>{
    if(config.method==='delete') requests.push({url:config.url,body:JSON.parse(config.data)})
    return {config,headers:{},status:200,statusText:'',data:{data:config.method==='delete'?{}:{
      employee:{id:'owner',username:'fixture',display_name:'隔离用户',role:'admin',role_label:'管理员'},catalog:[],
      wristbands:[{...business.wristbands[0],amount:'15.00',package_catalog_item_id:null}]}}}
  }
  const button=[...root.querySelectorAll('button')].find(node=>node.textContent?.includes('取消套票'))
  expect(button).toBeDefined()
  button!.click()
  await vi.waitFor(()=>expect(business.wristbands[0]?.amount).toBe('15.00'))
  expect(requests[0]).toMatchObject({url:'/mobile/visits/a/package',body:{version:3}})
  expect(requests[0].body.idempotency_key).toBeTruthy()
  expect(requests[0].body).not.toHaveProperty('amount')
})

it('declining cancellation cannot send a request or change the package',async()=>{
  vi.mocked(window.confirm).mockReturnValue(false)
  const {root,business}=await render();let writes=0
  http.defaults.adapter=async()=>{writes++;throw new Error('must not call API')}
  const button=[...root.querySelectorAll('button')].find(node=>node.textContent?.includes('取消套票'))
  expect(button).toBeDefined();button!.click();await nextTick()
  expect(writes).toBe(0)
  expect(business.wristbands[0]?.package_catalog_item_id).toBe('packageA')
})
