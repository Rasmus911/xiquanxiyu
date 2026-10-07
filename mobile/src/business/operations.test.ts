// @vitest-environment jsdom
import { afterEach, expect, test } from 'vitest'
import { createApp, nextTick, type App } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import VisitOrder from '../views/VisitOrderView.vue'
import Inventory from '../views/InventoryView.vue'
import { useBusinessStore } from '../stores/business'
import { useConnectivityStore } from '../stores/connectivity'
import { acceptBusinessState, clearBusinessSession } from './state'
import { useSessionStore } from '../stores/session'
import { http } from '../api'
let app: App; let host: HTMLDivElement
afterEach(() => { app?.unmount(); host?.remove() })
const item = { id: 'item1', kind: 'service' as const, name: '服务', category: '服务', mobile_scope: 'both' as const, price: '20', stock_tracked: false, stock_quantity: '0', low_stock_threshold: '0', sort_order: 1 }
const stock = {id:'stock1',name:'耗材',category:'耗材',base_unit:'袋',package_unit:'箱',units_per_package:'200',package_spec:'1*200',stock_quantity:'800',low_stock_threshold:'20',is_active:true,version:1}
function authorize(){acceptBusinessState({period_id:'test',policy_version:1,business_revision:1,maintenance:false,owner_reset_allowed:false},['mobile:order','inventory:read','inventory:write'])}
async function mountOperation(kind: 'order' | 'inventory', stale = false) {
  clearBusinessSession()
  authorize()
  const pinia = createPinia(); setActivePinia(pinia)
  const adapter=http.defaults.adapter as (config:any)=>Promise<any>
  http.defaults.adapter=async config=>{
    if(['/inventory/consumables','/inventory/stock-items','/inventory/usage','/inventory/stock-movements'].includes(config.url || ''))return {config,headers:{},status:200,statusText:'',data:{data:config.url==='/inventory/stock-items'?[stock]:[]}}
    return adapter(config)
  }
  useSessionStore().setEmployee({id:'e',username:'inventory',display_name:'库管',role:'inventory',role_label:'库管',capabilities:{inventory_manage:true,orders_view:true}})
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/work/:visitId', component: kind === 'order' ? VisitOrder : Inventory }, { path: '/orders', component: { template: '<p>已返回列表</p>' } }] })
  await router.push('/work/v1'); await router.isReady()
  const store = useBusinessStore()
  store.catalog = [item]; store.inventory = [stock]; store.wristbands = [{ number: '001', visit_id: 'v1', opened_at: new Date().toISOString(), amount: '20', bath_area: 'male' }]
  useConnectivityStore().markSynced()
  if (stale) useConnectivityStore().lastSyncAt = Date.now() - 31000
  host = document.createElement('div'); document.body.append(host)
  app = createApp({ template: '<router-view />' }); app.use(pinia); app.use(router); app.mount(host)
  await new Promise(resolve => setTimeout(resolve, 0))
  if (kind === 'order') { store.quantities = { item1: 1 }; store.materials={item1:[]}; await nextTick();(host.querySelector('.summary-bar button') as HTMLButtonElement).click();await nextTick() }
  else { store.inventory=[stock];await nextTick();(host.querySelector('[data-testid="stock-receive-stock1"]') as HTMLButtonElement).click(); await nextTick() }
  return { router, store, button: host.querySelector(kind === 'order' ? '[data-testid="confirm-consumption"]' : '.sheet .primary-button') as HTMLButtonElement }
}

test('inactive wristband navigation releases the shared order busy flag', async () => {
  http.defaults.adapter = async config => ({ config, headers: {}, status: 200, statusText: '', data: { data: { employee: { id: 'worker', username: 'worker', display_name: '员工', role: 'male_scrubber', role_label: '搓澡师', capabilities: {} }, wristbands: [], catalog: [item] } } })
  const { store, button } = await mountOperation('order', true)
  button.click(); await new Promise(resolve => setTimeout(resolve, 0)); await nextTick()
  expect(host.textContent).toContain('已返回列表')
  expect(store.sending).toBe(false)
  expect(store.businessBusy).toBeNull()
})

