<script setup lang="ts">
import { canAccess, canCapability, useBusinessGuard } from '../business/state'
const guardBusinessOperation = useBusinessGuard()

import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiData, apiErrorMessage, http } from '../api/http'
import AppPageHeader from '../components/app/AppPageHeader.vue'
import MemberDetailDrawer from '../components/members/MemberDetailDrawer.vue'
import MemberTypeBadge from '../components/members/MemberTypeBadge.vue'
import { subscribeRealtime } from '../realtime/events'
import { clearPendingRequestKey, pendingRequestKey } from '../domain/requests/pending-key'
import type { Member } from '../types'

type CardFilter = 'all' | 'stored' | 'pass'

const route = useRoute()
const router = useRouter()
const rows = ref<Member[]>([])
const deleting = ref(false)
const keyword = ref('')
const cardFilter = ref<CardFilter>(['stored', 'pass'].includes(String(route.query.tab)) ? String(route.query.tab) as CardFilter : 'all')
const createOpen = ref(false)
const detailOpen = ref(false)
const selected = ref<Member | null>(null)
const detailTab = ref<'stored' | 'pass'>(route.query.tab === 'pass' ? 'pass' : 'stored')
let unsubscribeRealtime: (() => void) | undefined
const createForm = reactive({ phone: '', name: '', note: '' })

const filteredRows = computed(() => rows.value.filter((row) => {
  if (cardFilter.value === 'stored') return row.has_stored_value
  if (cardFilter.value === 'pass') return row.has_pass
  return true
}))
const counts = computed(() => ({
  all: rows.value.length,
  stored: rows.value.filter((row) => row.has_stored_value).length,
  pass: rows.value.filter((row) => row.has_pass).length,
}))

async function load(silent = false) {
  const isCurrent = guardBusinessOperation('load')
  if (!isCurrent()) return

  try {
    const data = apiData<Member[]>(await http.get('/members', { params: { keyword: keyword.value } })); if (!isCurrent()) return; rows.value = data
  } catch (error) { if (!isCurrent()) return; 
    if (!silent) ElMessage.error(apiErrorMessage(error))
  }
}

async function remove(row: Member) {
  if (deleting.value || !canCapability('member_delete') || !canAccess('member:delete')) return
  const isCurrent = guardBusinessOperation('delete')
  if (!isCurrent()) return
  deleting.value = true
  try {
    const { value } = await ElMessageBox.prompt(`确认删除会员“${row.name || row.phone}”？有余额、剩余次数或未结账消费时不能删除。请输入本人登录密码。`, '删除会员', {inputType:'password', inputPattern:/\S+/, inputErrorMessage:'请输入本人登录密码', type:'warning', confirmButtonText:'确认删除'})
    if (!isCurrent()) return
    await http.delete(`/members/${row.id}`, {data:{password:value}})
    if (!isCurrent()) return
    rows.value = rows.value.filter(item => item.id !== row.id)
    if (selected.value?.id === row.id) { selected.value = null; detailOpen.value = false }
    ElMessage.success('会员已删除')
  } catch(error) { if (isCurrent() && error !== 'cancel' && error !== 'close') ElMessage.error(apiErrorMessage(error)) }
  finally { if (isCurrent()) deleting.value = false }
}

async function createMember() {
  const isCurrent = guardBusinessOperation('createMember')
  if (!isCurrent()) return

  try {
    await http.post('/members', createForm); if (!isCurrent()) return;
    ElMessage.success('会员创建成功')
    createOpen.value = false
    Object.assign(createForm, { phone: '', name: '', note: '' })
    await load(); if (!isCurrent()) return;
  } catch (error) { if (!isCurrent()) return; 
    ElMessage.error(apiErrorMessage(error))
  }
}

async function showDetail(row: Member) {
  const isCurrent = guardBusinessOperation('showDetail')
  if (!isCurrent()) return

  try {
    const data = apiData<Member>(await http.get(`/members/${row.id}`)); if (!isCurrent()) return; selected.value = data
    detailOpen.value = true
  } catch (error) { if (!isCurrent()) return; 
    ElMessage.error(apiErrorMessage(error))
  }
}

async function startRecharge(row: Member) {
  const isCurrent = guardBusinessOperation('startRecharge')
  if (!isCurrent()) return

  try {
    const { value } = await ElMessageBox.prompt('请输入本次储值金额', `会员充值：${row.name || row.phone}`, {
      inputType: 'number',
      inputPlaceholder: '例如：500',
      inputPattern: /^(?:0\.(?:0[1-9]|[1-9]\d?)|[1-9]\d*(?:\.\d{1,2})?)$/,
      inputErrorMessage: '请输入大于 0、最多两位小数的金额',
      confirmButtonText: '去支付',
    }); if (!isCurrent()) return;
    detailOpen.value = false
    await router.push({ path: `/members/${row.id}/recharge`, query: { amount: value } }); if (!isCurrent()) return;
  } catch (error) { if (!isCurrent()) return; 
    if (error !== 'cancel') ElMessage.error(apiErrorMessage(error))
  }
}

async function startPassPurchase(row: Member) {
  const isCurrent = guardBusinessOperation('startPassPurchase')
  if (!isCurrent()) return

  detailOpen.value = false
  await router.push(`/members/${row.id}/pass-purchase`); if (!isCurrent()) return;
}

