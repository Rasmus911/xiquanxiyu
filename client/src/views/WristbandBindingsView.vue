<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiData, apiErrorMessage, http } from '../api/http'
import { canCapability, onBusinessSessionClear, useBusinessGuard } from '../business/state'
import { normalizeCardInput } from '../domain/members/card-input'
import { useAuthStore } from '../stores/auth'
import AppPageHeader from '../components/app/AppPageHeader.vue'
import { subscribeRealtime } from '../realtime/events'

interface Binding {
  wristband_id:string; number:string; bath_area:string; status:string
  chip_uid:string|null; version:number; updated_at:string|null
}
const auth = useAuthStore(), guard = useBusinessGuard()
const allowed = computed(() => canCapability('wristband_bind'))
const rows = ref<Binding[]>([]), area = ref('all'), keyword = ref(''), page = ref(1)
const loading = ref(false), saving = ref(false), selected = ref<Binding|null>(null), dialog = ref(false)
const uid = ref(''), password = ref(''), error = ref(''), uidInput = ref<HTMLInputElement>()
let unsubscribe: (() => void) | undefined
const filtered = computed(() => rows.value.filter(row => (area.value === 'all' || row.bath_area === area.value)
  && (!keyword.value.trim() || row.number.includes(keyword.value.trim()) || row.chip_uid?.includes(keyword.value.trim()))))
const visible = computed(() => filtered.value.slice((page.value-1)*10,page.value*10))
const bound = computed(() => rows.value.filter(row => !!row.chip_uid).length)
watch([area,keyword],() => {page.value=1})
watch(() => filtered.value.length, count => {page.value=Math.min(page.value,Math.max(1,Math.ceil(count/10)))})
watch(allowed, value => { if (!value) clear() })
onBusinessSessionClear(clear)
function clear() { rows.value=[]; dialog.value=false; uid.value=''; password.value=''; selected.value=null; error.value='' }
function closeDialog(done: () => void) { if (!saving.value) {password.value='';uid.value='';done()} }
async function load() {
  if (!allowed.value) return
  const current=guard('load'); loading.value=true
  try { const data=apiData<Binding[]>(await http.get('/wristband-reader/bindings')); if(current()) rows.value=data }
  catch (failure) { if(current()) ElMessage.error(apiErrorMessage(failure)) }
  finally { if(current()) loading.value=false }
}
async function edit(row:Binding) {
  if (!allowed.value || row.status!=='available') return
  selected.value={...row}; uid.value=''; password.value=''; error.value=''; dialog.value=true
  await nextTick(); uidInput.value?.focus()
}
async function save() {
  if (!allowed.value || !selected.value || saving.value) return
  const clean=normalizeCardInput(uid.value.trim())
  if (!clean) {error.value='芯片 ID 必须是 1–64 位数字'; return}
  const row=selected.value
  if (row.version>0 && clean!==row.chip_uid && !password.value) {error.value='请验证当前登录账号的密码'; return}
  const current=guard('change'); saving.value=true; error.value=''
  try {
    await http.put(`/wristband-reader/bindings/${row.wristband_id}`, {chip_uid:clean,version:row.version,
      ...(row.version>0 && clean!==row.chip_uid ? {password:password.value} : {})})
    if(!current()) return
    dialog.value=false; password.value=''; uid.value=''; ElMessage.success(`${row.number} 号手牌芯片已保存`); await load()
  } catch (failure) { if(current()) error.value=apiErrorMessage(failure) }
  finally {if(current()) saving.value=false}
}
async function unbind(row:Binding) {
  if (!allowed.value || !row.chip_uid || row.status!=='available' || saving.value) return
  const current=guard('change')
  try {
    const {value}=await ElMessageBox.prompt(`解除 ${row.number} 号芯片绑定。请验证 ${auth.employee?.username || '当前账号'} 本人的登录密码。`,
      '解除手牌绑定',{inputType:'password',inputPattern:/\S+/,inputErrorMessage:'请输入本人密码',type:'warning'})
    if(!current()) return
    saving.value=true
    await http.delete(`/wristband-reader/bindings/${row.wristband_id}`,{data:{password:value,version:row.version}})
    if(!current()) return
    ElMessage.success('已解除芯片绑定'); await load()
  } catch (failure) {if(current() && failure!=='cancel' && failure!=='close') ElMessage.error(apiErrorMessage(failure))}
  finally {if(current()) saving.value=false}
}
onMounted(() => {void load();unsubscribe=subscribeRealtime(['wristbands'],()=>load())})
onBeforeUnmount(()=>unsubscribe?.())
</script>

