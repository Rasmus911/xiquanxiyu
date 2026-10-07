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

interface SmsNotification { recipient: 'member' | 'admin'; success: boolean; message: string }

const route = useRoute()
const router = useRouter()
const runtime = useRuntimeStore()
const member = ref<Member | null>(null)
const amount = ref(Number(route.query.amount || 0))
const method = ref<'cash' | 'wechat' | 'alipay'>('cash')
const note = ref('')
const loading = ref(false)

const methods = [
  { value: 'cash', label: '现金支付', description: '收取现金后确认', color: '#28b98b' },
  { value: 'wechat', label: '微信支付', description: '确认顾客微信到账', color: '#23b15d' },
  { value: 'alipay', label: '支付宝', description: '确认顾客支付宝到账', color: '#248df5' },
] as const
const amountValid = computed(() => Number.isFinite(amount.value) && amount.value > 0)

async function load() {
  const isCurrent = guardBusinessOperation('load')
  if (!isCurrent()) return

  try {
    const data = apiData<Member>(await http.get(`/members/${route.params.id}`)); if (!isCurrent()) return; member.value = data
  } catch (error) { if (!isCurrent()) return; 
    ElMessage.error(apiErrorMessage(error))
  }
}

async function completeRecharge() {
  const isCurrent = guardBusinessOperation('completeRecharge')
  if (!isCurrent()) return

  if (!member.value || !amountValid.value) return ElMessage.warning('请输入正确的储值金额')
  const selectedMethod = methods.find((row) => row.value === method.value)
  try {
    await ElMessageBox.confirm(
      `确认已收到 ${selectedMethod?.label} ¥${amount.value.toFixed(2)}？确认后储值立即到账。`,
      '确认充值收款',
      { type: 'warning', confirmButtonText: '确认到账并充值' },
    ); if (!isCurrent()) return;
  } catch { if (!isCurrent()) return; 
    return
  }

  loading.value = true
  const releaseBusy = await runtime.setBusinessBusy('正在完成会员充值')
  if (!isCurrent()) { await releaseBusy(); return }
  const scope = `member:${member.value.id}:recharge`
  const fingerprint = `${member.value.id}|${amount.value.toFixed(2)}|${method.value}|${note.value}`
  const key = pendingRequestKey(scope, fingerprint)
  try {
    const result = apiData<Member & { sms_notifications?: SmsNotification[] }>(await http.post(`/members/${member.value.id}/recharge`, {
      amount: amount.value,
      payment_method: method.value,
      note: note.value,
      idempotency_key: key,
    }, { headers: { 'Idempotency-Key': key } })); if (!isCurrent()) return;
    clearPendingRequestKey(scope)
    if (!result.sms_notifications?.length) {
      ElMessage.success(`充值成功，当前余额 ¥${result.balance}`)
    } else if (result.sms_notifications.every((row) => row.success)) {
      ElMessage.success(`开卡成功，当前余额 ¥${result.balance}，会员和管理员短信已提交`)
    } else {
      const errors = [...new Set(result.sms_notifications.filter((row) => !row.success).map((row) => row.message))]
      ElMessage.warning(`开卡成功，但短信未全部发送：${errors.join('、')}`)
    }
    await router.replace({ path: '/members', query: { member: member.value.id, tab: 'stored' } }); if (!isCurrent()) return;
  } catch (error) { if (!isCurrent()) return; 
    ElMessage.error(apiErrorMessage(error))
  } finally {
    if (isCurrent()) loading.value = false
    await releaseBusy()
  }
}

usePageRefresh(load)
onMounted(load)
</script>

