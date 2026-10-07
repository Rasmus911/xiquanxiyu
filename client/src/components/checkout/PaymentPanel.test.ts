import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { expect, it } from 'vitest'
import PaymentPanel from './PaymentPanel.vue'

it('exposes four payment labels and one-click gap fill, with all controls locked during payment', async () => {
  const wrapper = mount(PaymentPanel, { props: {
    payments: ['cash','wechat','alipay','balance'].map(method => ({ method, amount: 0, reference: '' })),
    total: '160.00', paid: '60.00', balanced: false, remaining: '100.00', overpaid: '0.00',
  }, global: { plugins: [ElementPlus] } })
  try {
    expect(wrapper.text()).toContain('还需收款')
    expect(wrapper.text()).toContain('100.00')
    const buttons = wrapper.findAll('[data-testid="fill-payment"]')
    expect(buttons).toHaveLength(4)
    await buttons[2].trigger('click')
    expect(wrapper.emitted('fill')).toEqual([[2]])
    await wrapper.setProps({ disabled: true })
    expect(wrapper.findAll('input').every(input => input.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.findAll('[data-testid="fill-payment"]').every(button => button.attributes('disabled') !== undefined)).toBe(true)
  } finally { wrapper.unmount() }
})
