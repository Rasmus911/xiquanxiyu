<script setup lang="ts">
import { businessGeneration, canAccess, canCapability, useBusinessGuard } from '../business/state'
const guardBusinessOperation = useBusinessGuard()
const pageGeneration = businessGeneration.capture()

import { computed, h, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { clearReasons } from '../domain/inventory/receiving'
import { readDashboardReturn, saveDashboardReturn } from '../domain/wristbands/return-state'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiData, apiErrorMessage, http } from '../api/http'
import AppPageHeader from '../components/app/AppPageHeader.vue'
import BatchActionBar from '../components/wristbands/BatchActionBar.vue'
import WristbandCard from '../components/wristbands/WristbandCard.vue'
import AdmissionDialog from '../components/wristbands/AdmissionDialog.vue'
import { useAdmissionDialog } from '../composables/useAdmissionDialog'
import { beginBatch, cancelBatch, finishBatch, toggleSelected, type WristbandSelectionState } from '../domain/wristbands/selection'
import { subscribeRealtime } from '../realtime/events'
import { useConnectivityStore } from '../stores/connectivity'
import { useAuthStore } from '../stores/auth'
import type { CatalogItem, Wristband } from '../types'

type BathArea = 'male' | 'female'

const router = useRouter()
const route = useRoute()
const connectivity = useConnectivityStore()
const auth = useAuthStore()
const loading = ref(false)
const clearing = ref(false)
const staffView = computed(() => !canCapability('visit_open') && !canCapability('visit_manage'))
function eligible(row: Wristband) { return !staffView.value || ((row.status === 'in_use' || row.status === 'lost') && !!row.visit_id) }
const wristbands = ref<Wristband[]>([])
const admission = useAdmissionDialog()
const tickets = ref<CatalogItem[]>([])
const areaFilter = ref<BathArea>(route.query.area === 'female' ? 'female' : 'male')
if (auth.employee?.role === 'female_scrubber') areaFilter.value = 'female'
const visibleAreas = computed<BathArea[]>(() => auth.employee?.role === 'male_scrubber' ? ['male']
  : auth.employee?.role === 'female_scrubber' ? ['female'] : ['male', 'female'])
const statusFilter = ref(['all', 'available', 'in_use', 'lost'].includes(String(route.query.status)) ? String(route.query.status) : 'all')
if (staffView.value && statusFilter.value === 'available') statusFilter.value = 'all'
const keyword = ref(String(route.query.q || ''))
const batchState = ref<WristbandSelectionState>({ active: false, selectedIds: [] })
let refreshTimer: number | undefined
let unsubscribeRealtime: (() => void) | undefined
let clockTimer: number | undefined
const clockNow = ref(Date.now())

const areaMeta: Record<BathArea, { label: string; range: string; color: string }> = {
  male: { label: '男浴', range: '001–050', color: '#3182ce' },
  female: { label: '女浴', range: '051–100', color: '#d25d9f' },
}

const statusMeta: Record<string, { label: string; color: string }> = {
  available: { label: '空闲', color: '#20ad83' },
  in_use: { label: '使用中', color: '#e69b2e' },
  lost: { label: '已挂失', color: '#e04f5f' },
  disabled: { label: '已停用', color: '#8b95a7' },
}

const statusKeys = ['all', 'available', 'in_use', 'lost'] as const

function bathArea(row: Wristband): 'male' | 'female' | 'other' {
  if (row.bath_area) return row.bath_area
  const number = Number(row.number)
  if (number >= 8001 && number <= 8060) return 'male'
  if (number >= 9001 && number <= 9060) return 'female'
  return 'other'
}

function summarize(area: BathArea) {
  const rows = wristbands.value.filter((row) => bathArea(row) === area && eligible(row))
  return {
    all: rows.length,
    available: rows.filter((row) => row.status === 'available').length,
    in_use: rows.filter((row) => row.status === 'in_use').length,
    lost: rows.filter((row) => row.status === 'lost').length,
  }
}

