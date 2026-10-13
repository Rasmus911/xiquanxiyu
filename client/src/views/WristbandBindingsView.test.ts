import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { createPinia } from 'pinia'
import { acceptBusinessState, clearBusinessSession } from '../business/state'
import { http } from '../api/http'
import WristbandBindingsView from './WristbandBindingsView.vue'

const originalAdapter = http.defaults.adapter
afterEach(() => { http.defaults.adapter = originalAdapter; clearBusinessSession(); ElMessage.closeAll(); vi.restoreAllMocks() })
it('shows the hundred physical bands and saves the selected zero-prefixed chip without admission', async () => {
  const rows = Array.from({ length:100 }, (_, index) => ({ wristband_id: 'band-' + index,
    number:String(index+1).padStart(3,'0'), bath_area:index<50?'male':'female', status:'available',
    chip_uid:null, version:0, updated_at:null }))
  const writes: Array<{url?:string;body:unknown}> = []
  http.defaults.adapter = async config => {
    if (config.method === 'put') { writes.push({url:config.url,body:JSON.parse(config.data)}); Object.assign(rows[0]!,{chip_uid:'000315346091',version:1}) }
    return {config,headers:{},status:200,statusText:'OK',data:{success:true,data:structuredClone(config.method==='get'?rows:rows[0])}}
  }
  acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,
    owner_reset_allowed:false,ui_pages:['wristband-bindings'],capabilities:{wristband_bind:true}},['wristband:bind'])
  const wrapper = mount(WristbandBindingsView,{attachTo:document.body,global:{plugins:[createPinia(),ElementPlus]}})
  try {
    await flushPromises(); expect(wrapper.text()).toContain('未录入 100')
    await wrapper.find('[data-testid="bind-chip"]').trigger('click'); await flushPromises()
    const input = document.querySelector('[data-testid="chip-uid"]') as HTMLInputElement
    input.value='000315346091'; input.dispatchEvent(new Event('input',{bubbles:true})); await flushPromises()
    ;(document.querySelector('[data-testid="save-chip"]') as HTMLButtonElement).click(); await flushPromises()
    expect(writes).toEqual([{url:'/wristband-reader/bindings/band-0',body:{chip_uid:'000315346091',version:0}}])
    expect(wrapper.text()).toContain('已录入 1')
  } finally { wrapper.unmount() }
})

it('no binding capability never requests physical identities', async () => {
  const adapter = vi.fn(); http.defaults.adapter=adapter
  acceptBusinessState({period_id:'fixture',policy_version:1,business_revision:0,maintenance:false,
    owner_reset_allowed:false,ui_pages:[],capabilities:{wristband_bind:false}},['inventory:read'])
  const wrapper = mount(WristbandBindingsView,{global:{plugins:[createPinia(),ElementPlus]}})
  try { await flushPromises(); expect(adapter).not.toHaveBeenCalled(); expect(wrapper.text()).toContain('无手牌 ID 录入权限') }
  finally { wrapper.unmount() }
})
