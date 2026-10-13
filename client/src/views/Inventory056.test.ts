import {beforeEach,afterEach,it,expect} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import ElementPlus from 'element-plus'
import InventoryView from './InventoryView.vue'
import {http} from '../api/http'
import {acceptBusinessState,clearBusinessSession} from '../business/state'
beforeEach(()=>{
 clearBusinessSession()
 acceptBusinessState({period_id:'p',policy_version:1,business_revision:1,maintenance:false,owner_reset_allowed:false,capabilities:{inventory_write:true}},['inventory:read','inventory:write'])
 http.defaults.adapter=async config=>({config,headers:{},status:200,statusText:'',data:{data:config.url==='/inventory/stock-items'?[{id:'s',name:'奶膏',version:3,base_unit:'袋',package_unit:'箱',units_per_package:'200.000',stock_quantity:'800.000',low_stock_threshold:'120.000',is_active:true,category:'耗材',unit_cost:'0.60',package_cost:'120.00',base_unit_cost:'0.600000'},{id:'s2',name:'液体',version:1,base_unit:'升',stock_quantity:'1.250',low_stock_threshold:'0.000',is_active:true}]:[]}})
})
afterEach(clearBusinessSession)
it('uses shared page margins, compact Excel actions and exact stock display without changing costs',async()=>{
 const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
 try{
  await flushPromises()
  expect(wrapper.classes()).toContain('page')
  expect(wrapper.text()).toContain('800 袋')
  expect(wrapper.text()).not.toContain('800.000')
  expect(wrapper.text()).toContain('1.25 升')
  expect(wrapper.text()).toContain('¥120.00/箱')
  expect(wrapper.text()).toContain('¥0.600000/袋')
  expect(wrapper.get('input[type=file]').classes()).toContain('excel-file-input')
  expect(wrapper.get('[aria-label="Excel人工盘点"]').classes()).toContain('excel-panel--compact')
 }finally{wrapper.unmount()}
})
