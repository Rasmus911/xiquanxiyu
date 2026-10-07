<script setup lang="ts">
import { useBusinessGuard } from '../business/state'
const guardBusinessOperation = useBusinessGuard()

import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiData, apiErrorMessage, http } from '../api/http'
import AppPageHeader from '../components/app/AppPageHeader.vue'
import { usePageRefresh } from '../composables/usePageRefresh'
import { formatBusinessTime as time } from '../format/business-time'

const rows = ref<Array<Record<string, any>>>([])
const filter = reactive({ employee: '', action: '', terminal: '', keyword: '', request_id: '' })
const dates = ref<string[]>([])
const page = ref(1)
const total = ref(0)
const busy = ref(false)
const selected = ref<Record<string, any> | null>(null)
const detailOpen = ref(false)
const chainValid = ref<boolean | null>(null)
const evidenceInput = ref<HTMLInputElement | null>(null)
const finance = ref<Record<string, any> | null>(null)
const financeOpen = ref(false)
const issueLabels: Record<string, string> = { member_balance: '会员余额', pass_balance: '次卡次数', settlement_payment: '结算收款', settlement_total: '结算合计', settlement_refund: '退款合计', settled_order: '已结账项目合计' }
function params() {
  return { ...filter, start: dates.value?.[0], end: dates.value?.[1], page: page.value, page_size: 50 }
}
async function load() {
  const isCurrent = guardBusinessOperation('load')
  if (!isCurrent()) return

  busy.value = true
  try {
    const data = apiData<{ items: Array<Record<string, any>>; total: number }>(await http.get('/audit', { params: params() })); if (!isCurrent()) return;
    rows.value = data.items; total.value = data.total
  } catch (error) { if (!isCurrent()) return;  ElMessage.error(apiErrorMessage(error)) }
  finally { if (!isCurrent()) return;  busy.value = false }
}
function search() { page.value = 1; void load() }
async function verify() {
  const isCurrent = guardBusinessOperation('verify')
  if (!isCurrent()) return

  try {
    const data = apiData<{ valid: boolean; broken_at?: number }>(await http.get('/audit/verify')); if (!isCurrent()) return;
    chainValid.value = data.valid
    data.valid ? ElMessage.success('当前数据库记录校验通过，请另存证据包作为独立核对依据') : ElMessage.error(`第 ${data.broken_at} 条记录校验失败，请停止相关操作并保留现场`)
  } catch (error) { if (!isCurrent()) return;  ElMessage.error(apiErrorMessage(error)) }
}
async function exportEvidence() {
  const isCurrent = guardBusinessOperation('exportEvidence')
  if (!isCurrent()) return

  try {
    const evidence = apiData<Record<string, any>>(await http.get('/audit/evidence', { params: params(), timeout: 60000 })); if (!isCurrent()) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(evidence, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url
    link.download = `溪泉操作证据-${new Date().toISOString().replace(/[:.]/g, '-')}.json`
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
    ElMessage.success('证据包已导出。请保存到独立电脑或备份介质，不要仅保存在服务器。')
  } catch (error) { if (!isCurrent()) return;  ElMessage.error(apiErrorMessage(error)) }
}
function details(row: Record<string, any>) { selected.value = row; detailOpen.value = true }
async function financialCheck() {
  const isCurrent = guardBusinessOperation('financialCheck')
  if (!isCurrent()) return

  try {
    const data = apiData<Record<string, any>>(await http.get('/audit/finance-integrity', { timeout: 60000 })); if (!isCurrent()) return; finance.value = data
    financeOpen.value = true
  } catch (error) { if (!isCurrent()) return;  ElMessage.error(apiErrorMessage(error)) }
}
async function compareCheckpoint(event: Event) {
  const isCurrent = guardBusinessOperation('compareCheckpoint')
  if (!isCurrent()) return

  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    if (file.size > 30 * 1024 * 1024) throw new Error('证据文件过大，请使用 30MB 以内的导出文件')
    const checkpoint = JSON.parse(await file.text()).checkpoint; if (!isCurrent()) return;
    if (!Number.isInteger(checkpoint?.chain_index) || !/^[a-f0-9]{64}$/.test(checkpoint?.hash)) throw new Error('不是有效的溪泉证据包')
    const data = apiData<{ valid: boolean; checkpoint_valid: boolean }>(await http.get('/audit/verify', { params: { checkpoint_index: checkpoint.chain_index, checkpoint_hash: checkpoint.hash } })); if (!isCurrent()) return;
    data.valid && data.checkpoint_valid ? ElMessage.success('与该文件保存的历史检查点一致') : ElMessage.error('历史检查点不一致，或当前记录校验失败，请保留现场和证据文件')
  } catch (error) { if (!isCurrent()) return;  ElMessage.error(apiErrorMessage(error)) }
  finally { if (!isCurrent()) return;  input.value = '' }
}
usePageRefresh(load)
onMounted(load)
</script>

