import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { expect, it } from 'vitest'
import AdmissionDialog from './AdmissionDialog.vue'
import type { CatalogItem } from '../../types'

const tickets = [
  { id: 'adult', kind: 'ticket', reference_code: 'ticket.adult', name: '门票', price: '15.00', is_active: true },
  { id: 'child', kind: 'ticket', reference_code: 'ticket.child', name: '儿童门票（一米以下）', price: '10.00', is_active: true },
] as CatalogItem[]
it('one child radio changes only that guest and confirmation contains no money', async () => {
  const wrapper = mount(AdmissionDialog, { props: { modelValue: true, tickets,
    bands: [{ id: 'a', number: '001' }, { id: 'b', number: '051' }] },
    global: { plugins: [ElementPlus], stubs: { teleport: true } } })
  try {
    await flushPromises()
    await wrapper.find('[data-band-id="b"] input[value="child"]').setValue()
    await wrapper.find('[data-testid="confirm-admission"]').trigger('click')
    expect(wrapper.emitted('confirm')?.[0]).toEqual([{ a: 'adult', b: 'child' }])
    expect(wrapper.text()).toContain('15.00')
    expect(wrapper.text()).toContain('10.00')
  } finally { wrapper.unmount() }
})
it('unavailable tickets cannot produce a partial or guessed admission request', async () => {
  const wrapper = mount(AdmissionDialog, { props: { modelValue: true, tickets: [], bands: [{ id: 'a', number: '001' }] },
    global: { plugins: [ElementPlus], stubs: { teleport: true } } })
  try {
    await flushPromises()
    expect(wrapper.find('[data-testid="confirm-admission"]').attributes('disabled')).toBeDefined()
    expect(wrapper.emitted('confirm')).toBeUndefined()
  } finally { wrapper.unmount() }
})

it('a live server price refresh keeps the selected child ticket for the same guest', async () => {
  const wrapper=mount(AdmissionDialog,{props:{modelValue:true,tickets,bands:[{id:'a',number:'001'}]},
    global:{plugins:[ElementPlus],stubs:{teleport:true}}})
  try {
    await flushPromises()
    await wrapper.find('[data-band-id="a"] input[value="child"]').setValue()
    await wrapper.setProps({tickets:tickets.map(row=>({...row,price:row.id==='adult' ? '18.00' : row.price}))})
    await wrapper.find('[data-testid="confirm-admission"]').trigger('click')
    expect(wrapper.emitted('confirm')?.[0]).toEqual([{a:'child'}])
    expect(wrapper.text()).toContain('18.00')
  } finally {wrapper.unmount()}
})
