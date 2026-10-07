import { afterEach, beforeEach, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import InventoryView from './InventoryView.vue'
import { http } from '../api/http'
import { acceptBusinessState, clearBusinessSession } from '../business/state'

const stocks = Array.from({ length: 31 }, (_, i) => ({ id: `s${i}`, name: `真实库存${String(i).padStart(2,'0')}`,
  category:'耗材',base_unit:'袋',package_unit:'箱',units_per_package:'200.000',package_spec:'1*200',
  stock_quantity:'800.000',low_stock_threshold:'120.000',is_active:true,version:1,legacy_catalog_item_id:null }))
let writes: any[]
beforeEach(() => {
  writes=[]; clearBusinessSession()
  acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,
    owner_reset_allowed:false,capabilities:{inventory_write:true}},['inventory:read','inventory:write'])
  http.defaults.adapter=async config=>{
    if(config.method!=='get') writes.push(JSON.parse(config.data))
    return {config,headers:{},status:200,statusText:'',data:{data:config.url==='/inventory/stock-items'?stocks:[]}}
  }
})
afterEach(()=>{clearBusinessSession();ElMessage.closeAll()})
it('shows 10 rows per page in a header pager and resets to the first page on search', async () => {
  const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
  try {
    await flushPromises()
    const table=()=>wrapper.findAll('.el-table')[0]!
    expect(table().findAll('.el-table__row')).toHaveLength(10)
    expect(wrapper.find('.el-card__header .el-pagination').exists()).toBe(true)
    await wrapper.get('.btn-next').trigger('click');await flushPromises()
    expect(table().text()).toContain('真实库存10')
    expect(table().text()).not.toContain('真实库存00')
    await wrapper.get('.inventory-toolbar input').setValue('真实库存30');await flushPromises()
    expect(table().findAll('.el-table__row')).toHaveLength(1)
    expect(table().text()).toContain('真实库存30')
  }finally{wrapper.unmount()}
})
it('new receiving offers optional cost and no redundant category/spec/alert fields', async () => {
  const wrapper=mount(InventoryView,{global:{plugins:[ElementPlus]}})
  try {
    await flushPromises();await wrapper.get('[data-testid="stock-new"]').trigger('click')
    const vm=wrapper.vm as any
    Object.assign(vm.masterForm,{name:'新库存',base_unit:'袋',package_unit:'箱',units_per_package:'200',
      opening_quantity:'4',opening_unit:'package'})
    await flushPromises()
    vm.masterForm.unit_cost='120'
    await flushPromises()
    const labels=wrapper.findAll('.el-form-item__label').map(row=>row.text())
    expect(labels).not.toContain('分类');expect(labels).not.toContain('包装规格')
    expect(wrapper.get('[data-testid="opening-cost-preview"]').text()).toContain('480.00')
    await wrapper.get('[data-testid="stock-save"]').trigger('click');await flushPromises()
    expect(writes[0].unit_cost).toBe('120')
    expect(writes[0]).not.toHaveProperty('category')
    expect(writes[0]).not.toHaveProperty('package_spec')
    expect(writes[0]).not.toHaveProperty('low_stock_threshold')
  }finally{wrapper.unmount()}
})
