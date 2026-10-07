import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'
import { dataOf, errorMessage, http } from '../api'
import { assertCurrent, businessGeneration, canAccess, onBusinessSessionClear } from '../business/state'
import { clearPendingOperationKey, orderFingerprint, pendingOperationKey, type PendingOrderItem } from '../idempotency'
import { reportRange } from '../mobile-management'
import { clampOrderQuantities } from '../order-selection'
import { useConnectivityStore } from './connectivity'
import { useSessionStore } from './session'
import type { Consumable, Consumption, StockItem, MobileBootstrap, MobileCatalogItem, MobileManagementReport, MobileWristband } from '../types'
import type { MobileRefreshDomain } from '../realtime/events'

export const useBusinessStore = defineStore('mobile-business', () => {
  const wristbands = ref<MobileWristband[]>([])
  const catalog = ref<MobileCatalogItem[]>([])
  const report = ref<MobileManagementReport | null>(null)
  const reportDays = ref<1 | 7 | 30>(1)
  const inventory = ref<StockItem[]>([])
  const consumables = ref<Consumable[]>([])
  const materials = ref<Record<string, Consumption[]>>({})
  const materialDrafts = new Map<string, Record<string, Consumption[]>>()
  const loading = ref(false)
  const sending = ref(false)
  const inventorySaving = ref(false)
  const error = ref('')
  const selectedVisitId = ref('')
  const quantities = ref<Record<string, number>>({})
  const visitDrafts = new Map<string, Record<string, number>>()
  const pendingOrders = reactive(new Map<string, { visitId: string; version?: number; items: PendingOrderItem[]; key: string; fingerprint: string; confirmReplace:boolean }>())
  let bootstrapOperation = 0; let reportOperation = 0; let inventoryOperation = 0
  let consumablesOperation = 0
  let loadingOperation = 0
  const busyOperations = { order: 0, inventory: 0 }
  const businessBusy = computed(() => sending.value ? '正在提交点单' : inventorySaving.value ? '正在提交库存入库' : null)

  function beginBusinessOperation(kind: 'order' | 'inventory') {
    const generation = businessGeneration.capture()
    const owned = ++busyOperations[kind]
    const flag = kind === 'order' ? sending : inventorySaving
    flag.value = true
    return () => {
      if (businessGeneration.isCurrent(generation) && busyOperations[kind] === owned) flag.value = false
    }
  }

  async function refreshBootstrap(silent = false) {
    const generation = businessGeneration.capture()
    const owned = ++bootstrapOperation
    const loadingOwned = ++loadingOperation
    const current = () => businessGeneration.isCurrent(generation) && owned === bootstrapOperation
    if (!silent) loading.value = true
    try {
      const data = dataOf<MobileBootstrap>(await http.get('/mobile/bootstrap'))
      assertCurrent(generation)
      if (!current()) return data
      wristbands.value = data.wristbands
      catalog.value = data.catalog
      if (selectedVisitId.value) visitDrafts.set(selectedVisitId.value, { ...quantities.value })
      const active = new Set(data.wristbands.map(row => row.visit_id))
      for (const id of visitDrafts.keys()) {
        if (!active.has(id)) { visitDrafts.delete(id); materialDrafts.delete(id) }
        else visitDrafts.set(id, clampOrderQuantities(data.catalog, visitDrafts.get(id)!))
      }
      quantities.value = clampOrderQuantities(data.catalog, quantities.value)
      useSessionStore().setEmployee(data.employee)
      useConnectivityStore().markSynced()
      if (selectedVisitId.value && !data.wristbands.some((row) => row.visit_id === selectedVisitId.value)) {
        selectedVisitId.value = ''
        quantities.value = {}
        materials.value = {}
      }
      error.value = ''
      return data
    } catch (cause) {
      if (!current()) throw cause
      useConnectivityStore().apiReachable = false
      error.value = errorMessage(cause)
      throw cause
    } finally { if (businessGeneration.isCurrent(generation) && loadingOwned === loadingOperation) loading.value = false }
  }

  async function loadReport(days: 1 | 7 | 30, silent = false) {
    const generation = businessGeneration.capture()
    const owned = ++reportOperation
    const loadingOwned = ++loadingOperation
    const current = () => businessGeneration.isCurrent(generation) && owned === reportOperation
    if (!silent) loading.value = true
    reportDays.value = days
    try { const data = dataOf<MobileManagementReport>(await http.get('/mobile/management/report', { params: reportRange(days) })); assertCurrent(generation); if (!current()) return; report.value = data; useConnectivityStore().markSynced(); error.value = '' }
    catch (cause) { if (current()) { useConnectivityStore().apiReachable = false; error.value = errorMessage(cause) }; throw cause }
    finally { if (businessGeneration.isCurrent(generation) && loadingOwned === loadingOperation) loading.value = false }
  }

  async function loadInventory(silent = false) {
    const generation = businessGeneration.capture()
    const owned = ++inventoryOperation
    const loadingOwned = ++loadingOperation
    const current = () => businessGeneration.isCurrent(generation) && owned === inventoryOperation
    if (!silent) loading.value = true
    try { const data = dataOf<StockItem[]>(await http.get('/inventory/stock-items')); assertCurrent(generation); if (!current()) return; inventory.value = data; useConnectivityStore().markSynced(); error.value = '' }
    catch (cause) { if (current()) { useConnectivityStore().apiReachable = false; error.value = errorMessage(cause) }; throw cause }
    finally { if (businessGeneration.isCurrent(generation) && loadingOwned === loadingOperation) loading.value = false }
  }

  async function loadConsumables() {
    const generation = businessGeneration.capture()
    const owned = ++consumablesOperation
    const data = dataOf<Consumable[]>(await http.get('/inventory/consumables'))
    assertCurrent(generation)
    if (owned === consumablesOperation) consumables.value = data
  }

  async function refreshDomains(domains: MobileRefreshDomain[], silent = true) {
    const generation = businessGeneration.capture()
    const tasks: Promise<unknown>[] = []
    if (domains.includes('orders')) tasks.push(refreshBootstrap(silent))
    if (domains.includes('reports') && report.value) tasks.push(loadReport(reportDays.value, silent))
    if (domains.includes('inventory') && inventory.value.length) tasks.push(loadInventory(silent))
    if (domains.includes('inventory') && canAccess('mobile:order')) tasks.push(loadConsumables())
    await Promise.allSettled(tasks)
    if (businessGeneration.isCurrent(generation)) window.dispatchEvent(new CustomEvent('xiquan:domains-refreshed',{detail:domains}))
  }

  function selectVisit(visitId: string) {
    if (visitId === selectedVisitId.value) return
    if (selectedVisitId.value) {
      visitDrafts.set(selectedVisitId.value, { ...quantities.value })
      materialDrafts.set(selectedVisitId.value, JSON.parse(JSON.stringify(materials.value)))
    }
    selectedVisitId.value = visitId
    quantities.value = { ...visitDrafts.get(visitId) }
    materials.value = JSON.parse(JSON.stringify(materialDrafts.get(visitId) || {}))
  }

  function clearVisitDraft(visitId: string) {
    visitDrafts.delete(visitId)
    materialDrafts.delete(visitId)
    if (selectedVisitId.value === visitId) { quantities.value = {}; materials.value = {} }
  }

  function prepareOrder(visitId: string, version: number | undefined, items: PendingOrderItem[],confirmReplace=false) {
    const fingerprint = orderFingerprint(visitId, items)+'|replace:'+confirmReplace
    const previous = pendingOrders.get(visitId)
    if (previous && previous.fingerprint !== fingerprint) throw new Error('上一笔加单尚未确认，请先重试原选择')
    if (previous) return previous
    const target = Object.freeze({ visitId, version, fingerprint,confirmReplace,
      items: items.map(item => Object.freeze({ ...item, ...(item.inventory_consumption ? { inventory_consumption: item.inventory_consumption.map(row => Object.freeze({ ...row })) } : {}) })),
      key: pendingOperationKey(`order:${visitId}`, `${version}|${fingerprint}`) })
    pendingOrders.set(visitId, target)
    clearVisitDraft(visitId)
    return target
  }
  function pendingOrder(visitId: string) { return pendingOrders.get(visitId) }
  function completeOrder(visitId: string) {
    pendingOrders.delete(visitId); clearPendingOperationKey(`order:${visitId}`)
  }
  function rejectOrder(visitId: string, status?: number) {
    if (status && status >= 400 && status < 500) {
      const target=pendingOrders.get(visitId)
      if (target && selectedVisitId.value===visitId && !Object.values(quantities.value).some(value=>value>0)) {
        quantities.value=Object.fromEntries(target.items.map(row=>[row.catalog_item_id,Number(row.quantity)]))
        materials.value=Object.fromEntries(target.items.filter(row=>row.inventory_mode==='manual').map(row=>[row.catalog_item_id,row.inventory_consumption!.map(item=>({...item}))]))
      }
      pendingOrders.delete(visitId); clearPendingOperationKey(`order:${visitId}`)
    }
  }

  function reset() {
    busyOperations.order++; busyOperations.inventory++
    wristbands.value = []; catalog.value = []; report.value = null; inventory.value = []
    selectedVisitId.value = ''; quantities.value = {}; error.value = ''
    visitDrafts.clear()
    pendingOrders.clear()
    materialDrafts.clear(); materials.value = {}; consumables.value = []
    loading.value = false; sending.value = false; inventorySaving.value = false
  }
  onBusinessSessionClear(reset)

  return { beginBusinessOperation, businessBusy, catalog, clearVisitDraft, completeOrder, prepareOrder, pendingOrder, rejectOrder, error, inventory, consumables, materials, inventorySaving, loading, loadInventory, loadConsumables, loadReport, quantities, refreshBootstrap, refreshDomains, report, reportDays, reset, selectVisit, selectedVisitId, sending, wristbands }
})
