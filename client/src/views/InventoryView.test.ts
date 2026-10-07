import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import InventoryView from './InventoryView.vue'
import { http } from '../api/http'
import { acceptBusinessState, clearBusinessSession } from '../business/state'

const stock = { id:'s1',name:'奶浴袋',category:'耗材',base_unit:'袋',package_unit:'箱',units_per_package:'200.000',package_spec:'1*200',stock_quantity:'800.000',low_stock_threshold:'20.000',is_active:true,version:3,legacy_catalog_item_id:null }
let writes: any[]
beforeEach(() => {
  clearBusinessSession(); writes=[]
  acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,owner_reset_allowed:false,capabilities:{inventory_write:true}},['inventory:read','inventory:write'])
  http.defaults.adapter=async config=>{
    if(config.method!=='get') writes.push({url:config.url,method:config.method,body:JSON.parse(config.data),key:config.headers['Idempotency-Key']})
    const data=config.url==='/inventory/stock-items' ? [stock,{...stock,id:'s2',name:'洗发水',base_unit:'瓶',stock_quantity:'10.000'}] : config.url==='/inventory/stock-movements' ? [{id:'m1',stock_item_id:'s1',movement_type:'opening',quantity:'800.000',balance_before:'0.000',balance_after:'800.000',input_quantity:'4.000',input_unit:'package',conversion_factor:'200.000',base_unit:'袋',package_unit:'箱',reference_type:null,reference_id:null,operator_id:'e1',reason:'期初实盘',created_at:'2026-10-05T01:00:00Z'}] : []
    return {config,headers:{},status:200,statusText:'',data:{data}}
  }
})
afterEach(()=>{clearBusinessSession();ElMessage.closeAll();vi.restoreAllMocks()})
it('creates independent stock with four boxes previewing exactly 800.000 bags and separates unit totals',async()=>{
  const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
  try {
    await flushPromises()
    expect(wrapper.text()).toContain('800.000 袋')
    expect(wrapper.text()).toContain('10.000 瓶')
    await wrapper.get('[data-testid="stock-new"]').trigger('click')
    const vm=wrapper.vm as any
    Object.assign(vm.masterForm,{name:'奶浴袋',category:'耗材',base_unit:'袋',package_unit:'箱',units_per_package:'200',opening_quantity:'4',opening_unit:'package'})
    await flushPromises()
    expect(wrapper.find('[data-testid="opening-preview"]').text()).toContain('800.000 袋')
    await wrapper.get('[data-testid="stock-save"]').trigger('click');await flushPromises()
    expect(writes[0]).toMatchObject({url:'/inventory/stock-items',method:'post',body:{name:'奶浴袋',base_unit:'袋',opening_quantity:'4',opening_unit:'package'}})
    expect(writes[0].key).toBeTruthy()
    expect(writes[0].body).not.toHaveProperty('catalog_item_id')
  } finally {wrapper.unmount()}
})
it('zero opening is omitted, edit uses integer version, archive confirms nonzero writeoff',async()=>{
  vi.spyOn(ElMessageBox,'confirm').mockResolvedValue('confirm' as any)
  const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
  try {
    await flushPromises();await wrapper.get('[data-testid="stock-new"]').trigger('click')
    Object.assign((wrapper.vm as any).masterForm,{name:'新耗材',base_unit:'袋',opening_quantity:'0'})
    await wrapper.get('[data-testid="stock-save"]').trigger('click');await flushPromises()
    expect(writes[0].body).not.toHaveProperty('opening_quantity')
    await wrapper.findAll('[data-testid="stock-edit"]')[0]!.trigger('click')
    Object.assign((wrapper.vm as any).masterForm,{name:'改名奶浴袋'})
    await wrapper.get('[data-testid="stock-save"]').trigger('click');await flushPromises()
    expect(writes[1]).toMatchObject({method:'patch',url:'/inventory/stock-items/s1',body:{name:'改名奶浴袋',version:3}})
    await wrapper.findAll('[data-testid="stock-archive"]')[0]!.trigger('click');await flushPromises()
    expect(writes[2]).toMatchObject({method:'delete',url:'/inventory/stock-items/s1',body:{version:3,confirm_writeoff:true}})
  } finally {wrapper.unmount()}
})
it('receives in package units with the master version and required reason',async()=>{
  const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
  try {
    await flushPromises();await wrapper.findAll('[data-testid="stock-adjust"]')[0]!.trigger('click')
    Object.assign((wrapper.vm as any).form,{quantity:'4',input_unit:'package',reason:'采购单001'})
    await wrapper.get('[data-testid="adjust-save"]').trigger('click');await flushPromises()
    expect(writes[0]).toMatchObject({url:'/inventory/stock-adjust',body:{stock_item_id:'s1',version:3,movement_type:'purchase',quantity:'4',input_unit:'package',reason:'采购单001'}})
  } finally {wrapper.unmount()}
})
it('read-only inventory has no mutation controls',async()=>{
  acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,owner_reset_allowed:false,capabilities:{}},['inventory:read'])
  const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
  try {await flushPromises();expect(wrapper.find('[data-testid="stock-new"]').exists()).toBe(false);expect(wrapper.find('[data-testid="stock-edit"]').exists()).toBe(false)} finally {wrapper.unmount()}
})

