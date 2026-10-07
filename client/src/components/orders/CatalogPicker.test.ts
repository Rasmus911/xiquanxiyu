import { expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { http } from '../../api/http'
import ElementPlus from 'element-plus'
import CatalogPicker from './CatalogPicker.vue'

const items = [
  { id: 's', kind: 'service', name: '搓澡', category: '洗浴', is_active: true, price: '10', sort_order: 10 },
  { id: 'p', kind: 'product', name: '澡巾', category: '洗浴', is_active: true, price: '6', sort_order: 20, stock_tracked: true, stock_quantity: '10' },
  { id: 'zero', kind: 'product', name: '备品', category: '洗浴', is_active: true, price: '7', sort_order: 30, stock_tracked: true, stock_quantity: '0' },
] as any
it('starts mixed, product stepper does not also select, and depleted products cannot be sold', async () => {
  const wrapper = mount(CatalogPicker, { props: { items, quantities: {} }, global: { plugins: [ElementPlus] } })
  try {
    expect(wrapper.findAll('article').map(node => node.find('strong').text())).toEqual(['搓澡', '澡巾', '备品'])
    const plus = wrapper.findAll('article')[1]!.find('.el-input-number__increase')
    await plus.trigger('mousedown', { button: 0 })
    document.dispatchEvent(new MouseEvent('mouseup'))
    await plus.trigger('click')
    expect(wrapper.emitted('quantity')?.[0]?.[1]).toBe(1)
    expect(wrapper.emitted('select')).toBeUndefined()
    await wrapper.findAll('article')[2]!.trigger('click')
    expect(wrapper.emitted('select')).toBeUndefined()
    await wrapper.findAll('article')[0]!.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('select')?.[0]?.[0]).toMatchObject({ id: 's' })
  } finally { wrapper.unmount() }
})

it('administrator keyboard arrangement includes depleted items, never changes sales and cancellation does not PUT', async () => {
  const writes: any[] = []
  http.defaults.adapter = async config => {
    if (config.method === 'put') writes.push(JSON.parse(config.data))
    return { config, headers: {}, status: 200, statusText: '', data: { data: { revision: 2,
      ids: config.method === 'put' ? JSON.parse(config.data).ids : ['s', 'p', 'zero'] } } }
  }
  const wrapper = mount(CatalogPicker, { props: { items, quantities: { s: 1 }, canArrange: true } as any, global: { plugins: [ElementPlus] } })
  try {
    await wrapper.find('[data-testid="arrange-start"]').trigger('click'); await flushPromises()
    await wrapper.find('[aria-label="上移备品"]').trigger('click')
    expect(wrapper.findAll('article').map(row => row.find('strong').text())).toEqual(['搓澡', '备品', '澡巾'])
    await wrapper.findAll('article')[0]!.trigger('click')
    expect(wrapper.emitted('select')).toBeUndefined()
    expect(wrapper.props('quantities')).toEqual({ s: 1 })
    await wrapper.find('[data-testid="arrange-cancel"]').trigger('click'); expect(writes).toEqual([])
    await wrapper.find('[data-testid="arrange-start"]').trigger('click'); await flushPromises()
    await wrapper.find('[aria-label="上移备品"]').trigger('click')
    await wrapper.find('[data-testid="arrange-save"]').trigger('click'); await flushPromises()
    expect(writes).toEqual([{ revision: 2, ids: ['s', 'zero', 'p'] }])
  } finally { wrapper.unmount(); vi.restoreAllMocks() }
})