<template>
  <div class="page">
    <AppPageHeader title="操作记录" :description="`共 ${total} 条。保留原始账号、终端和操作详情，不提供修改、删除入口。`">
      <template #actions>
        <el-button :type="chainValid === false ? 'danger' : 'default'" @click="verify">校验记录</el-button>
        <el-button @click="financialCheck">核对资金账目</el-button>
        <el-button @click="evidenceInput?.click()">核对历史证据包</el-button>
        <el-button @click="exportEvidence">导出追责证据包</el-button>
      </template>
    </AppPageHeader>
    <input ref="evidenceInput" type="file" accept="application/json,.json" hidden @change="compareCheckpoint" />
    <div class="audit-filter xq-panel">
      <el-input v-model="filter.employee" clearable placeholder="员工登录账号" @keyup.enter="search" />
      <el-input v-model="filter.action" clearable placeholder="操作名称，例如退款" @keyup.enter="search" />
      <el-input v-model="filter.terminal" clearable placeholder="终端编码或名称" @keyup.enter="search" />
      <el-input v-model="filter.keyword" clearable placeholder="单号、手牌号或详情关键词" @keyup.enter="search" />
      <el-input v-model="filter.request_id" clearable placeholder="请求编号，精确查询" @keyup.enter="search" />
      <el-date-picker v-model="dates" type="datetimerange" value-format="YYYY-MM-DDTHH:mm:ssZ" start-placeholder="开始时间" end-placeholder="结束时间" />
      <el-button type="primary" :loading="busy" @click="search">查询</el-button>
    </div>
    <el-card shadow="never">
      <el-table v-loading="busy" :data="rows" max-height="600" @row-dblclick="details">
        <el-table-column prop="chain_index" label="序号" width="85" />
        <el-table-column label="操作时间" width="185"><template #default="s">{{ time(s.row.created_at) }}</template></el-table-column>
        <el-table-column prop="employee_username" label="登录账号" min-width="110" />
        <el-table-column prop="action_label" label="操作" min-width="140" />
        <el-table-column prop="terminal_name" label="终端" min-width="130" />
        <el-table-column label="对象 / 请求编号" min-width="230"><template #default="s"><div>{{ s.row.details?.wristband_number ? `手牌 ${s.row.details.wristband_number}` : s.row.details?.number || s.row.entity_label }} · {{ s.row.entity_id?.slice(0, 8) || '—' }}</div><small class="request-id" :title="s.row.request_id">{{ s.row.request_id }}</small></template></el-table-column>
        <el-table-column label="详情" width="85"><template #default="s"><el-button link type="primary" @click="details(s.row)">查看</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" :page-size="50" :total="total" layout="total, prev, pager, next" @current-change="load" />
    </el-card>
    <el-drawer v-model="detailOpen" title="操作详情" size="min(680px, 90vw)">
      <template v-if="selected">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="时间">{{ time(selected.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="操作人">{{ selected.employee_username }} · {{ selected.context?.employee_name }} · {{ selected.context?.employee_role }}（{{ selected.context?.identity_verified ? '身份已验证' : '未验证身份 / 系统记录' }}）</el-descriptions-item>
          <el-descriptions-item label="操作">{{ selected.action_label }}</el-descriptions-item>
          <el-descriptions-item label="终端">{{ selected.terminal_name }} / {{ selected.terminal_code }}</el-descriptions-item>
          <el-descriptions-item label="来源 IP">{{ selected.context?.source_ip || '旧记录未采集' }}</el-descriptions-item>
          <el-descriptions-item label="客户端（声明值）">{{ selected.context?.client_type_claim || '未声明' }} {{ selected.context?.client_version_claim }}</el-descriptions-item>
          <el-descriptions-item label="请求编号">{{ selected.request_id }}</el-descriptions-item>
          <el-descriptions-item label="会话编号">{{ selected.context?.session_id || '旧记录未采集' }}</el-descriptions-item>
        </el-descriptions>
        <h3>业务详情与变更前后值</h3><pre>{{ JSON.stringify(selected.details, null, 2) }}</pre>
        <h3>证据链</h3><p class="hash">前序：{{ selected.prev_hash }}<br>当前：{{ selected.current_hash }}</p>
        <p class="muted">账号可追溯到操作会话，但不能独立证明实际操作者。禁止共用账号；发生争议时同时保留收款凭证、设备记录和监控。</p>
      </template>
    </el-drawer>
    <el-dialog v-model="financeOpen" title="资金账目核对" width="min(820px, 90vw)">
      <template v-if="finance">
        <el-alert :type="finance.valid ? 'success' : 'error'" :title="finance.valid ? `核对 ${finance.checked} 项，当前余额和金额与流水一致` : `发现 ${finance.issue_count} 项不一致，请停止相关资金操作并导出证据`" :closable="false" />
        <p class="muted">核对会员余额、次卡次数、收款、退款和已结账项目。历史导入未带流水也会报告差异；不要直接修改余额来消除差异。此核对不能证明微信或支付宝实际到账。</p>
        <el-table :data="finance.issues">
          <el-table-column label="类别" width="160"><template #default="s">{{ issueLabels[s.row.kind] || s.row.kind }}</template></el-table-column>
          <el-table-column prop="entity_id" label="对象编号" min-width="230" />
          <el-table-column prop="actual" label="当前值" /><el-table-column prop="expected" label="流水推算值" />
        </el-table>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.audit-filter { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 14px; padding: 14px; }
.audit-filter :deep(.el-input) { width: 210px; }.audit-filter :deep(.el-date-editor) { max-width: 390px; }
small { color: var(--xq-text-3); font-size: 11px; }h3 { font-size: 15px; margin-top: 24px; }
.request-id { display: block; max-width: 235px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
pre { padding: 12px; border: 1px solid var(--xq-border); border-radius: 5px; background: #f8f9f6; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.7 Consolas, "Microsoft YaHei", monospace; }
.hash { overflow-wrap: anywhere; font: 12px/1.8 Consolas, monospace; }.el-pagination { margin-top: 16px; justify-content: flex-end; }
</style>