it('movement history uses immutable unit snapshots and server reason',async()=>{
 const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
 try{await flushPromises();expect(wrapper.text()).toContain('期初实盘');expect(wrapper.find('.movement').text()).toContain('4.000 箱 × 200.000');expect(wrapper.find('.movement').text()).toContain('800.000 袋')}finally{wrapper.unmount()}
})

it('lost receiving reply reuses the original integer version and key after stock refresh',async()=>{
 const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
 try{
  await flushPromises();await wrapper.findAll('[data-testid="stock-adjust"]')[0]!.trigger('click')
  Object.assign((wrapper.vm as any).form,{quantity:'4',input_unit:'package',reason:'采购单001'})
  const previous=http.defaults.adapter as any;let fail=true
  http.defaults.adapter=async config=>{
   if(config.method==='post'){
    writes.push({url:config.url,method:config.method,body:JSON.parse(config.data),key:config.headers['Idempotency-Key']})
    if(fail)throw new Error('lost reply')
    return {config,headers:{},status:200,statusText:'',data:{data:{stock_item:{...stock,version:4,stock_quantity:'1600.000'},movement:{id:'m2'}}}}
   }
   return previous(config)
  }
  await wrapper.get('[data-testid="adjust-save"]').trigger('click');await flushPromises()
  Object.assign((wrapper.vm as any).form,{version:9})
  fail=false;await wrapper.get('[data-testid="adjust-save"]').trigger('click');await flushPromises()
  expect(writes[1]).toEqual(writes[0]);expect(writes[1].body.version).toBe(3)
 }finally{wrapper.unmount()}
})

it('leaving and returning to inventory can retry a lost receiving reply with its original payload',async()=>{
 let wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
 try{
  await flushPromises();await wrapper.findAll('[data-testid="stock-adjust"]')[0]!.trigger('click')
  Object.assign((wrapper.vm as any).form,{quantity:'4',input_unit:'package',reason:'采购单001'})
  const previous=http.defaults.adapter as any;let fail=true
  http.defaults.adapter=async config=>{
   if(config.method==='post'){
    writes.push({body:JSON.parse(config.data),key:config.headers['Idempotency-Key']})
    if(fail)throw new Error('lost reply')
    return {config,headers:{},status:200,statusText:'',data:{data:{stock_item:{...stock,version:4},movement:{id:'m2'}}}}
   }
   return previous(config)
  }
  await wrapper.get('[data-testid="adjust-save"]').trigger('click');await flushPromises()
  wrapper.unmount();wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}});await flushPromises()
  expect(wrapper.find('[data-testid="stock-retry"]').exists()).toBe(true)
  fail=false;await wrapper.get('[data-testid="stock-retry"]').trigger('click');await flushPromises()
  expect(writes[1]).toEqual(writes[0])
  expect(wrapper.find('[data-testid="stock-retry"]').exists()).toBe(false)
 }finally{wrapper.unmount()}
})