<template>
  <div class="page recharge-page">
    <AppPageHeader title="会员储值支付" description="无需开班，确认真实收款后储值立即到账。" eyebrow="MEMBER VALUE" />
    <div class="recharge-layout">
      <el-card shadow="never" class="order-card">
        <template #header><strong>充值订单</strong></template>
        <div class="member-summary"><div class="avatar">{{ (member?.name || member?.phone || '会').slice(0, 1) }}</div><div><strong>{{ member?.name || '会员' }}</strong><span>{{ member?.phone }}</span></div><div><small>当前余额</small><b>¥{{ member?.balance || '0.00' }}</b></div></div>
        <el-divider />
        <el-form label-position="top"><el-form-item label="储值金额"><el-input-number v-model="amount" :min="0.01" :precision="2" :controls="false" class="amount-input" /></el-form-item><el-form-item label="充值备注"><el-input v-model="note" placeholder="选填" /></el-form-item></el-form>
        <div class="amount-due"><span>本次应收</span><strong>¥{{ amountValid ? amount.toFixed(2) : '0.00' }}</strong></div>
      </el-card>

      <el-card shadow="never" class="pay-card">
        <template #header><div><strong>选择支付方式</strong><div class="muted">请在确认实际到账后完成充值</div></div></template>
        <div class="method-list">
          <button v-for="row in methods" :key="row.value" :class="{ active: method === row.value }" :style="{ '--method-color': row.color }" @click="method = row.value"><i></i><div><strong>{{ row.label }}</strong><span>{{ row.description }}</span></div><el-icon v-if="method === row.value"><CircleCheckFilled /></el-icon></button>
        </div>
        <el-alert v-if="method !== 'cash'" title="当前版本由收银员人工确认微信/支付宝到账，不会自动拉起付款码。" type="warning" :closable="false" show-icon />
        <el-button type="success" size="large" class="full-width pay-button" :loading="loading" :disabled="!amountValid" @click="completeRecharge">确认收款 ¥{{ amountValid ? amount.toFixed(2) : '0.00' }}</el-button>
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.recharge-page { max-width: 1120px; margin: 0 auto; }
.recharge-layout { display: grid; grid-template-columns: .9fr 1.1fr; gap: 20px; }
.order-card, .pay-card { border-radius: 17px; }
.member-summary { display: grid; grid-template-columns: 52px 1fr auto; align-items: center; gap: 13px; }
.avatar { width: 52px; height: 52px; display: grid; place-items: center; border-radius: 15px; color: white; background: var(--xq-primary); font-size: 22px; font-weight: 800; }
.member-summary strong, .member-summary span, .member-summary small, .member-summary b { display: block; }
.member-summary span, .member-summary small { color: #8a96a8; margin-top: 4px; }
.member-summary b { margin-top: 3px; color: var(--xq-danger); font-size: 20px; }
.amount-input { width: 100%; }
.amount-input :deep(.el-input__inner) { height: 52px; text-align: left; font-size: 24px; font-weight: 800; }
.amount-due { display: flex; justify-content: space-between; align-items: center; margin-top: 18px; padding: 18px; border-radius: 13px; background: #f2f7fb; }
.amount-due strong { color: var(--xq-danger); font-size: 30px; }
.method-list { display: grid; gap: 12px; margin-bottom: 18px; }
.method-list button { display: grid; grid-template-columns: 12px 1fr auto; align-items: center; gap: 14px; width: 100%; padding: 16px; text-align: left; color: #42526a; background: white; border: 2px solid #e6ebf2; border-radius: 13px; cursor: pointer; }
.method-list button.active { border-color: var(--method-color); background: #f0f7f4; }
.method-list i { width: 11px; height: 11px; border-radius: 50%; background: var(--method-color); box-shadow: 0 0 0 5px #e5eeeb; }
@supports (background: color-mix(in srgb, black, white)) {
  .method-list button.active { background: color-mix(in srgb, var(--method-color) 7%, white); }
  .method-list i { box-shadow: 0 0 0 5px color-mix(in srgb, var(--method-color) 16%, white); }
}
.method-list strong, .method-list span { display: block; }
.method-list strong { font-size: 16px; }
.method-list span { margin-top: 4px; color: #8995a7; font-size: 12px; }
.method-list .el-icon { color: var(--method-color); font-size: 22px; }
.pay-button { margin-top: 20px; height: 50px; font-size: 17px; }
@media (max-width: 1000px) { .recharge-layout { grid-template-columns: 1fr; } }
</style>