const areaCounts = computed(() => ({ male: summarize('male'), female: summarize('female') }))
const currentAreaRows = computed(() => wristbands.value.filter((row) => bathArea(row) === areaFilter.value))
const filtered = computed(() => (keyword.value.trim() ? wristbands.value : currentAreaRows.value).filter((row) => {
  if (!eligible(row)) return false
  const statusOk = statusFilter.value === 'all' || row.status === statusFilter.value
  const query = keyword.value.trim()
  const numberOk = !query || row.number.includes(query) || row.linked_numbers?.some((number) => number.includes(query))
  return statusOk && numberOk
}))
const counts = computed(() => areaCounts.value[areaFilter.value])
const selectedBandIds = computed(() => batchState.value.selectedIds)
const selectedRows = computed(() => selectedBandIds.value
  .map((id) => wristbands.value.find((row) => row.id === id))
  .filter((row): row is Wristband => Boolean(row)))
const selectedVisits = computed(() => selectedRows.value.map((row) => row.visit_id).filter((id): id is string => Boolean(id)))
const selectedAreaCounts = computed(() => ({
  male: selectedRows.value.filter((row) => bathArea(row) === 'male').length,
  female: selectedRows.value.filter((row) => bathArea(row) === 'female').length,
}))

async function load(silent = false) {
  const isCurrent = guardBusinessOperation('load')
  if (!isCurrent()) return

  if (!silent) loading.value = true
  try {
    const data = apiData<Wristband[]>(await http.get('/wristbands')); if (!isCurrent()) return; wristbands.value = data
    if (canCapability('visit_open')) {
      const catalog = apiData<CatalogItem[]>(await http.get('/catalog', { params: { kind: 'ticket', active: true } }))
      if (!isCurrent()) return
      tickets.value = catalog
    }
    batchState.value = {
      ...batchState.value,
      selectedIds: selectedBandIds.value.filter((id) => wristbands.value.some((row) => row.id === id)),
    }
  } catch (error) { if (!isCurrent()) return; 
    if (!silent) ElMessage.error(apiErrorMessage(error))
  } finally { if (!isCurrent()) return; 
    loading.value = false
  }
}

async function cardClick(row: Wristband) {
  const isCurrent = guardBusinessOperation('cardClick')
  if (!isCurrent()) return

  if (batchState.value.active) {
    if (canSelect(row)) toggleSelection(row)
    return
  }
  if (row.visit_id) {
    await router.push({ path: `/visits/${row.visit_id}`, query: { returnTo: dashboardReturnTo.value } }); if (!isCurrent()) return;
    return
  }
  if (row.status !== 'available' || !canCapability('visit_open')) return
  try {
    const selected = await admission.open([row], `发放 ${row.number} 号手牌`)
    if (!selected || !isCurrent()) return
    const visit = apiData<{ id: string }>(await http.post(`/wristbands/${row.id}/open`, { ticket_catalog_item_id: selected[row.id] })); if (!isCurrent()) return;
    ElMessage.success('开单成功')
    await router.push(`/visits/${visit.id}`); if (!isCurrent()) return;
  } catch (error) { if (!isCurrent()) return; 
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error))
  }
}

async function switchBand(row: Wristband) {
  const isCurrent = guardBusinessOperation('switchBand')
  if (!isCurrent()) return

  try {
    const { value } = await ElMessageBox.prompt('输入新的空闲手牌号', `更换 ${row.number} 号手牌`, { inputPattern: /\S+/, inputErrorMessage: '请输入手牌号' }); if (!isCurrent()) return;
    await http.post(`/wristbands/${row.id}/switch`, { target_number: value }); if (!isCurrent()) return;
    ElMessage.success('换牌成功')
    await load(true); if (!isCurrent()) return;
  } catch (error) { if (!isCurrent()) return; 
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error))
  }
}

async function markLost(row: Wristband) {
  const isCurrent = guardBusinessOperation('markLost')
  if (!isCurrent()) return

  try {
    const { value } = await ElMessageBox.prompt('请输入挂失原因，将自动收取赔偿费用', `挂失 ${row.number} 号手牌`, { inputPattern: /\S+/, inputErrorMessage: '必须填写原因', type: 'warning' }); if (!isCurrent()) return;
    await http.post(`/wristbands/${row.id}/lost`, { reason: value }); if (!isCurrent()) return;
    ElMessage.success('挂失成功')
    await load(true); if (!isCurrent()) return;
  } catch (error) { if (!isCurrent()) return; 
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error))
  }
}

