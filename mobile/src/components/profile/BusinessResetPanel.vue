<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { dataOf, errorMessage, http } from '../../api'
import { businessGeneration, businessState, clearBusinessSession, onBusinessSessionClear } from '../../business/state'
import { ResetWorkflow } from '../../../../client/src/business/reset'

const owner = computed(() => businessState.value?.owner_reset_allowed === true)
const username = ref(''); const password = ref(''); const confirmation = ref('')
const period = ref(''); const table = ref('members'); const now = ref(Date.now())
const flow = reactive(new ResetWorkflow({
  request: async (method, path, body, params) => dataOf<unknown>(await http.request({ method, url: path, data: body, params })),
  capture: () => businessGeneration.capture(), isCurrent: generation => businessGeneration.isCurrent(generation),
  clear: task => { if (businessState.value?.period_id === task.old_period_id) { clearBusinessSession(); window.dispatchEvent(new Event('xiquan:logged-out')) } },
  readKey: () => localStorage.getItem('xiquan_reset_query') || '',
  saveKey: key => localStorage.setItem('xiquan_reset_query', key),
  createKey: () => crypto.randomUUID(), now: () => Date.now(), errorMessage: errorMessage,
}))
const remaining = computed(() => flow.preview ? Math.max(0, Math.ceil((Date.parse(flow.preview.expires_at) - now.value) / 1000)) : 0)
const removeClear = onBusinessSessionClear(() => { username.value = ''; password.value = ''; confirmation.value = ''; flow.preview = null; flow.evidence = null; flow.archives = [] })
let timer = 0
function submit() {
  if (!owner.value) return
  const pending = flow.submit(username.value, password.value, confirmation.value)
  password.value = ''; confirmation.value = ''
  void pending
}
function exportPage() {
  if (!owner.value || !flow.evidence) return
  const page = flow.evidence
  const url = URL.createObjectURL(new Blob([JSON.stringify(page, null, 2)], { type: 'application/json' }))
  const anchor = document.createElement('a')
  anchor.href = url; anchor.download = `archive-${page.period_id}-${page.table}-page-${page.page}.json`
  anchor.click(); URL.revokeObjectURL(url)
}
onMounted(() => {
  if (owner.value) void flow.recover()
  timer = window.setInterval(() => {
    now.value = Date.now()
    if (owner.value && flow.needsRecovery) void flow.recover()
  }, 3000)
})
onBeforeUnmount(() => { window.clearInterval(timer); removeClear(); password.value = ''; flow.preview = null })
</script>
<template>
  <section v-if="owner" class="business-reset" data-reset-panel>
    <h3>经营数据重置（危险操作）</h3>
    <p>当前经营数据归零、手牌恢复空闲。库存数量、库存历史、包装设置保留。历史资金、会员、次卡、流水及审计证据归档保留；不会实际退款或发送短信。</p>
    <p>保留项目价格、手牌号码、店名、终端、打印机与安全配置。预览有效期5分钟。</p>
    <button data-preview :disabled="flow.busy" @click="flow.loadPreview()">预览重置影响</button>
    <button :disabled="flow.busy" @click="flow.recover()">按已保存编号查询任务</button>
    <p v-if="flow.message" role="status">{{ flow.message }}</p>
    <div v-if="flow.preview">
      <dl>
        <dt>会员数量</dt><dd>{{ flow.preview.summary.members }}</dd>
        <dt>储值余额</dt><dd>{{ flow.preview.summary.stored_balance }}</dd>
        <dt>剩余次卡次数</dt><dd>{{ flow.preview.summary.remaining_passes }}</dd>
        <dt>在店手牌</dt><dd>{{ flow.preview.summary.active_visits }}</dd>
        <dt>未结金额</dt><dd>{{ flow.preview.summary.unsettled_amount }}</dd>
        <dt>库存项目</dt><dd>{{ flow.preview.summary.stock_items }}</dd>
        <dt>库存数量</dt><dd>{{ flow.preview.summary.stock_quantity }}</dd>
      </dl>
      <p>预览剩余 {{ remaining }} 秒；过期后须重新预览。</p>
    </div>
    <form @submit.prevent="submit">
      <label>账号<input v-model="username" name="username" autocomplete="username" :disabled="flow.busy" /></label>
      <label>再次输入密码<input v-model="password" name="password" type="password" autocomplete="off" :disabled="flow.busy" /></label>
      <label>输入“重置当前经营数据”<input v-model="confirmation" name="confirmation" autocomplete="off" :disabled="flow.busy" /></label>
      <button data-submit :disabled="flow.busy || !flow.preview || remaining === 0">确认重置当前经营数据</button>
    </form>
    <p v-if="flow.task">任务 {{ flow.task.id }} · {{ flow.task.status }} · {{ flow.task.stage }}</p>
    <details>
      <summary>历史归档与只读证据</summary>
      <button data-archives :disabled="flow.busy" @click="flow.loadArchives()">查询历史归档</button>
      <div v-for="archive in flow.archives" :key="archive.period_id">
        <button :disabled="flow.busy" @click="period = archive.period_id; flow.loadEvidence(period, table)">{{ archive.closed_at }} · {{ archive.period_id }}</button>
        <pre>{{ JSON.stringify(archive.summary, null, 2) }}</pre>
      </div>
      <p>归档列表第 {{ flow.archivePage }} 页</p>
      <button :disabled="flow.busy || flow.archivePage === 1" @click="flow.loadArchives(flow.archivePage - 1)">上一页归档</button>
      <button :disabled="flow.busy || flow.archives.length === 0" @click="flow.loadArchives(flow.archivePage + 1)">下一页归档</button>
      <label>证据表<select v-model="table" @change="period && flow.loadEvidence(period, table)"><option value="members">会员</option><option value="audit_logs">审计日志</option></select></label>
      <div v-if="flow.evidence">
        <p>证据第 {{ flow.evidence.page }} 页（每页最多100条）；导出仅包含当前已收到页。</p>
        <pre>{{ JSON.stringify(flow.evidence.rows, null, 2) }}</pre>
        <button :disabled="flow.busy || flow.evidence.page === 1" @click="flow.loadEvidence(period, table, flow.evidence.page - 1)">上一页证据</button>
        <button :disabled="flow.busy || !flow.evidence.has_more" @click="flow.loadEvidence(period, table, flow.evidence.page + 1)">下一页证据</button>
        <button @click="exportPage">导出当前页 JSON</button>
      </div>
    </details>
  </section>
</template>
<style scoped>
.business-reset{margin-top:20px;padding:16px;border:1px solid #cf4b46;border-radius:6px;background:#fff8f7;color:#692824}
h3{margin:0 0 12px}p{font-size:13px;line-height:1.6}button{margin:4px;padding:8px;border:1px solid #b64640;border-radius:4px;color:#8c2925;background:white;cursor:pointer}button:disabled{opacity:.5;cursor:default}
label{display:block;margin:10px 0;font-size:13px}input,select{display:block;box-sizing:border-box;width:100%;max-width:380px;padding:9px;margin-top:5px;border:1px solid #bda5a2;border-radius:4px;background:white}
dl{display:grid;grid-template-columns:1fr 1fr;max-width:380px;font-size:13px}dd{margin:0;text-align:right}pre{max-height:280px;overflow:auto;white-space:pre-wrap;font-size:12px}details{margin-top:16px}
</style>