async function consumePass(passId: string) {
  const isCurrent = guardBusinessOperation('consumePass')
  if (!isCurrent()) return

  if (!selected.value) return
  const scope = `pass:${passId}:consume`
  const key = pendingRequestKey(scope, passId)
  try {
    await http.post(`/members/passes/${passId}/consume`, {}, { headers: { 'Idempotency-Key': key } }); if (!isCurrent()) return;
    clearPendingRequestKey(scope)
    ElMessage.success('核销成功')
    await showDetail(selected.value); if (!isCurrent()) return;
    await load(true); if (!isCurrent()) return;
  } catch (error) { if (!isCurrent()) return; 
    ElMessage.error(apiErrorMessage(error))
  }
}

onMounted(async () => {
  const isCurrent = guardBusinessOperation('callback3571')
  if (!isCurrent()) return

  await load(); if (!isCurrent()) return;
  const memberId = String(route.query.member || '')
  const member = rows.value.find((row) => row.id === memberId)
  if (member) await showDetail(member); if (!isCurrent()) return;
  unsubscribeRealtime = subscribeRealtime(['members'], () => load(true))
})
onBeforeUnmount(() => unsubscribeRealtime?.())
</script>

<template>
  <div class="page member-page">
    <AppPageHeader title="会员管理" description="储值余额与次卡次数分别展示，所有开卡先完成真实收款。" eyebrow="MEMBERS"><template #actions><el-input v-model="keyword" clearable placeholder="手机号或姓名" @keyup.enter="load()" /><el-button @click="load()">查询</el-button><el-button type="primary" @click="createOpen = true">新增会员</el-button></template></AppPageHeader>

    <div class="card-filters">
      <button :class="{ active: cardFilter === 'all' }" @click="cardFilter = 'all'"><span>全部会员</span><strong>{{ counts.all }}</strong><small>完整会员列表</small></button>
      <button class="stored" :class="{ active: cardFilter === 'stored' }" @click="cardFilter = 'stored'"><span>储值卡会员</span><strong>{{ counts.stored }}</strong><small>当前有储值余额</small></button>
      <button class="pass" :class="{ active: cardFilter === 'pass' }" @click="cardFilter = 'pass'"><span>次卡会员</span><strong>{{ counts.pass }}</strong><small>当前有可用次数</small></button>
    </div>

    <el-card shadow="never">
      <el-table :data="filteredRows" @row-dblclick="showDetail">
        <el-table-column prop="phone" label="手机号" width="145" />
        <el-table-column prop="name" label="姓名" min-width="100" />
        <el-table-column label="会员卡类型" width="190">
          <template #default="scope"><MemberTypeBadge :member="scope.row" /></template>
        </el-table-column>
        <el-table-column label="储值余额" width="140"><template #default="scope"><span :class="{ money: scope.row.has_stored_value }">¥{{ scope.row.balance }}</span></template></el-table-column>
        <el-table-column label="次卡" min-width="150"><template #default="scope"><span v-if="scope.row.has_pass"><b>{{ scope.row.active_pass_count }}</b> 张，剩余 <b>{{ scope.row.pass_remaining }}</b> 次</span><span v-else class="muted">无可用次卡</span></template></el-table-column>
        <el-table-column label="状态" width="86"><template #default="scope"><el-tag :type="scope.row.is_active ? 'success' : 'info'">{{ scope.row.is_active ? '正常' : '停用' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="280"><template #default="scope"><el-button link type="success" @click="startRecharge(scope.row)">储值</el-button><el-button link type="warning" @click="startPassPurchase(scope.row)">买次卡</el-button><el-button link type="primary" @click="showDetail(scope.row)">详情</el-button><el-button v-if="canCapability('member_delete') && canAccess('member:delete')" data-testid="member-delete" link type="danger" :disabled="deleting" @click="remove(scope.row)">删除</el-button></template></el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="createOpen" title="新增会员" width="460px">
      <el-form label-position="top"><el-form-item label="手机号"><el-input v-model="createForm.phone" /></el-form-item><el-form-item label="姓名"><el-input v-model="createForm.name" /></el-form-item><el-form-item label="备注"><el-input v-model="createForm.note" /></el-form-item></el-form>
      <template #footer><el-button @click="createOpen = false">取消</el-button><el-button type="primary" @click="createMember">保存</el-button></template>
    </el-dialog>

    <MemberDetailDrawer v-model="detailOpen" v-model:active-tab="detailTab" :member="selected" @recharge="startRecharge" @purchase-pass="startPassPurchase" @consume-pass="consumePass" />
  </div>
</template>

<style scoped>
.card-filters { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 18px; }
.card-filters button { display: grid; grid-template-columns: 1fr auto; gap: 5px; padding: 17px 19px; text-align: left; color: #56647a; background: white; border: 2px solid transparent; border-radius: 14px; cursor: pointer; box-shadow: 0 4px 16px rgba(34, 54, 82, .06); }
.card-filters button.active { border-color: #6579ee; background: #f4f6ff; }
.card-filters button.stored.active { border-color: #24b88d; background: #effbf7; }
.card-filters button.pass.active { border-color: #e8a13a; background: #fff8ec; }
.card-filters span { font-weight: 700; }
.card-filters strong { grid-row: 1 / 3; grid-column: 2; align-self: center; font-size: 27px; color: #23364f; }
.card-filters small { color: #98a3b2; }
.card-tags { display: flex; gap: 6px; }
.pane-header { display: flex; align-items: center; justify-content: space-between; }
.pane-header strong, .pane-header span { display: block; }
.pane-header span { margin-top: 4px; font-size: 12px; }
</style>