async function replaceBand(row: Wristband) {
  const isCurrent = guardBusinessOperation('replaceBand')
  if (!isCurrent()) return

  try {
    const { value } = await ElMessageBox.prompt('输入补发的新手牌号', `补发 ${row.number} 号手牌`, { inputPattern: /\S+/, inputErrorMessage: '请输入手牌号' }); if (!isCurrent()) return;
    await http.post(`/wristbands/${row.id}/replace`, { target_number: value }); if (!isCurrent()) return;
    ElMessage.success('补牌成功')
    await load(true); if (!isCurrent()) return;
  } catch (error) { if (!isCurrent()) return; 
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error))
  }
}

async function recoverBand(row: Wristband) {
  const isCurrent = guardBusinessOperation('recoverBand')
  if (!isCurrent()) return

  try {
    const message = row.visit_id
      ? `确认恢复 ${row.number} 号手牌？未结账的挂失赔偿将自动撤销。`
      : `确认恢复 ${row.number} 号手牌并重新设为空闲？已结账费用不会改变。`
    await ElMessageBox.confirm(message, '恢复挂失手牌', { type: 'warning' }); if (!isCurrent()) return;
    await http.post(`/wristbands/${row.id}/recover`, {}); if (!isCurrent()) return;
    ElMessage.success('手牌已恢复')
    await load(true); if (!isCurrent()) return;
  } catch (error) { if (!isCurrent()) return; 
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error))
  }
}

async function forceClear(row: Wristband) {
  if (clearing.value || !row.visit_id || !canCapability('visit_clear') || !canAccess('visit:clear')) return
  const isCurrent = guardBusinessOperation('forceClear')
  if (!isCurrent()) return

  clearing.value = true
  try {
    let reason = clearReasons[0]!
    await ElMessageBox.confirm(h('div', [h('p', `请选择清空 ${row.number} 号手牌的原因`),
      h('select', { 'aria-label':'取消手牌激活原因', style:'width:100%;min-height:42px;padding:8px;border:1px solid #dcdfe6;border-radius:6px',
        onChange:(event:Event)=>{ reason=(event.target as HTMLSelectElement).value } },
        clearReasons.map(value=>h('option',{value},value)))]), '清空账单',
      {confirmButtonText:'下一步：验证本人密码'}); if (!isCurrent()) return;
    const { value } = await ElMessageBox.prompt(
      `仅清空所选 ${row.number} 号手牌，联动组其他手牌及消费保留。撤销本牌未结账消费并返还库存。请验证 ${auth.employee?.username} 本人的登录密码。`,
      '授权清空账单',
      { inputType: 'password', inputPattern: /\S+/, inputErrorMessage: '请输入本人登录密码', type: 'error', confirmButtonText: '确认清空' },
    ); if (!isCurrent()) return;
    await http.post(`/wristbands/${row.id}/force-clear`, { password: value, reason }); if (!isCurrent()) return;
    ElMessage.success(`${row.number} 号手牌已恢复为空闲`)
    await load(true); if (!isCurrent()) return;
  } catch (error) { if (!isCurrent()) return; 
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error))
  }
  finally { if (isCurrent()) clearing.value = false }
}

