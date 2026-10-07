import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {flushPromises,mount} from '@vue/test-utils'
import ElementPlus,{ElMessage,ElMessageBox} from 'element-plus'
import InventoryView from './InventoryView.vue'
import {http} from '../api/http'
import {acceptBusinessState,clearBusinessSession} from '../business/state'

let stock:any,requests:any[]
beforeEach(()=>{
 clearBusinessSession();requests=[]
 acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,owner_reset_allowed:false,capabilities:{inventory_write:true}},['inventory:read','inventory:write'])
 stock={id:'s1',name:'奶浴袋',category:'耗材',base_unit:'袋',package_unit:'箱',units_per_package:'200.000',package_spec:'1*200',stock_quantity:'800.000',low_stock_threshold:'120.000',is_active:true,version:7,legacy_catalog_item_id:null,unit_cost:null}
 http.defaults.adapter=async config=>{
  if(config.method!=='get')requests.push({url:config.url,method:config.method,body:JSON.parse(config.data)})
  const data=config.url==='/inventory/stock-items'?[stock]:[]
  return {config,headers:{},status:200,statusText:'',data:{data}}
 }
})
afterEach(()=>{clearBusinessSession();ElMessage.closeAll();vi.restoreAllMocks()})
it.each([[null,'0',false],['0.00','1.20',true],['1.20','1.2',false]])('master price %s → %s uses login password iff previously assigned and changed',async(previous,next,password)=>{
 stock.unit_cost=previous
 const prompt=vi.spyOn(ElMessageBox,'prompt').mockResolvedValue({value:'own-password',action:'confirm'} as any)
 const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
 try{
  await flushPromises()
  expect(wrapper.find('.el-table').text()).toContain(previous===null?'未设置':`¥${previous}/袋`)
  await wrapper.get('[data-testid="stock-edit"]').trigger('click');await flushPromises()
  await wrapper.get('[data-testid="master-unit-cost"]').setValue(next)
  await wrapper.get('[data-testid="stock-save"]').trigger('click');await flushPromises()
  expect(prompt).toHaveBeenCalledTimes(password?1:0)
  expect(requests).toHaveLength(1)
  expect(requests[0]).toMatchObject({url:'/inventory/stock-items/s1',method:'patch',body:{version:7}})
  if(previous!==null&&Number(previous)===Number(next))expect(requests[0].body).not.toHaveProperty('unit_cost')
  else expect(requests[0].body.unit_cost).toBe(next)
  if(password)expect(requests[0].body.password).toBe('own-password')
  else expect(requests[0].body).not.toHaveProperty('password')
 }finally{wrapper.unmount()}
})
it('editing the name of an unpriced stock item omits cost so the server accepts the ordinary edit',async()=>{
 const previous=http.defaults.adapter as any
 http.defaults.adapter=async config=>{
  if(config.method==='patch'&&Object.hasOwn(JSON.parse(config.data),'unit_cost'))throw {response:{status:422,data:{message:'成本不接受空值'}}}
  return previous(config)
 }
 const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
 try{
  await flushPromises();await wrapper.get('[data-testid="stock-edit"]').trigger('click');await flushPromises()
  ;(wrapper.vm as any).masterForm.name='改名奶浴袋'
  await wrapper.get('[data-testid="stock-save"]').trigger('click');await flushPromises()
  expect(requests).toHaveLength(1)
  expect(requests[0]).toMatchObject({method:'patch',body:{name:'改名奶浴袋',version:7}})
  expect(requests[0].body).not.toHaveProperty('unit_cost')
  expect((wrapper.vm as any).masterOpen).toBe(false)
 }finally{wrapper.unmount()}
})
it('clearing an assigned master cost visibly rejects the edit without prompting or writing',async()=>{
 stock.unit_cost='0.00'
 const prompt=vi.spyOn(ElMessageBox,'prompt').mockResolvedValue({value:'own-password'} as any)
 const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
 try{
  await flushPromises();await wrapper.get('[data-testid="stock-edit"]').trigger('click');await flushPromises()
  await wrapper.get('[data-testid="master-unit-cost"]').setValue('')
  await wrapper.get('[data-testid="stock-save"]').trigger('click');await flushPromises()
  expect(wrapper.get('[data-testid="stock-validation"]').text()).toContain('不能清空')
  expect(prompt).not.toHaveBeenCalled();expect(requests).toEqual([])
 }finally{wrapper.unmount()}
})
it('cancelled password prompt sends no master or receipt write',async()=>{
 stock.unit_cost='0.00';vi.spyOn(ElMessageBox,'prompt').mockRejectedValue('cancel')
 const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
 try{
  await flushPromises();await wrapper.get('[data-testid="stock-edit"]').trigger('click');await flushPromises()
  await wrapper.get('[data-testid="master-unit-cost"]').setValue('2')
  await wrapper.get('[data-testid="stock-save"]').trigger('click');await flushPromises();expect(requests).toEqual([])
 }finally{wrapper.unmount()}
})
it('blocks repeated master save prompts and a cleared session revokes a pending authorization',async()=>{
 stock.unit_cost='0.00'
 let resolve!:(value:any)=>void
 const prompt=vi.spyOn(ElMessageBox,'prompt').mockImplementation(()=>new Promise(done=>{resolve=done}))
 const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
 try{
  await flushPromises();await wrapper.get('[data-testid="stock-edit"]').trigger('click');await flushPromises()
  await wrapper.get('[data-testid="master-unit-cost"]').setValue('2')
  await wrapper.get('[data-testid="stock-save"]').trigger('click');await flushPromises()
  await wrapper.get('[data-testid="stock-save"]').trigger('click');await flushPromises()
  expect(prompt).toHaveBeenCalledTimes(1)
  expect(wrapper.get('[data-testid="stock-save"]').attributes('disabled')).toBeDefined()
  clearBusinessSession();resolve({value:'own-password'});await flushPromises();expect(requests).toEqual([])
 }finally{wrapper.unmount()}
})
it('an uncertain cost write stores its retry key without the login password',async()=>{
 stock.unit_cost='0.00';vi.spyOn(ElMessageBox,'prompt').mockResolvedValue({value:'secret-cost-password',action:'confirm'} as any)
 const previous=http.defaults.adapter as any
 http.defaults.adapter=async config=>{if(config.method==='patch')throw new Error('lost reply');return previous(config)}
 const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
 try{
  await flushPromises();await wrapper.get('[data-testid="stock-edit"]').trigger('click');await flushPromises()
  await wrapper.get('[data-testid="master-unit-cost"]').setValue('2')
  await wrapper.get('[data-testid="stock-save"]').trigger('click');await flushPromises()
  expect(wrapper.find('[data-testid="stock-retry"]').exists()).toBe(true)
  expect(Object.values(sessionStorage).join('')).not.toContain('secret-cost-password')
  expect(Object.values(localStorage).join('')).not.toContain('secret-cost-password')
 }finally{wrapper.unmount()}
})
it.each([[null,false],['1.00',true],['2.00',false]])('receipt correction from %s remains a separate write and authenticates changes to an assigned cost',async(previous,password)=>{
 const prompt=vi.spyOn(ElMessageBox,'prompt').mockResolvedValue({value:'own-password',action:'confirm'} as any)
 const old=http.defaults.adapter as any
 http.defaults.adapter=async config=>config.url==='/inventory/stock-movements'&&config.method==='get'?{config,headers:{},status:200,statusText:'',data:{data:[{id:'m1',stock_item_id:'s1',movement_type:'purchase',quantity:'200.000',balance_after:'800.000',input_quantity:'1.000',input_unit:'package',conversion_factor:'200.000',reason:'采购',created_at:'2026-10-07T00:00:00Z',base_unit:'袋',package_unit:'箱',balance_before:'600.000',cost:previous===null?null:{id:'c1',version:1,unit_cost:previous,total_cost:previous,base_unit_cost:'0.005000',operator_id:'owner',created_at:'2026-10-07T00:00:00Z'}}]}}:old(config)
 const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
 try{
  await flushPromises();await wrapper.findAll('button').find(row=>row.text()===(previous===null?'补录成本':'修改成本'))!.trigger('click');await flushPromises()
  ;(wrapper.vm as any).costInput='2.00';await flushPromises()
  await wrapper.findAll('button').find(row=>row.text()==='保存成本')!.trigger('click');await flushPromises()
  expect(prompt).toHaveBeenCalledTimes(password?1:0)
  expect(requests).toHaveLength(1);expect(requests[0]).toMatchObject({url:'/inventory/stock-movements/m1/cost',body:{unit_cost:'2.00',expected_cost_id:previous===null?null:'c1'}})
  if(password)expect(requests[0].body.password).toBe('own-password')
 }finally{wrapper.unmount()}
})
