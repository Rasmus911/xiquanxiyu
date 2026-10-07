<script setup lang="ts">
import { useBusinessGuard } from '../business/state'
const guardBusinessOperation = useBusinessGuard()

import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiData, apiErrorMessage, http } from '../api/http'
import AppPageHeader from '../components/app/AppPageHeader.vue'
import { usePageRefresh } from '../composables/usePageRefresh'
import { clearPendingRequestKey, pendingRequestKey } from '../domain/requests/pending-key'
import { useRuntimeStore } from '../stores/runtime'
import type { Member } from '../types'

interface SmsNotification { success: boolean; message: string }
const route = useRoute()
const router = useRouter()
const runtime = useRuntimeStore()
const member = ref<Member | null>(null)
const name = ref('洗浴10次卡')
const count = ref(10)
const amount = ref(300)
const validUntil = ref('')
const note = ref('')
const method = ref<'cash' | 'wechat' | 'alipay'>('cash')
const loading = ref(false)
const valid = computed(() => count.value > 0 && amount.value > 0 && name.value.trim().length > 0)
const methods = [{ value: 'cash', label: '现金' }, { value: 'wechat', label: '微信' }, { value: 'alipay', label: '支付宝' }] as const

async function load() {
  const isCurrent = guardBusinessOperation('load')
  if (!isCurrent()) return

  try { const data = apiData<Member>(await http.get(`/members/${route.params.id}`)); if (!isCurrent()) return; member.value = data } catch (error) { if (!isCurrent()) return;  ElMessage.error(apiErrorMessage(error)) }
}

async function complete() {
  const isCurrent = guardBusinessOperation('complete')
  if (!isCurrent()) return

  if (!member.value || !valid.value) return ElMessage.warning('请完整填写次卡次数和收款金额')
  try {
    await ElMessageBox.confirm(`确认已收到 ${methods.find((row) => row.value === method.value)?.label} ¥${amount.value.toFixed(2)}，并开通 ${count.value} 次？`, '确认次卡收款', { type: 'warning', confirmButtonText: '确认收款并开卡' }); if (!isCurrent()) return;
  } catch { if (!isCurrent()) return;  return }
  const scope = `member:${member.value.id}:pass-purchase`
  const fingerprint = `${member.value.id}|${name.value}|${count.value}|${amount.value.toFixed(2)}|${method.value}|${validUntil.value}`
  const key = pendingRequestKey(scope, fingerprint)
  loading.value = true
  const releaseBusy = await runtime.setBusinessBusy('正在完成次卡收款')
  if (!isCurrent()) { await releaseBusy(); return }
  try {
    const result = apiData<{ sms_notifications?: SmsNotification[] }>(await http.post(`/members/${member.value.id}/passes`, {
      name: name.value, count: count.value, amount: amount.value, payment_method: method.value,
      valid_until: validUntil.value || null, note: note.value, idempotency_key: key,
    }, { headers: { 'Idempotency-Key': key } })); if (!isCurrent()) return;
    clearPendingRequestKey(scope)
    if (result.sms_notifications?.some((row) => !row.success)) ElMessage.warning('次卡已开通，但短信未全部发送')
    else ElMessage.success('次卡收款并开通成功')
    await router.replace({ path: '/members', query: { member: member.value.id, tab: 'pass' } }); if (!isCurrent()) return;
  } catch (error) { if (isCurrent()) ElMessage.error(apiErrorMessage(error)) }
  finally { if (isCurrent()) loading.value = false; await releaseBusy() }
}
usePageRefresh(load)
onMounted(load)
</script>

<template><div class="page pass-page"><AppPageHeader title="购买次卡" description="记录真实收款后开通次数，避免次卡收入遗漏或重复计算。" eyebrow="MEMBER PASS" /><div class="pass-layout"><el-card shadow="never"><template #header><strong>次卡内容</strong></template><div class="member-line"><strong>{{ member?.name || '会员' }}</strong><span>{{ member?.phone }}</span></div><el-form label-position="top"><el-form-item label="次卡名称"><el-input v-model="name" /></el-form-item><el-row :gutter="12"><el-col :span="12"><el-form-item label="总次数"><el-input-number v-model="count" :min="1" class="full-width" /></el-form-item></el-col><el-col :span="12"><el-form-item label="有效期"><el-date-picker v-model="validUntil" value-format="YYYY-MM-DD" placeholder="可选" class="full-width" /></el-form-item></el-col></el-row><el-form-item label="备注"><el-input v-model="note" placeholder="选填" /></el-form-item></el-form></el-card><el-card shadow="never"><template #header><strong>收款确认</strong></template><el-form label-position="top"><el-form-item label="次卡售价"><el-input-number v-model="amount" :min="0.01" :precision="2" :controls="false" class="amount-input" /></el-form-item></el-form><div class="method-list"><button v-for="row in methods" :key="row.value" :class="{ active: method === row.value }" @click="method = row.value">{{ row.label }}</button></div><div class="amount-due"><span>本次应收</span><strong>¥{{ amount > 0 ? amount.toFixed(2) : '0.00' }}</strong></div><el-button type="success" size="large" class="full-width" :loading="loading" :disabled="!valid" @click="complete">确认收款并开卡</el-button></el-card></div></div></template>
<style scoped>.pass-page{max-width:1040px;margin:0 auto}.pass-layout{display:grid;grid-template-columns:1fr 1fr;gap:18px}.member-line{display:flex;justify-content:space-between;margin-bottom:16px;color:var(--xq-text-2)}.amount-input{width:100%}.amount-input :deep(.el-input__inner){height:50px;font-size:23px;font-weight:800}.method-list{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.method-list button{padding:13px;cursor:pointer;border:1px solid var(--xq-border);border-radius:10px;background:white}.method-list button.active{color:var(--xq-primary);border-color:var(--xq-primary);background:var(--xq-primary-soft)}.amount-due{display:flex;justify-content:space-between;margin:20px 0;padding:16px;border-radius:12px;background:var(--xq-bg-page)}.amount-due strong{color:var(--xq-danger);font-size:26px}</style>
