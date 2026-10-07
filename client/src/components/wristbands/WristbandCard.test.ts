import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import * as icons from '@element-plus/icons-vue'
import WristbandCard from './WristbandCard.vue'

it('a service employee can open the bill but sees no wristband management actions', async () => {
  const wrapper = mount(WristbandCard, { props: { row: { id: 'band', number: '8001', status: 'in_use',
    visit_id: 'visit', amount: '10.00', version: 1 }, selected: false, batchActive: false,
    selectable: false, elapsed: '00:01:00', canManage: false }, global: { plugins: [ElementPlus], components: icons } })
  expect(wrapper.text()).not.toContain('换牌')
  expect(wrapper.text()).not.toContain('挂失')
  await wrapper.find('article').trigger('keydown', { key: 'Enter' })
  expect(wrapper.emitted('primary')).toHaveLength(1)
  wrapper.unmount()
})
