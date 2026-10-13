import {beforeEach,afterEach,it,expect,vi} from 'vitest'
// @vitest-environment jsdom
import {createApp,h,nextTick} from 'vue'
import {webcrypto} from 'node:crypto'
import InventoryExcelPanel from './InventoryExcelPanel.vue'
import {http} from '../../api'
import {acceptBusinessState,clearBusinessSession} from '../../business/state'

async function flushPromises(){await nextTick();await new Promise(resolve=>setTimeout(resolve,0));await nextTick()}
function mount(component:any,options:{props:{canWrite:boolean}}){
 const root=document.createElement('div');document.body.append(root)
 let changed=0;const app=createApp({render:()=>h(component,{...options.props,onChanged:()=>changed++})});app.mount(root)
 function node(element:Element|null):any{return {exists:()=>!!element,element,text:()=>element?.textContent,attributes:(key:string)=>element?.hasAttribute(key)?element.getAttribute(key):undefined,
  async trigger(type:string){element!.dispatchEvent(new Event(type,{bubbles:true}));await nextTick()},
  async setValue(value:string|boolean){const input=element as HTMLInputElement;if(typeof value==='boolean'){input.checked=value;input.dispatchEvent(new Event('change',{bubbles:true}))}else{input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}))}await nextTick()}}}
 return {find:(selector:string)=>node(root.querySelector(selector)),get:(selector:string)=>{const value=root.querySelector(selector);if(!value)throw new Error('Missing '+selector);return node(value)},text:()=>root.textContent,emitted:(_name?:string)=>Array.from({length:changed},()=>[]),unmount:()=>{app.unmount();root.remove()}}
}
let writes:any[]=[]
const plan={preview_token:'signed-preview',requires_password:false,errors:[],rows:[{
 row_number:3,name:'奶膏',action:'update',current_quantity:'800.000',target_quantity:'600.000',
 base_unit:'袋',package_unit:'箱',current_package_cost:'120.00',target_package_cost:'120.00',
 requires_consumption_confirmation:true,decrease_percentage:'25.00',password_required:false}]}
beforeEach(()=>{
 clearBusinessSession();writes=[]
 acceptBusinessState({period_id:'p',policy_version:1,business_revision:1,maintenance:false,
  owner_reset_allowed:false},['inventory:read','inventory:write'])
 vi.stubGlobal('crypto',webcrypto)
 http.defaults.adapter=async config=>{
  if(config.method==='post')writes.push({url:config.url,body:JSON.parse(config.data),key:config.headers['Idempotency-Key']})
  return {config,headers:{},status:200,statusText:'',data:{data:config.url==='/inventory/excel/preview'?plan:config.url==='/inventory/excel/pending'?[{id:'new',name:'新奶膏',quantity:'800.000',package_cost:'120.00'}]:{updated:1,pending:0,unchanged:0}}}
 }
})
afterEach(()=>{clearBusinessSession();vi.unstubAllGlobals();vi.restoreAllMocks()})
async function choose(wrapper:ReturnType<typeof mount>){
 const bytes=new TextEncoder().encode('test-interface-bytes')
 const file=new File([bytes],'库存.xlsx',{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'})
 Object.defineProperty(file,'arrayBuffer',{value:async()=>bytes.buffer})
 Object.defineProperty(wrapper.get('input[type=file]').element,'files',{configurable:true,value:[file]})
 await wrapper.get('input[type=file]').trigger('change');await flushPromises()
 await vi.waitFor(()=>expect(wrapper.find('[data-testid="excel-apply"]').exists()).toBe(true))
}
it('requires the exact25percent row acknowledgement before applying the signed preview',async()=>{
 const wrapper=mount(InventoryExcelPanel,{props:{canWrite:true}})
 try{
  await choose(wrapper)
  expect(wrapper.text()).toContain('是否是真的消耗了这么多')
  expect(wrapper.get('[data-testid="excel-apply"]').attributes('disabled')).toBeDefined()
  await wrapper.get('[data-testid="excel-confirm-3"]').setValue(true)
  await wrapper.get('[data-testid="excel-apply"]').trigger('click');await flushPromises()
  const request=writes.find(row=>row.url==='/inventory/excel/apply')
  expect(request.body).toMatchObject({preview_token:'signed-preview',confirmed_rows:[3]})
  expect(request.key).toBeTruthy()
  expect(wrapper.emitted('changed')).toHaveLength(1)
 }finally{wrapper.unmount()}
})
it('a read-only page cannot show upload or pending mutation controls',async()=>{
 const wrapper=mount(InventoryExcelPanel,{props:{canWrite:false}})
 try{await flushPromises();expect(wrapper.find('input[type=file]').exists()).toBe(false);expect(wrapper.find('[data-testid="excel-pending"]').exists()).toBe(false)}finally{wrapper.unmount()}
})
it('shows a red pending badge and sends basic/package units only when completing a row',async()=>{
 const wrapper=mount(InventoryExcelPanel,{props:{canWrite:true}})
 try{
  await flushPromises();expect(wrapper.get('[data-testid="excel-pending"]').text()).toContain('1')
  await wrapper.get('[data-testid="excel-pending"]').trigger('click')
  await wrapper.get('[data-testid="pending-base-new"]').setValue('袋')
  await wrapper.get('[data-testid="pending-package-new"]').setValue('箱')
  await wrapper.get('[data-testid="pending-factor-new"]').setValue('200')
  await wrapper.get('[data-testid="pending-complete-new"]').trigger('click');await flushPromises()
  expect(writes.find(row=>row.url.endsWith('/new/complete')).body).toEqual({base_unit:'袋',package_unit:'箱',units_per_package:'200'})
 }finally{wrapper.unmount()}
})
