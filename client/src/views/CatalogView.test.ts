import { afterEach, beforeEach, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { http } from '../api/http'
import { acceptBusinessState, clearBusinessSession } from '../business/state'
import CatalogView from './CatalogView.vue'
const rows=[{id:'s1',kind:'service',name:'搓澡',category:'洗浴',mobile_scope:'both',price:'20.00',stock_tracked:false,stock_quantity:'0',low_stock_threshold:'0',sort_order:1,is_active:true,can_edit:true},
 {id:'t1',kind:'ticket',name:'门票',category:'门票',price:'15.00',is_active:true,can_edit:false},
 {id:'old',kind:'service',name:'停用服务',category:'洗浴',price:'10.00',is_active:false,can_edit:true}]
let requests:any[]
beforeEach(()=>{
 clearBusinessSession();requests=[]
 acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,owner_reset_allowed:false,capabilities:{}},['catalog:read','catalog:write'])
 http.defaults.adapter=async config=>{requests.push({url:config.url,method:config.method,params:config.params,body:config.data&&JSON.parse(config.data)});return {config,headers:{},status:200,statusText:'',data:{data:rows}}}
})
afterEach(()=>{clearBusinessSession();ElMessage.closeAll()})
it('hides inactive rows by default and server can_edit protects tickets while permitting service name and price edits',async()=>{
 const wrapper=mount(CatalogView,{global:{plugins:[ElementPlus]}})
 try {
  await flushPromises();expect(wrapper.text()).not.toContain('停用服务')
  expect(wrapper.findAll('[data-testid="catalog-edit"]')).toHaveLength(1)
  await wrapper.get('[data-testid="catalog-edit"]').trigger('click')
  Object.assign((wrapper.vm as any).form,{name:'改名搓澡',price:25})
  await wrapper.get('[data-testid="catalog-save"]').trigger('click');await flushPromises()
  expect(requests.find(row=>row.method==='patch')).toMatchObject({url:'/catalog/s1',body:{name:'改名搓澡',price:25}})
  expect(wrapper.find('[data-testid="inactive-filter"]').exists()).toBe(false)
 } finally{wrapper.unmount()}
})
it('pages catalog ten rows at a time and resets search and clamps refreshed results',async()=>{
 let catalog=Array.from({length:21},(_,i)=>({...rows[0],id:`s${i}`,name:`服务${String(i).padStart(2,'0')}`}))
 http.defaults.adapter=async config=>({config,headers:{},status:200,statusText:'',data:{data:catalog}})
 const wrapper=mount(CatalogView,{global:{plugins:[ElementPlus]}})
 try{
  await flushPromises();expect(wrapper.findAll('.el-table__row')).toHaveLength(10)
  expect(wrapper.find('.el-card__header .el-pagination').exists()).toBe(true)
  await wrapper.get('.btn-next').trigger('click');await flushPromises();expect(wrapper.find('.el-table').text()).toContain('服务10')
  await wrapper.get('.catalog-filters input').setValue('服务20');await flushPromises()
  expect(wrapper.findAll('.el-table__row')).toHaveLength(1);expect(wrapper.find('.el-table').text()).toContain('服务20')
  await wrapper.get('.catalog-filters input').setValue('');await flushPromises()
  await wrapper.get('.btn-next').trigger('click');await flushPromises()
  catalog=catalog.slice(0,2);await (wrapper.vm as any).load();await flushPromises()
  expect(wrapper.findAll('.el-table__row')).toHaveLength(2)
 }finally{wrapper.unmount()}
})
it('administrator inactive filter requests all catalog rows',async()=>{
 acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,owner_reset_allowed:false,capabilities:{catalog_layout:true}},['*'])
 const wrapper=mount(CatalogView,{global:{plugins:[ElementPlus]}})
 try{
  await flushPromises();await wrapper.get('[data-testid="inactive-filter"] input').setValue(true);await flushPromises()
  expect(requests.at(-1).params).toEqual({active:false})
  expect(wrapper.text()).toContain('停用服务')
 }finally{wrapper.unmount()}
})
it('cashier catalog capability includes inactive rows and edits ticket/package attributes while retaining package definitions',async()=>{
 acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,owner_reset_allowed:false,capabilities:{catalog_write:true}},['catalog:read','catalog:write'])
 const definition={schema:1,display_contents:['门票'],slots:[{catalog_item_ids:['t1'],quantity:'1'}]}
 http.defaults.adapter=async config=>{requests.push({url:config.url,method:config.method,params:config.params,body:config.data&&JSON.parse(config.data)});return {config,headers:{},status:200,statusText:'',data:{data:[{...rows[1],can_edit:true},{...rows[0],id:'pkg',kind:'package',name:'套票',package_definition:definition},rows[2]]}}}
 const wrapper=mount(CatalogView,{global:{plugins:[ElementPlus]}})
 try {
  await flushPromises();await wrapper.get('[data-testid="inactive-filter"] input').setValue(true);await flushPromises();expect(requests.at(-1).params).toEqual({active:false})
  const pkg=wrapper.findAll('.el-table__body tr').find(row=>row.text().includes('套票'))!
  await pkg.get('[data-testid="catalog-edit"]').trigger('click');Object.assign((wrapper.vm as any).form,{name:'新套票',price:88,is_active:false});await wrapper.get('[data-testid="catalog-save"]').trigger('click');await flushPromises()
  const body=requests.find(row=>row.method==='patch').body;expect(body).toMatchObject({name:'新套票',price:88,is_active:false});expect(body).not.toHaveProperty('package_definition')
  expect(definition.slots[0]?.catalog_item_ids).toEqual(['t1'])
 }finally{wrapper.unmount()}
})
