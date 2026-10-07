<script setup lang="ts">
import { businessState, onBusinessSessionClear, canCapability, useBusinessGuard } from '../business/state'
const guardBusinessOperation = useBusinessGuard()

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiData, apiErrorMessage, http } from '../api/http'
import AppPageHeader from '../components/app/AppPageHeader.vue'
import CatalogPicker from '../components/orders/CatalogPicker.vue'
import OrderCart from '../components/orders/OrderCart.vue'
import PartyTabs from '../components/orders/PartyTabs.vue'
import ConsumptionEditor from '../components/orders/ConsumptionEditor.vue'
import { buildManualConsumption } from '../domain/orders/consumption'
import AdmissionDialog from '../components/wristbands/AdmissionDialog.vue'
import { useAdmissionDialog } from '../composables/useAdmissionDialog'
import { setOrderQuantity, toggleOrderItem } from '../domain/orders/selection'
import { togglePackageSelection } from '../domain/orders/package-selection'
import { useVisitOrdering } from '../composables/useVisitOrdering'
import type { SubmissionSnapshot } from '../domain/orders/visit-drafts'
import { clearPendingRequestKey, pendingRequestKey } from '../domain/requests/pending-key'
import { subscribeRealtime } from '../realtime/events'
import { useConnectivityStore } from '../stores/connectivity'
import { useRuntimeStore } from '../stores/runtime'
import type { CatalogItem, Visit, Consumable, ManualConsumption } from '../types'
import { formatBusinessTime } from '../format/business-time'

const route = useRoute()
const router = useRouter()
const connectivity = useConnectivityStore()
const runtime = useRuntimeStore()
const ordering = useVisitOrdering()
const visit = ordering.currentVisit
const catalog = ref<CatalogItem[]>([])
const consumables = ref<Consumable[]>([])
const consumptions = ref<Record<string, ManualConsumption[] | undefined>>({})
const materialsDialog = ref(false)
const confirmingMaterials = ref(false)
const materialTarget = ref<SubmissionSnapshot | null>(null)
const materialItems = ref<CatalogItem[]>([])
const materialBand = ref('')
let materialCurrent: (() => boolean) | undefined
function closeMaterials() {
  materialsDialog.value = false
  confirmingMaterials.value = false
  materialTarget.value = null
  materialItems.value = []
  consumptions.value = {}
  materialCurrent = undefined
}
onBusinessSessionClear(closeMaterials)
watch([
  () => businessState.value?.period_id,
  () => businessState.value?.policy_version,
  () => businessState.value?.maintenance,
  () => canCapability('visit_order'),
], closeMaterials)
const loading = ordering.loading
const adding = ref(false)
const layoutEditing = ref(false)
const admission = useAdmissionDialog()
const changingTicket = ref(false)
const draftRevision = ref(0)
const selectedQuantities = computed({
  get: () => { void draftRevision.value; return ordering.drafts.read(String(route.params.id)) },
  set: values => { ordering.drafts.replace(String(route.params.id), values); draftRevision.value++ },
})
let refreshTimer: number | undefined
let unsubscribeRealtime: (() => void) | undefined
let clockTimer: number | undefined
const clockNow = ref(Date.now())
const linkedVisits = computed(() => visit.value?.linked_visits?.length ? visit.value.linked_visits : (visit.value ? [visit.value] : []))
const linkedItems = computed(() => linkedVisits.value.flatMap((linkedVisit) =>
  linkedVisit.items.map((item) => ({ ...item, wristband_number: linkedVisit.wristband_number })),
))
const displayedTotal = computed(() => visit.value?.linked_total_amount || visit.value?.total_amount || '0.00')
const selectedKindCount = computed(() => Object.values(selectedQuantities.value).filter((quantity) => quantity > 0).length)
const selectedCount = computed(() => Object.values(selectedQuantities.value).reduce((total, quantity) => total + quantity, 0))
const pendingOrder = computed(() => ordering.pendingTarget(String(route.params.id)))