test.each([['order', 'resolve'], ['order', 'reject'], ['inventory', 'resolve'], ['inventory', 'reject']] as const)('unmounted pending %s %s releases only its own shared busy flag', async (kind, outcome) => {
  http.defaults.adapter = async config => ({ config, headers: {}, status: 200, statusText: '', data: { data: [item] } })
  const { router, store, button } = await mountOperation(kind)
  let finish!: () => void
  http.defaults.adapter = config => new Promise((resolve, reject) => { finish = () => outcome === 'resolve' ? resolve({ config, headers: {}, status: 200, statusText: '', data: { data: {} } }) : reject(new Error('request failed')) })
  button.click(); await Promise.resolve(); await Promise.resolve()
  await router.replace('/orders'); await nextTick()
  finish(); await new Promise(resolve => setTimeout(resolve, 0)); await nextTick()
  expect(store.sending).toBe(false); expect(store.inventorySaving).toBe(false); expect(store.businessBusy).toBeNull()
})

test.each(['order', 'inventory'] as const)('unmounted %s completion cannot release a newer same-session operation', async kind => {
  http.defaults.adapter = async config => ({ config, headers: {}, status: 200, statusText: '', data: { data: [item] } })
  const { router, store, button } = await mountOperation(kind)
  let finish!: () => void
  http.defaults.adapter = config => new Promise(resolve => { finish = () => resolve({ config, headers: {}, status: 200, statusText: '', data: { data: {} } }) })
  button.click(); await Promise.resolve(); await Promise.resolve(); await router.replace('/orders')
  const releaseNew = store.beginBusinessOperation(kind)
  finish(); await new Promise(resolve => setTimeout(resolve, 0))
  expect(kind === 'order' ? store.sending : store.inventorySaving).toBe(true)
  releaseNew()
  expect(kind === 'order' ? store.sending : store.inventorySaving).toBe(false)
})

test('an unmounted inventory rejection cannot release a newer session busy flag', async () => {
  http.defaults.adapter = async config => ({ config, headers: {}, status: 200, statusText: '', data: { data: [item] } })
  const { router, store, button } = await mountOperation('inventory')
  let reject!: (reason: Error) => void
  http.defaults.adapter = () => new Promise((_resolve, fail) => { reject = fail })
  button.click(); await Promise.resolve(); await Promise.resolve(); await router.replace('/orders')
  clearBusinessSession(); store.inventorySaving = true
  reject(new Error('old failure')); await new Promise(resolve => setTimeout(resolve, 0))
  expect(store.inventorySaving).toBe(true)
})
test.each(['resolve', 'reject'])('old mounted order %s cannot finalize a newer operation', async outcome => {
  clearBusinessSession()
  authorize()
  const pinia = createPinia(); setActivePinia(pinia)
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/orders/:visitId', component: VisitOrder }] })
  await router.push('/orders/v1'); await router.isReady()
  const store = useBusinessStore()
  store.catalog = [{ id: 'service1', kind: 'service', name: '服务', category: '服务', mobile_scope: 'both', price: '20', stock_tracked: false, stock_quantity: '0', low_stock_threshold: '0', sort_order: 1 }]
  store.wristbands = [{ number: '001', visit_id: 'v1', opened_at: new Date().toISOString(), amount: '20', bath_area: 'male' }]
  useConnectivityStore().markSynced()
  host = document.createElement('div'); document.body.append(host)
  http.defaults.adapter=async config=>({config,headers:{},status:200,statusText:'',data:{data:[]}})
  app = createApp(VisitOrder); app.use(pinia); app.use(router); app.mount(host)
  store.quantities = { service1: 1 };store.materials={service1:[]}; await nextTick()
  let finish!: () => void
  http.defaults.adapter = config => new Promise((resolve, reject) => { finish = () => outcome === 'resolve' ? resolve({ config, headers: {}, status: 200, statusText: '', data: { data: {} } }) : reject(new Error('old failure')) })
  ;(host.querySelector('.summary-bar button') as HTMLButtonElement).click()
  await nextTick()
  ;(host.querySelector('[data-testid="confirm-consumption"]') as HTMLButtonElement).click()
  await Promise.resolve(); await Promise.resolve()
  clearBusinessSession(); store.sending = true; store.quantities = { newer: 2 }
  localStorage.setItem('xiquan_mobile_pending_order_key', 'new-key')
  finish(); await new Promise(resolve => setTimeout(resolve, 0)); await nextTick()
  expect(store.sending).toBe(true)
  expect(store.quantities).toEqual({ newer: 2 })
  expect(localStorage.getItem('xiquan_mobile_pending_order_key')).toBe('new-key')
})
