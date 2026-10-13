import {beforeEach,afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import ElementPlus,{ElMessageBox,ElMessage} from 'element-plus'
import InventoryView from './InventoryView.vue'
import {http} from '../api/http'
import {acceptBusinessState,clearBusinessSession} from '../business/state'
let row:any,writes:any[]
beforeEach(()=>{clearBusinessSession();writes=[];row={id:'s',name:'奶膏',version:3,base_unit:'袋',package_unit:'箱',units_per_package:'200.000',stock_quantity:'800.000',low_stock_threshold:'120.000',is_active:true,category:'耗材',unit_cost:null};acceptBusinessState({period_id:'p',policy_version:1,business_revision:1,maintenance:false,owner_reset_allowed:false,capabilities:{inventory_write:true}},['inventory:read','inventory:write']);http.defaults.adapter=async config=>{if(config.method!=='get')writes.push(JSON.parse(config.data));return {config,headers:{},status:200,statusText:'',data:{data:config.url==='/inventory/stock-items'?[row]:[]}}}})
afterEach(()=>{clearBusinessSession();ElMessage.closeAll();vi.restoreAllMocks()})
it('supports 120 per box and displays 0.600000 per bag without losing the box basis',async()=>{
 const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
 try{await flushPromises();await wrapper.get('[data-testid="stock-edit"]').trigger('click');await wrapper.get('[data-testid="master-cost-basis"]').setValue('package');await wrapper.get('[data-testid="master-unit-cost"]').setValue('120');await flushPromises();expect(wrapper.get('[data-testid="master-cost-preview"]').text()).toContain('0.600000');await wrapper.get('[data-testid="stock-save"]').trigger('click');await flushPromises();expect(writes[0]).toMatchObject({reference_cost:'120',cost_basis:'package',version:3});expect(writes[0]).not.toHaveProperty('unit_cost')}finally{wrapper.unmount()}
})
it('changing package factor authenticates when the actual existing base cost changes',async()=>{
 row={...row,unit_cost:'0.60',reference_cost:'120.00',cost_basis:'package',base_unit_cost:'0.600000',package_cost:'120.00'}
 vi.spyOn(ElMessageBox,'prompt').mockResolvedValue({value:'own-password'} as any)
 const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
 try{await flushPromises();await wrapper.get('[data-testid="stock-edit"]').trigger('click');(wrapper.vm as any).masterForm.units_per_package='100';await wrapper.get('[data-testid="stock-save"]').trigger('click');await flushPromises();expect(writes[0].password).toBe('own-password');expect(writes[0]).toMatchObject({units_per_package:'100'})}finally{wrapper.unmount()}
})