function elapsed(openedAt?: string) {
  if (!openedAt) return ''
  const seconds = Math.max(0, Math.floor((clockNow.value - new Date(openedAt).getTime()) / 1000))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor(seconds % 3600 / 60)
  const remain = seconds % 60
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remain).padStart(2, '0')}`
}

async function load(silent = false) {
  const id = String(route.params.id)
  const isCurrent = guardBusinessOperation('catalog')
  if (!isCurrent()) return
  const detail = ordering.load(id)
  try {
    const [result, stock] = await Promise.all([http.get('/catalog', { params: { active: true } }), canCapability('visit_order') ? http.get('/inventory/consumables') : Promise.resolve(null)])
    if (!isCurrent()) return
    catalog.value = apiData<CatalogItem[]>(result)
    consumables.value = stock ? apiData<Consumable[]>(stock) : []
  } catch (error) { if (!isCurrent()) return;
    if (!silent) ElMessage.error(apiErrorMessage(error))
  } finally { await detail }
}

function selectedQuantity(itemId: string) {
  return selectedQuantities.value[itemId] || 0
}

function setQuantity(item: CatalogItem, value: number | undefined) {
  if (materialsDialog.value || adding.value || loading.value || !canCapability('visit_order')) return
  if(item.kind === 'package') return
  const maximum = item.kind === 'service' ? 1 : 99
  selectedQuantities.value = setOrderQuantity(selectedQuantities.value, item.id, Number(value || 0), maximum)
}

function selectItem(item: CatalogItem) {
  if (materialsDialog.value || adding.value || loading.value || !canCapability('visit_order')) return
  if(item.kind==='package') {
    if(!canCapability('package_write')) return
    selectedQuantities.value=togglePackageSelection(selectedQuantities.value,catalog.value,item.id)
    return
  }
  const maximum = item.kind === 'service' ? 1 : 99
  selectedQuantities.value = toggleOrderItem(selectedQuantities.value, { id: item.id, kind: item.kind as 'service' | 'product', maximum })
}

function clearSelectedItems() {
  if (materialsDialog.value || adding.value) return
  selectedQuantities.value = {}
  consumptions.value = {}
}

async function addSelectedItems() {
  if (materialsDialog.value || adding.value || layoutEditing.value || !connectivity.isOnline || !canCapability('visit_order')) return
  const isCurrent = guardBusinessOperation('addSelectedItems')
  if (!isCurrent()) return

  if (!visit.value || visit.value.id !== String(route.params.id) || loading.value) return
  if (pendingOrder.value) return ElMessage.warning('上一笔加单尚未确认，请点击“重试原操作”')
  if (!selectedCount.value) return ElMessage.warning('请先选择要添加的项目')
  materialTarget.value = ordering.drafts.capture(visit.value.id, visit.value.version)
  materialItems.value = catalog.value.filter(item => materialTarget.value!.quantities[item.id]).map(item => ({...item}))
  materialBand.value = visit.value.wristband_number
  consumptions.value = {}
  materialCurrent = isCurrent
  materialsDialog.value = true
}

async function confirmMaterials() {
  if (confirmingMaterials.value || adding.value || !materialsDialog.value || !materialTarget.value || !connectivity.isOnline || !canCapability('visit_order')) return
  const isCurrent = materialCurrent
  let target = materialTarget.value
  if (!isCurrent?.() || target.visitId !== String(route.params.id) || visit.value?.id !== target.visitId) { closeMaterials(); return }
  const materials: Record<string, readonly ManualConsumption[]> = {}
  try {
    for (const id of Object.keys(target.quantities)) {
      const rows = consumptions.value[id]
      if (rows === undefined) throw new Error('请为每个项目选择耗材，或明确勾选本行无耗材')
      materials[id] = Object.freeze(buildManualConsumption(rows).inventory_consumption.map(row => Object.freeze(row)))
    }
  } catch (error) { return ElMessage.warning(apiErrorMessage(error)) }
  target = Object.freeze({...target, consumptions: Object.freeze(materials)})
  const selectedPackage=materialItems.value.find(item=>item.kind==='package' && target.quantities[item.id])
  const currentPackage=visit.value.items.find(item=>item.kind==='package' && item.status==='active')
  if(selectedPackage && currentPackage && selectedPackage.id!==currentPackage.catalog_item_id) {
    confirmingMaterials.value = true
    try {
      await ElMessageBox.confirm(`将当前手牌的套票更换为${selectedPackage.name}？未结账包含项目会重新计算。`,'更换套票',
        {confirmButtonText:'确认更换',cancelButtonText:'取消',type:'warning'})
    } catch { if(materialCurrent===isCurrent)confirmingMaterials.value=false; return }
    if(!isCurrent() || !materialsDialog.value || String(route.params.id)!==target.visitId || adding.value) return
    target=Object.freeze({...target,confirmReplace:true})
  }
  closeMaterials()
  // Preserve the exact submitted choices so retry compares the draft with the saved operation.
  consumptions.value = Object.fromEntries(Object.entries(target.consumptions || {}).map(([id, rows]) => [id, rows.map(row=>({...row}))]))
  await submitOrder(target, isCurrent)
}

async function retryOriginalOrder() {
  if (adding.value || layoutEditing.value || loading.value || !connectivity.isOnline || !canCapability('visit_order')) return
  const target = pendingOrder.value
  if (!target || !visit.value || visit.value.id !== target.visitId || target.visitId !== String(route.params.id)) return
  const isCurrent = guardBusinessOperation('addSelectedItems')
  if (!isCurrent()) return
  // A new form is separate from the saved operation. Only clear a form that still
  // represents the original selection, never one edited after the lost reply.
  const sameDraft = JSON.stringify(selectedQuantities.value) === JSON.stringify(target.quantities) &&
    JSON.stringify(consumptions.value) === JSON.stringify(target.consumptions || {})
  await submitOrder(target, isCurrent, true, sameDraft)
}

async function submitOrder(target: SubmissionSnapshot, isCurrent: () => boolean, retry = false, clearDraft = true) {
  adding.value = true
  let releaseBusy = async () => {}
  try {
    releaseBusy = await runtime.setBusinessBusy(retry ? '正在重试原加单' : '正在提交加单')
    if (!isCurrent()) return
    if (retry) await ordering.retryPending(target.visitId)
    else await ordering.submitSnapshot(target)
    if (!isCurrent()) return
    ElMessage.success(`已添加 ${target.kinds} 种，共 ${target.units} 份`)
    if (clearDraft) {
      ordering.drafts.clear(target.visitId); draftRevision.value++
      if (String(route.params.id) === target.visitId) consumptions.value = {}
    }
    await load(); if (!isCurrent()) return;
  } catch (error) { if (!isCurrent()) return; 
    ElMessage.error(apiErrorMessage(error))
  } finally {
    if (isCurrent()) adding.value = false
    await releaseBusy()
  }
}

async function voidItem(itemId: string) {
  const isCurrent = guardBusinessOperation('voidItem')
  if (!isCurrent()) return
  const visitId = String(route.params.id)

  try {
    const isPackage=visit.value?.items.some(item=>item.id===itemId && item.kind==='package')
    await ElMessageBox.confirm(isPackage ? '取消套票后，现有包含项目将恢复单项收费，已售商品库存不变。确定取消吗？' : '确定撤销这个消费项目吗？', isPackage ? '取消套票' : '撤销消费项目', { type: 'warning', confirmButtonText: '确定撤销', cancelButtonText: '取消' }); if (!isCurrent()) return;
    const scope = `visit:${visitId}:void:${itemId}`
    const key = pendingRequestKey(scope, `${visitId}|${itemId}|void`)
    await http.post(`/visits/${visitId}/items/${itemId}/void`, { idempotency_key: key }, { headers: { 'Idempotency-Key': key } }); if (!isCurrent()) return;
    clearPendingRequestKey(scope)
    ElMessage.success('项目已撤销')
    await load(); if (!isCurrent()) return;
  } catch (error) { if (!isCurrent()) return; 
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error))
  }
}

function checkout(scope: 'party' | 'selected' = 'party') {
  router.push({ path: '/checkout', query: { visits: String(route.params.id), scope, returnTo: router.currentRoute.value.fullPath } })
}

function selectPartyVisit(visitId: string) {
  if (materialsDialog.value || adding.value || loading.value) return
  void router.push({ path: `/visits/${visitId}`, query: { returnTo: String(route.query.returnTo || '/') } })
}

async function changeTicket() {
  const current = visit.value
  if (!current || current.id !== String(route.params.id) || changingTicket.value || adding.value ||
      loading.value || layoutEditing.value || !connectivity.isOnline || !canCapability('visit_manage')) return
  const target = { id: current.id, version: current.version, number: current.wristband_number }
  const isCurrent = guardBusinessOperation('changeTicket')
  const existing = current.items.find(item => item.kind === 'ticket' && item.status === 'active')
  const selected = await admission.open([{ id: target.id, number: target.number }], '更改当前手牌门票',
    '只更改这一位的票种；旧门票保留撤销记录，不改变同组其他人。',
    existing?.catalog_item_id ? { [target.id]: existing.catalog_item_id } : {})
  if (!selected || !isCurrent() || String(route.params.id) !== target.id) return
  const requestScope = `visit:${target.id}:ticket`
  const body = { ticket_catalog_item_id: selected[target.id], version: target.version }
  const key = pendingRequestKey(requestScope, JSON.stringify(body))
  changingTicket.value = true
  let releaseBusy = async () => {}
  try {
    releaseBusy = await runtime.setBusinessBusy('正在更改门票')
    if (!isCurrent() || String(route.params.id) !== target.id) return
    await http.patch(`/visits/${target.id}/ticket`, { ...body, idempotency_key: key })
    if (!isCurrent()) return
    clearPendingRequestKey(requestScope, key)
    if (String(route.params.id) !== target.id) return
    ElMessage.success('门票已更改')
    await load(true)
  } catch (error) {
    if (!isCurrent()) return
    const status = (error as { response?: { status: number } }).response?.status
    if (status && status >= 400 && status < 500) clearPendingRequestKey(requestScope, key)
    ElMessage.error(apiErrorMessage(error))
  } finally {
    changingTicket.value = false
    await releaseBusy()
  }
}

watch(selectedQuantities, (values, previous) => {
  consumptions.value = Object.fromEntries(Object.entries(consumptions.value).filter(([id]) => values[id] && values[id] === previous[id]))
})
watch(() => route.params.id, () => { closeMaterials(); admission.close(); void load() }, { immediate: true })
onMounted(() => {
  unsubscribeRealtime = subscribeRealtime(['visits', 'wristbands', 'catalog', 'inventory', 'checkout'], () => load(true))
  refreshTimer = window.setInterval(() => {
    if (!connectivity.isOnline && document.visibilityState === 'visible') load(true)
  }, 30_000)
  clockTimer = window.setInterval(() => { clockNow.value = Date.now() }, 1_000)
})

onBeforeUnmount(() => {
  unsubscribeRealtime?.()
  if (refreshTimer) window.clearInterval(refreshTimer)
  if (clockTimer) window.clearInterval(clockTimer)
})
</script>

<template>
  <div class="page">
    <AdmissionDialog :model-value="admission.visible.value" :bands="admission.bands.value" :tickets="catalog"
      :title="admission.title.value" :description="admission.description.value" :initial="admission.initial.value"
      @confirm="admission.close($event)" @cancel="admission.close()" />
    <AppPageHeader :title="`${visit?.wristband_number || '—'} 号手牌`" :description="`开单时间：${formatBusinessTime(visit?.opened_at)} · 已使用 ${elapsed(visit?.opened_at)}`" eyebrow="ACTIVE ORDER">
      <template #actions>
        <span class="bill-total">{{ linkedVisits.length > 1 ? '联动合计' : '合计' }} ¥{{ displayedTotal }}</span>
        <el-button v-if="canCapability('visit_manage')" data-testid="change-ticket" :disabled="changingTicket || adding || layoutEditing || loading || !connectivity.isOnline" @click="changeTicket">更改门票</el-button>
        <el-button v-if="canCapability('checkout_write') && linkedVisits.length > 1" type="success" plain size="large" @click="checkout('selected')">当前手牌单独结账（¥{{ visit?.total_amount }}）</el-button>
        <el-button v-if="canCapability('checkout_write')" type="success" size="large" @click="checkout('party')">{{ linkedVisits.length > 1 ? '联动整组结账' : '结账' }}</el-button>
      </template>
    </AppPageHeader>
    <PartyTabs :visits="linkedVisits" :current-id="String(route.params.id)" :elapsed="elapsed" :disabled="materialsDialog || adding || loading" @select="selectPartyVisit" />
    <el-alert v-if="ordering.error.value" :title="ordering.error.value" type="error" :closable="false" />
    <el-row :gutter="18" v-loading="loading">
      <el-col :xs="24" :lg="14">
        <el-card shadow="never">
          <template #header>
            <div data-testid="quick-order-header" class="quick-order-header">
              <div><strong>快速加单</strong><div class="muted">服务选一次，商品可调整数量</div></div>
              <div class="quick-order-header">
                <el-button v-if="pendingOrder && canCapability('visit_order')" data-testid="retry-order" type="warning"
                  :loading="adding" :disabled="adding || loading || layoutEditing || !connectivity.isOnline || visit?.id !== String(route.params.id)"
                  @click="retryOriginalOrder">重试 {{ visit?.wristband_number || '—' }} 号手牌原操作</el-button>
                <OrderCart :items="catalog" :quantities="selectedQuantities" :adding="adding" compact
                  :disabled="materialsDialog || !!pendingOrder || layoutEditing || loading || !connectivity.isOnline || visit?.id !== String(route.params.id) || !canCapability('visit_order')"
                  @clear="clearSelectedItems" @submit="addSelectedItems" />
              </div>
            </div>
          </template>
          <CatalogPicker :items="catalog" :quantities="selectedQuantities" manual-inventory :disabled="materialsDialog || adding || loading || !canCapability('visit_order')" :can-arrange="canCapability('catalog_layout') && !adding && !materialsDialog" @select="selectItem" @quantity="setQuantity" @arranged="load(true)" @editing-change="layoutEditing = $event" />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="10">
        <el-card shadow="never">
          <template #header><strong>{{ linkedVisits.length > 1 ? '联动消费明细' : '消费明细' }}</strong></template>
          <el-table :data="linkedItems" max-height="610">
            <el-table-column v-if="linkedVisits.length > 1" prop="wristband_number" label="手牌" width="76" />
            <el-table-column prop="name" label="项目" min-width="120">
              <template #default="scope"><span :class="{ voided: scope.row.status === 'voided' }">{{ scope.row.name }}</span><el-tag v-if="Number(scope.row.covered_quantity) > 0" size="small" type="success">套票包含 {{ Number(scope.row.covered_quantity) }} 份</el-tag><el-tag v-if="scope.row.status === 'voided'" size="small" type="info">已撤销</el-tag><div v-for="stock in scope.row.inventory_consumption || []" :key="stock.stock_item_id" class="muted">{{ stock.name }} {{ stock.quantity }} {{ stock.base_unit }}</div><small v-if="scope.row.inventory_mode === 'manual' && !scope.row.inventory_consumption?.length" class="muted">无耗材</small></template>
            </el-table-column>
            <el-table-column prop="quantity" label="数量" width="70" />
            <el-table-column prop="total_amount" label="金额" width="90"><template #default="scope">¥{{ scope.row.total_amount }}</template></el-table-column>
            <el-table-column v-if="canCapability('visit_manage')" label="操作" width="75"><template #default="scope"><el-button v-if="scope.row.status === 'active' && scope.row.wristband_number === visit?.wristband_number" link type="danger" @click="voidItem(scope.row.id)">撤销</el-button><span v-else-if="scope.row.status === 'active'" class="muted">切换手牌</span></template></el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
    <el-dialog :model-value="materialsDialog" title="确认耗材并加单" width="min(760px, 94vw)" :close-on-click-modal="!adding && !confirmingMaterials" :close-on-press-escape="!adding && !confirmingMaterials" :show-close="!adding && !confirmingMaterials" @update:model-value="!$event && closeMaterials()">
      <div v-if="materialsDialog && materialTarget" data-testid="order-materials-dialog">
        <ConsumptionEditor v-model="consumptions" :items="materialItems" :quantities="materialTarget.quantities" :stock="consumables" :target="materialBand" :disabled="confirmingMaterials || adding || !connectivity.isOnline || !canCapability('visit_order')" />
      </div>
      <template #footer><el-button data-testid="cancel-order-materials" :disabled="adding || confirmingMaterials" @click="closeMaterials">取消</el-button><el-button data-testid="confirm-order-materials" type="primary" :loading="adding || confirmingMaterials" :disabled="adding || confirmingMaterials || !connectivity.isOnline || !canCapability('visit_order')" @click="confirmMaterials">确认加单</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.bill-total { align-self: center; color: var(--xq-danger); font-size: 22px; font-weight: 800; }
.voided { text-decoration: line-through; color: #a0a7b2; margin-right: 6px; }
.quick-order-header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; }
</style>