<template>
  <div class="page binding-page">
    <AppPageHeader title="手牌ID录入" description="选择手牌、刷入芯片 ID 后保存。录入页面不会自动开牌。" />
    <el-alert v-if="!allowed" title="无手牌 ID 录入权限" type="warning" :closable="false" />
    <template v-else>
      <div class="binding-summary"><strong>已录入 {{ bound }}</strong><span>未录入 {{ rows.length-bound }}</span><span>仅空闲手牌可更换或解除绑定</span></div>
      <section class="binding-table" v-loading="loading">
        <div class="binding-toolbar">
          <el-radio-group v-model="area"><el-radio-button value="all">全部</el-radio-button><el-radio-button value="male">男浴</el-radio-button><el-radio-button value="female">女浴</el-radio-button></el-radio-group>
          <el-input v-model="keyword" placeholder="搜索手牌号 / 芯片 ID" clearable style="width:240px" />
          <el-button @click="load">刷新</el-button>
          <el-pagination v-model:current-page="page" :page-size="10" :total="filtered.length" layout="prev,pager,next" />
        </div>
        <el-table :data="visible" row-key="wristband_id">
          <el-table-column prop="number" label="手牌号" width="100" />
          <el-table-column label="浴区" width="90"><template #default="{row}">{{ row.bath_area==='male'?'男浴':'女浴' }}</template></el-table-column>
          <el-table-column label="绑定状态" width="110"><template #default="{row}"><el-tag :type="row.chip_uid?'success':'info'">{{ row.chip_uid?'已录入':'未录入' }}</el-tag></template></el-table-column>
          <el-table-column label="芯片 ID"><template #default="{row}"><code>{{ row.chip_uid || '—' }}</code></template></el-table-column>
          <el-table-column label="最近修改"><template #default="{row}">{{ row.updated_at?new Date(row.updated_at).toLocaleString():'—' }}</template></el-table-column>
          <el-table-column label="操作" width="210"><template #default="{row}">
            <el-button data-testid="bind-chip" :disabled="row.status!=='available'||saving" @click="edit(row)">{{ row.chip_uid?'更换绑定':'录入芯片' }}</el-button>
            <el-button v-if="row.chip_uid" type="danger" plain :disabled="row.status!=='available'||saving" @click="unbind(row)">解除</el-button>
          </template></el-table-column>
        </el-table>
      </section>
      <el-dialog v-model="dialog" :title="`${selected?.number || ''} 号手牌 · ${selected?.chip_uid?'更换绑定':'录入芯片'}`" width="460px" :close-on-click-modal="false" :before-close="closeDialog">
        <p>请刷手牌，读卡器数字会填入下方。核对后点击保存。</p>
        <label class="field-label" for="wristband-chip">芯片 ID</label>
        <input id="wristband-chip" ref="uidInput" v-model="uid" data-testid="chip-uid" inputmode="numeric" autocomplete="off" maxlength="64" class="chip-input" @keydown.enter.stop.prevent />
        <template v-if="(selected?.version || 0)>0">
          <label class="field-label">当前登录账号密码（{{ auth.employee?.username }}）</label>
          <el-input v-model="password" type="password" show-password autocomplete="off" placeholder="更换芯片需本人密码" />
        </template>
        <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-top:14px" />
        <template #footer><el-button :disabled="saving" @click="dialog=false;password='';uid=''">取消</el-button><el-button data-testid="save-chip" type="primary" :loading="saving" @click="save">保存绑定</el-button></template>
      </el-dialog>
    </template>
  </div>
</template>

<style scoped>
.binding-summary{display:flex;gap:24px;align-items:center;margin:16px 0;color:var(--xq-text-2)}
.binding-table{padding:18px;background:white;border:1px solid var(--xq-border);border-radius:12px}
.binding-toolbar{display:flex;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap}.binding-toolbar .el-pagination{margin-left:auto}
.field-label{display:block;margin:16px 0 8px}.chip-input{box-sizing:border-box;width:100%;padding:12px;border:1px solid var(--xq-border);border-radius:6px;font:18px monospace}.chip-input:focus{outline:2px solid var(--xq-primary)}
</style>
