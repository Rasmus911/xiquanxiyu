import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import ElementPlus from 'element-plus'
import { afterEach, expect, it } from 'vitest'
import CardScanDialog from './CardScanDialog.vue'

let cleanup = () => {}
afterEach(() => { cleanup(); document.body.innerHTML = '' })
async function render() {
  const host = defineComponent({ components: { CardScanDialog }, setup() {
    return { open: ref(true), busy: ref(false), payments: ref(0), reads: ref<string[]>([]) }
  }, template: '<form @submit.prevent="payments++" @keydown.enter="payments++"><CardScanDialog v-model="open" :busy="busy" @read="reads.push($event)" /><input name="other" /></form>' })
  const w = mount(host, { attachTo: document.body, global: { plugins: [ElementPlus], stubs: { teleport: true } } })
  cleanup = () => w.unmount(); await flushPromises(); return w
}
it('reads leading zero UID once from real ElInput and stops parent Enter payment', async () => {
  const w = await render(), scan = w.findComponent(CardScanDialog), input = scan.find('input')
  expect(document.activeElement).toBe(input.element)
  await input.setValue('000315346091'); await input.trigger('keydown', { key: 'Enter' }); await input.trigger('keydown', { key: 'Enter' })
  expect(w.vm.reads).toEqual(['000315346091']); expect(w.vm.payments).toBe(0)
  w.vm.busy = true; await flushPromises(); await input.trigger('keydown', { key: 'Enter' }); expect(w.vm.reads).toHaveLength(1)
})
it('allows correction, clears on reopen, and never steals focus after blur', async () => {
  const w = await render(), input = w.findComponent(CardScanDialog).find('input')
  await input.setValue('31 5346091'); await input.trigger('keydown', { key: 'Enter' }); expect(w.vm.reads).toEqual([])
  await input.setValue('315346091'); await input.trigger('keydown', { key: 'Enter' }); expect(w.vm.reads).toEqual(['315346091'])
  const cancel = w.findComponent(CardScanDialog).find('.el-dialog__footer button')
  ;(cancel.element as HTMLButtonElement).focus(); await input.trigger('blur'); await flushPromises()
  expect(document.activeElement).toBe(cancel.element)
  w.vm.open = false; await flushPromises(); w.vm.open = true; await flushPromises()
  expect((w.findComponent(CardScanDialog).find('input').element as HTMLInputElement).value).toBe('')
  await w.findComponent(CardScanDialog).find('input').trigger('keydown', { key: 'Escape' })
  expect(w.vm.open).toBe(false)
})