it('rejects an unrepresentable opening conversion visibly and submits only after an exact correction',async()=>{
 const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
 try{
  await flushPromises();await wrapper.get('[data-testid="stock-new"]').trigger('click')
  Object.assign((wrapper.vm as any).masterForm,{name:'精油',base_unit:'瓶',package_unit:'箱',units_per_package:'1.001',opening_quantity:'1.001',opening_unit:'package'})
  await flushPromises()
  expect(wrapper.get('[data-testid="opening-preview"]').text()).not.toContain('1.002')
  expect(wrapper.get('[data-testid="stock-validation"]').text()).toContain('三位小数')
  await wrapper.get('[data-testid="stock-save"]').trigger('click');await flushPromises()
  expect(writes).toEqual([])
  Object.assign((wrapper.vm as any).masterForm,{opening_quantity:'1.000'});await flushPromises()
  expect(wrapper.get('[data-testid="opening-preview"]').text()).toContain('1.001 瓶')
  await wrapper.get('[data-testid="stock-save"]').trigger('click');await flushPromises()
  expect(writes[0].body).toMatchObject({opening_quantity:'1.000',units_per_package:'1.001',opening_unit:'package'})
 }finally{wrapper.unmount()}
})

it('blocks invalid receipt input and preserves exact signed adjustment payload/version/key',async()=>{
 const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
 try{
  await flushPromises();await wrapper.findAll('[data-testid="stock-adjust"]')[0]!.trigger('click')
  const form=(wrapper.vm as any).form
  for(const quantity of ['1.0001','Infinity','1000000000','999999999.999','0','-1']){
   Object.assign(form,{quantity,input_unit:'package',reason:'实盘'});await flushPromises()
   await wrapper.get('[data-testid="adjust-save"]').trigger('click');await flushPromises()
   expect(writes).toEqual([])
   expect(wrapper.get('[data-testid="adjust-validation"]').text()).toContain('三位小数')
  }
  Object.assign(form,{movement_type:'adjust',quantity:'-0.125'});await flushPromises()
  expect(wrapper.get('[data-testid="adjust-preview"]').text()).toContain('-25.000 袋')
  await wrapper.get('[data-testid="adjust-save"]').trigger('click');await flushPromises()
  expect(writes[0]).toMatchObject({url:'/inventory/stock-adjust',body:{version:3,movement_type:'adjust',quantity:'-0.125',input_unit:'package'}})
  expect(writes[0].key).toBeTruthy()
 }finally{wrapper.unmount()}
})

it('does not send an unrepresentable receiving product or round it into a valid preview',async()=>{
 const previous=http.defaults.adapter as any
 http.defaults.adapter=config=>config.method==='get'&&config.url==='/inventory/stock-items'?Promise.resolve({config,headers:{},status:200,statusText:'',data:{data:[{...stock,units_per_package:'1.001'}]}}):previous(config)
 const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
 try{
  await flushPromises();await wrapper.get('[data-testid="stock-adjust"]').trigger('click')
  Object.assign((wrapper.vm as any).form,{quantity:'1.001',input_unit:'package',reason:'采购实盘'})
  await flushPromises()
  expect(wrapper.get('[data-testid="adjust-preview"]').text()).not.toContain('1.002')
  expect(wrapper.get('[data-testid="adjust-validation"]').text()).toContain('换算结果')
  await wrapper.get('[data-testid="adjust-save"]').trigger('click');await flushPromises()
  expect(writes).toEqual([])
  Object.assign((wrapper.vm as any).form,{quantity:'2'});await flushPromises()
  expect(wrapper.get('[data-testid="adjust-preview"]').text()).toContain('2.002 袋')
  await wrapper.get('[data-testid="adjust-save"]').trigger('click');await flushPromises()
  expect(writes[0].body).toMatchObject({version:3,quantity:'2',input_unit:'package'})
 }finally{wrapper.unmount()}
})

it('does not submit invalid master factor or cost without receiving quantity',async()=>{
 const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
 try{
  await flushPromises();await wrapper.get('[data-testid="stock-new"]').trigger('click')
  const form=(wrapper.vm as any).masterForm
  Object.assign(form,{name:'新耗材',base_unit:'袋',opening_quantity:'0'})
  for(const units_per_package of ['0','-1','1.0001','NaN','1000000000']){
   Object.assign(form,{units_per_package});await flushPromises()
   await wrapper.get('[data-testid="stock-save"]').trigger('click');await flushPromises();expect(writes).toEqual([])
  }
  Object.assign(form,{units_per_package:'1',unit_cost:'120'});await flushPromises()
  await wrapper.get('[data-testid="stock-save"]').trigger('click');await flushPromises();expect(writes).toEqual([])
  expect(wrapper.get('[data-testid="stock-validation"]').text()).toContain('成本')
 }finally{wrapper.unmount()}
})