function elapsed(openedAt?: string) {
  if (!openedAt) return ''
  const seconds = Math.max(0, Math.floor((clockNow.value - new Date(openedAt).getTime()) / 1000))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor(seconds % 3600 / 60)
  const remain = seconds % 60
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remain).padStart(2, '0')}`
}

function beginBatchMode() {
  batchState.value = beginBatch(batchState.value)
}

function cancelBatchMode() {
  batchState.value = cancelBatch(batchState.value)
}

function cancelWithKeyboard(event: Event) {
  if (!batchState.value.active) return
  cancelBatchMode()
  event.preventDefault()
}

function canSelect(row: Wristband) {
  return ['available', 'in_use'].includes(row.status)
}

function toggleSelection(row: Wristband) {
  if (!canSelect(row)) return
  batchState.value = toggleSelected(batchState.value, row.id)
}

function mergeCheckout() {
  if (!selectedVisits.value.length) return ElMessage.warning('请选择至少一个使用中的手牌')
  const visits = selectedVisits.value.join(',')
  batchState.value = finishBatch(batchState.value)
  router.push({ path: '/checkout', query: { visits, scope: 'selected', returnTo: dashboardReturnTo.value } })
}

async function batchLink() {
  const isCurrent = guardBusinessOperation('batchLink')
  if (!isCurrent()) return

  if (selectedBandIds.value.length < 2) return ElMessage.warning('请至少选择两个手牌')
  const numbers = selectedRows.value.map((row) => row.number).join('、')
  const capturedRows = selectedRows.value.map(row => ({ ...row }))
  const capturedIds = capturedRows.map(row => row.id)
  try {
    const newRows = capturedRows.filter(row => row.status === 'available' && !row.visit_id)
    let selected: Record<string, string> = {}
    if (newRows.length) {
      const result = await admission.open(newRows, '联动开牌：逐人选择门票',
        `联动 ${numbers}。已开牌人员保留原票种；男浴和女浴可同组。`)
      if (!result || !isCurrent()) return
      selected = result
    } else {
      await ElMessageBox.confirm(`确认联动 ${numbers}？各人原票种保持不变。`, '一键联动确认')
      if (!isCurrent()) return
    }
    const result = apiData<{ linked_wristbands: string[] }>(
      await http.post('/wristbands/link-batch', { wristband_ids: capturedIds, ticket_catalog_item_ids: selected }),
    ); if (!isCurrent()) return;
    ElMessage.success(`已联动：${result.linked_wristbands.join('、')}`)
    batchState.value = finishBatch(batchState.value)
    await load(true); if (!isCurrent()) return;
  } catch (error) { if (!isCurrent()) return; 
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error))
  }
}

const dashboardReturnTo = computed(() => router.resolve({
  path: '/',
  query: {
    area: areaFilter.value,
    ...(statusFilter.value !== 'all' ? { status: statusFilter.value } : {}),
    ...(keyword.value.trim() ? { q: keyword.value.trim() } : {}),
  },
}).fullPath)

watch([areaFilter, statusFilter, keyword], () => {
  void router.replace(dashboardReturnTo.value)
})

onMounted(async () => {
  window.addEventListener('xiquan:cancel-selection', cancelWithKeyboard)
  const saved = readDashboardReturn()
  if (saved) {
    if (saved.area !== 'all') areaFilter.value = saved.area
    keyword.value = saved.keyword
  }
  await load()
  await nextTick()
  if (saved && businessGeneration.isCurrent(pageGeneration)) window.scrollTo({ top: saved.scrollTop })
  unsubscribeRealtime = subscribeRealtime(['wristbands', 'visits', 'checkout', 'catalog'], () => load(true))
  refreshTimer = window.setInterval(() => {
    if (!connectivity.isOnline && document.visibilityState === 'visible') load(true)
  }, 30_000)
  clockTimer = window.setInterval(() => { clockNow.value = Date.now() }, 1_000)
})

onBeforeUnmount(() => {
  if (businessGeneration.isCurrent(pageGeneration)) saveDashboardReturn({ area: areaFilter.value,
    keyword: keyword.value, scrollTop: window.scrollY })
  window.removeEventListener('xiquan:cancel-selection', cancelWithKeyboard)
  unsubscribeRealtime?.()
  if (refreshTimer) window.clearInterval(refreshTimer)
  if (clockTimer) window.clearInterval(clockTimer)
})
</script>

<template>
  <div :class="['page dashboard', { 'has-batch-bar': batchState.active }]" v-loading="loading">
    <AdmissionDialog :model-value="admission.visible.value" :bands="admission.bands.value" :tickets="tickets"
      :title="admission.title.value" :description="admission.description.value"
      @confirm="admission.close($event)" @cancel="admission.close()" />
    <AppPageHeader :title="staffView ? '在场手牌' : '前台手牌'" :description="staffView ? '点击在场手牌查看消费并服务。' : '单击手牌直接开单或查看；需要联动、合并结账时再进入批量操作。'" eyebrow="FRONT DESK">
      <template #actions>
        <el-input v-model="keyword" clearable placeholder="输入手牌号" style="width: 180px" />
        <el-button @click="load()"><el-icon><Refresh /></el-icon>刷新</el-button>
        <el-button v-if="canCapability('visit_manage') && !batchState.active" type="primary" @click="beginBatchMode"><el-icon><Select /></el-icon>批量操作</el-button>
        <el-button v-else-if="batchState.active" @click="cancelBatchMode">退出批量</el-button>
      </template>
    </AppPageHeader>

    <div class="area-tabs">
      <button
        v-for="area in visibleAreas"
        :key="area"
        :class="['area-tab', area, { active: areaFilter === area }]"
        @click="areaFilter = area"
      >
        <span class="area-title">{{ areaMeta[area].label }}</span>
        <span class="area-range">{{ areaMeta[area].range }}</span>
        <span class="area-summary"><template v-if="!staffView">空闲 {{ areaCounts[area].available }} · </template>使用中 {{ areaCounts[area].in_use }} · 挂失 {{ areaCounts[area].lost }}</span>
        <span v-if="selectedAreaCounts[area]" class="selected-count">已选 {{ selectedAreaCounts[area] }}</span>
      </button>
    </div>

    <div class="section-heading">
      <div>
        <strong>{{ keyword.trim() ? '手牌搜索与联动结果' : `${areaMeta[areaFilter].label}手牌` }}</strong>
        <span>{{ keyword.trim() ? `包含 ${keyword.trim()} 的联动组` : areaMeta[areaFilter].range }}</span>
      </div>
      <span>共 {{ keyword.trim() ? filtered.length : counts.all }} 个</span>
    </div>

    <div class="filters">
      <button v-for="key in statusKeys.filter(key => !staffView || key !== 'available')" :key="key" :class="{ active: statusFilter === key }" @click="statusFilter = key">
        {{ key === 'all' ? '全部' : statusMeta[key].label }} <strong>{{ counts[key] }}</strong>
      </button>
    </div>

    <el-empty v-if="!filtered.length" description="暂无符合条件的手牌" />
    <div class="band-grid">
      <WristbandCard
        v-for="row in filtered"
        :key="row.id"
        :row="row"
        :selected="selectedBandIds.includes(row.id)"
        :batch-active="batchState.active"
        :selectable="canSelect(row)"
        :elapsed="elapsed(row.opened_at)"
        :can-clear="canCapability('visit_clear') && canAccess('visit:clear') && !clearing"
        :can-manage="canCapability('visit_manage')"
        @primary="cardClick"
        @toggle-select="toggleSelection"
        @switch="switchBand"
        @lost="markLost"
        @recover="recoverBand"
        @replace="replaceBand"
        @force-clear="forceClear"
      />
    </div>
    <BatchActionBar
      v-if="batchState.active"
      :selected-numbers="selectedRows.map((row) => row.number)"
      :active-visit-count="selectedVisits.length"
      :male-count="selectedAreaCounts.male"
      :female-count="selectedAreaCounts.female"
      @link="batchLink"
      @checkout="mergeCheckout"
      @cancel="cancelBatchMode"
    />
  </div>
</template>

<style scoped>
.dashboard.has-batch-bar { padding-bottom: 105px; }
.area-tabs { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }
.area-tab { position: relative; display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 4px 14px; min-height: 72px; padding: 16px 20px; text-align: left; border: 2px solid transparent; border-radius: var(--xq-radius-lg); cursor: pointer; transition: transform .15s, box-shadow .15s, border-color .15s; }
.area-tab:hover { border-color: var(--xq-border); }
.area-tab.male { color: #245f9d; background: #f0f5f8; }
.area-tab.female { color: #a9457d; background: #faf1f4; }
.area-tab.male.active { border-color: var(--xq-primary); }
.area-tab.female.active { border-color: #c8508d; }
.area-title { font-size: 25px; font-weight: 800; }
.area-range { font-size: 17px; font-weight: 700; }
.area-summary { grid-column: 1 / -1; font-size: 13px; opacity: .82; }
.selected-count { position: absolute; right: 14px; top: 12px; padding: 3px 8px; color: white; border-radius: 10px; font-size: 12px; font-weight: 700; }
.area-tab.male .selected-count { background: var(--xq-primary); }
.area-tab.female .selected-count { background: #c8508d; }
.section-heading { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.section-heading div { display: flex; align-items: baseline; gap: 10px; }
.section-heading strong { color: var(--xq-text-1); font-size: 19px; }
.section-heading span { color: var(--xq-text-3); }
.filters { display: flex; gap: 10px; margin-bottom: 18px; }
.filters button { padding: 9px 16px; color: var(--xq-text-2); cursor: pointer; border: 1px solid var(--xq-border); border-radius: 10px; background: white; }
.filters button.active { color: #08796c; border-color: var(--xq-accent); background: var(--xq-accent-soft); }
.band-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 14px; }
@media (max-width: 900px) { .area-tabs { grid-template-columns: 1fr; } }
</style>
