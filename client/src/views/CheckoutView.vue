<script setup lang="ts">
import { useBusinessGuard } from '../business/state'
const guardBusinessOperation = useBusinessGuard()

import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { apiData, apiErrorMessage, http } from '../api/http'
import AppPageHeader from '../components/app/AppPageHeader.vue'
import PaymentPanel from '../components/checkout/PaymentPanel.vue'
import VisitSelector from '../components/checkout/VisitSelector.vue'
import { checkoutFingerprint, checkoutRequestKey, clearCheckoutRequest } from '../domain/checkout/checkout-request'
import { applyMemberBalance, fillRemaining, paymentPayload, paymentSummary, type MixedPayment } from '../domain/checkout/mixed-payments'
import { initialCheckoutSelection, toggleCheckoutVisit } from '../domain/checkout/selection'
import { subscribeRealtime } from '../realtime/events'
import { useAuthStore } from '../stores/auth'
import { useConnectivityStore } from '../stores/connectivity'
import { useRuntimeStore } from '../stores/runtime'
import type { Member } from '../types'

interface Preview { visits: Array<{ visit_id: string; wristband_number: string; amount: string }>; total_amount: string; auto_included_linked_visits?: number; checkout_scope?: 'party' | 'selected' }

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const runtime = useRuntimeStore()
const connectivity = useConnectivityStore()
const preview = ref<Preview | null>(null)
const availableVisits = ref<Preview['visits']>([])
const selectedVisitIds = ref<string[]>([])
const loading = ref(false)
const uncertainPayment = ref(false)
const formLocked = computed(() => loading.value || uncertainPayment.value)
type PendingCheckout = { visit_ids: string[]; checkout_scope: 'selected'; member_id: string | null;
  payments: ReturnType<typeof paymentPayload>; idempotency_key: string }
let pendingCheckout: PendingCheckout | null = null
let releasePaymentBusy: (() => Promise<void>) | null = null
let settlementConfirmed = false
const payments = reactive<MixedPayment[]>(['cash', 'wechat', 'alipay', 'balance'].map(method => ({ method, amount: 0, reference: '' })))
const automaticCash = ref(true)
const memberId = ref('')
const memberPhone = ref('')
const selectedMember = ref<Member | null>(null)
const entryVisitIds = computed(() => String(route.query.visits || '').split(',').filter(Boolean))
const checkoutScope = computed<'party' | 'selected'>(() => route.query.scope === 'selected' ? 'selected' : 'party')
const isIndividualCheckout = computed(() => selectedVisitIds.value.length < availableVisits.value.length)
const summary = computed(() => paymentSummary(preview.value?.total_amount || '0.00', payments))
const paid = computed(() => summary.value.paid)
const balanced = computed(() => summary.value.balanced && summary.value.valid)
let refreshTimer: number | undefined
let unsubscribeRealtime: (() => void) | undefined

async function load(silent = false) {
  if (formLocked.value) return
  const isCurrent = guardBusinessOperation('load')
  if (!isCurrent()) return

  if (!selectedVisitIds.value.length) return
  try {
    const previousTotal = preview.value?.total_amount
    const nextPreview = apiData<Preview>(await http.post('/checkout/preview', {
      visit_ids: selectedVisitIds.value,
      checkout_scope: 'selected',
    })); if (!isCurrent()) return;
    const canAutoBalance = automaticCash.value && payments.slice(1).every(row => !row.amount) && (!previousTotal || Number(payments[0].amount) === Number(previousTotal))
    preview.value = nextPreview
    if (canAutoBalance) payments[0].amount = Number(nextPreview.total_amount)
  } catch (error) { if (!isCurrent()) return; 
    if (!silent) ElMessage.error(apiErrorMessage(error))
  }
}

async function initialize() {
  const isCurrent = guardBusinessOperation('initialize')
  if (!isCurrent()) return

  resetMember()
  try {
    const discovery = apiData<Preview>(await http.post('/checkout/preview', {
      visit_ids: entryVisitIds.value,
      checkout_scope: 'party',
    })); if (!isCurrent()) return;
    availableVisits.value = discovery.visits
    selectedVisitIds.value = initialCheckoutSelection(
      discovery.visits,
      entryVisitIds.value[0] || '',
      checkoutScope.value,
    )
    await load(); if (!isCurrent()) return;
  } catch (error) { if (!isCurrent()) return; 
    ElMessage.error(apiErrorMessage(error))
  }
}

async function toggleVisit(visitId: string) {
  if (formLocked.value) return
  const isCurrent = guardBusinessOperation('toggleVisit')
  if (!isCurrent()) return

  const next = toggleCheckoutVisit(selectedVisitIds.value, visitId)
  if (next === selectedVisitIds.value) return ElMessage.warning('至少保留一个手牌进行结账')
  selectedVisitIds.value = next
  await load(); if (!isCurrent()) return;
}

function fillPayment(index: number) {
  if (formLocked.value || !preview.value) return
  if (payments[index]?.method === 'balance' && !selectedMember.value) {
    return ElMessage.warning('请先输入完整手机号并查询会员')
  }
  try {
    if (payments[index]?.method === 'balance') {
      applyMemberBalance(preview.value.total_amount, payments, selectedMember.value!.balance, automaticCash.value)
    } else {
      fillRemaining(preview.value.total_amount, payments, index)
    }
    automaticCash.value = false
  } catch (error) { ElMessage.warning(error instanceof Error ? error.message : '请检查支付金额') }
}

function resetMember() {
  memberPhone.value = ''
  selectedMember.value = null
  memberId.value = ''
  payments.find(row => row.method === 'balance')!.amount = 0
}

async function findMember() {
  if (formLocked.value) return
  const isCurrent = guardBusinessOperation('findMember')
  if (!isCurrent()) return

  selectedMember.value = null
  memberId.value = ''
  const normalizedPhone = memberPhone.value.replace(/\D/g, '')
  if (!/^1\d{10}$/.test(normalizedPhone)) return ElMessage.warning('请输入完整的 11 位会员手机号')
  try {
    const data = apiData<Member>(await http.get('/members/lookup', { params: { phone: normalizedPhone } })); if (!isCurrent() || memberPhone.value.replace(/\D/g, '') !== normalizedPhone) return; selectedMember.value = data
    memberId.value = selectedMember.value?.id || ''
  } catch (error) { if (!isCurrent()) return; 
    ElMessage.error(apiErrorMessage(error))
  }
}

watch(memberPhone, () => {
  if (selectedMember.value?.phone.replace(/\D/g, '') !== memberPhone.value.replace(/\D/g, '')) {
    selectedMember.value = null
    memberId.value = ''
    payments.find(row => row.method === 'balance')!.amount = 0
  }
})

async function complete() {
  if (loading.value) return
  const isCurrent = guardBusinessOperation('complete')
  if (!isCurrent()) return

  if (!pendingCheckout && !balanced.value) return ElMessage.warning('支付合计必须等于应收金额')
  if (!pendingCheckout && payments.some((row) => row.method === 'balance' && Number(row.amount) > 0) && !selectedMember.value) {
    return ElMessage.warning('请重新输入完整手机号并查询储值卡会员')
  }
  const memberPayment = Number(payments.find(row => row.method === 'balance')?.amount || 0)
  if (!pendingCheckout && memberPayment > Number(selectedMember.value?.balance || 0)) {
    return ElMessage.warning('会员余额不足，请使用可用余额，剩余金额用其他方式补齐')
  }
  loading.value = true
  if (!releasePaymentBusy) releasePaymentBusy = await runtime.setBusinessBusy('正在确认收款，未确认结果前不能更新或退出')
  if (!isCurrent()) { await releasePaymentBusy(); releasePaymentBusy = null; return }
  if (!pendingCheckout) {
    const activePayments = paymentPayload(payments)
    const key = checkoutRequestKey(checkoutFingerprint(selectedVisitIds.value, activePayments.map(row => ({ ...row, amount: Number(row.amount) })), memberId.value))
    pendingCheckout = { visit_ids: [...selectedVisitIds.value], checkout_scope: 'selected', member_id: memberId.value || null,
      payments: activePayments, idempotency_key: key }
  }
  const requestBody = pendingCheckout
  let settlementKnown = false
  try {
    const settlement = apiData<{ id: string; number: string }>(await http.post('/checkout', requestBody,
      { headers: { 'Idempotency-Key': requestBody.idempotency_key } })); if (!isCurrent()) return;
    settlementKnown = true
    settlementConfirmed = true
    uncertainPayment.value = false
    pendingCheckout = null
    clearCheckoutRequest()
    ElMessage.success(`结账成功：${settlement.number}`)
    const receipt = apiData<Record<string, unknown>>(await http.get(`/checkout/${settlement.id}/receipt`)); if (!isCurrent()) return;
    const printerName = auth.terminal?.printer_name || localStorage.getItem('xiquan_printer_name') || undefined
    const result = window.xiquan
      ? await window.xiquan.printReceipt(receipt, printerName)
      : { success: false, error: '浏览器模式不支持静默打印' }; if (!isCurrent()) return;
    await http.post(`/checkout/${settlement.id}/print-result`, result); if (!isCurrent()) return;
    if (!result.success) {
      ElMessage.warning(`结账已成功，小票待补打：${result.error}`)
      await router.replace('/print-jobs'); if (!isCurrent()) return;
    } else {
      await router.replace('/'); if (!isCurrent()) return;
    }
  } catch (error) { if (!isCurrent()) return;
    const code = typeof error === 'object' && error && 'code' in error ? String(error.code) : ''
    const response = typeof error === 'object' && error && 'response' in error ? error.response as { status?: number } | undefined : undefined
    if (!settlementKnown && (['ECONNABORTED', 'ETIMEDOUT', 'ERR_NETWORK'].includes(code) || (response?.status || 0) >= 500)) {
      uncertainPayment.value = true
      ElMessage.warning('收款结果待确认，金额已锁定；请点击“确认上次收款结果”，不要重新收钱。')
    } else {
      uncertainPayment.value = false
      pendingCheckout = null
      if (settlementKnown) {
        ElMessage.warning(`结账已成功，请勿重复收款；小票可到补打页面处理：${apiErrorMessage(error)}`)
        await router.replace('/print-jobs')
      } else {
        ElMessage.error(apiErrorMessage(error))
      }
    }
  } finally {
    if (isCurrent()) loading.value = false
    if (!uncertainPayment.value || !isCurrent()) {
      await releasePaymentBusy?.()
      releasePaymentBusy = null
    }
  }
}

onMounted(() => {
  initialize()
  unsubscribeRealtime = subscribeRealtime(['visits', 'wristbands', 'members'], () => load(true))
  refreshTimer = window.setInterval(() => {
    if (!connectivity.isOnline && document.visibilityState === 'visible') load(true)
  }, 30_000)
})

onBeforeRouteLeave(() => {
  if (formLocked.value && !settlementConfirmed) { ElMessage.warning('请先确认当前收款结果，再离开收款页面'); return false }
  resetMember()
})

onBeforeUnmount(() => {
  unsubscribeRealtime?.()
  if (refreshTimer) window.clearInterval(refreshTimer)
})
</script>

<template>
  <div class="page checkout-page">
    <AppPageHeader :title="isIndividualCheckout ? '选择手牌结账' : '统一结账'" description="先确认本次结账手牌，再填写支付方式；收款成功与打印小票相互独立。" eyebrow="CHECKOUT" />
    <el-card shadow="never" class="checkout-card">
      <section class="checkout-step">
        <div class="step-title"><div><strong>1. 选择本次结账手牌</strong><span>未选中的联动手牌会继续使用，不受本次结账影响</span></div><b>应收 ¥{{ preview?.total_amount || '0.00' }}</b></div>
        <VisitSelector :visits="availableVisits" :selected-ids="selectedVisitIds" @toggle="!formLocked && toggleVisit($event)" />
        <el-alert v-if="isIndividualCheckout" type="warning" :closable="false" show-icon title="本次只结所选手牌；结账后，其余联动手牌仍可继续消费。" />
      </section>
      <el-divider />
      <PaymentPanel :payments="payments" :total="preview?.total_amount || '0.00'" :paid="paid" :balanced="balanced" :remaining="summary.remaining" :overpaid="summary.overpaid" :disabled="formLocked" @fill="fillPayment" @change="automaticCash = false" />
      <div class="member-lookup">
        <strong>会员储值验证</strong>
        <div class="toolbar"><el-input v-model="memberPhone" :disabled="formLocked" maxlength="11" placeholder="每次请输入完整的 11 位手机号" @keyup.enter="findMember" /><el-button :disabled="formLocked" @click="findMember">查询会员</el-button><el-button :disabled="formLocked || !selectedMember" @click="fillPayment(3)">使用可用余额</el-button></div>
        <el-alert v-if="selectedMember" type="success" :closable="false" :title="`${selectedMember.name || selectedMember.phone}，余额 ¥${selectedMember.balance}`" />
      </div>
      <el-divider />
      <el-alert v-if="uncertainPayment" type="warning" :closable="false" show-icon title="上次收款结果待确认：请勿重新收钱。金额和手牌已锁定，点击下方按钮确认原结果。" />
      <section class="submit-step"><div><strong>3. 确认收款</strong><span>收款完成后即视为结账成功；打印失败请到“小票补打”处理。</span></div><el-button type="success" size="large" :loading="loading" :disabled="!uncertainPayment && (!balanced || !selectedVisitIds.length)" @click="complete">{{ uncertainPayment ? '确认上次收款结果' : `确认收款 ¥${preview?.total_amount || '0.00'}` }}</el-button></section>
    </el-card>
  </div>
</template>

<style scoped>
.checkout-page { max-width: 1040px; margin: 0 auto; }
.checkout-card { border-radius: var(--xq-radius-lg); }
.checkout-step { display: grid; gap: 14px; }
.step-title, .submit-step { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.step-title strong, .step-title span, .submit-step strong, .submit-step span { display: block; }
.step-title span, .submit-step span { margin-top: 4px; color: var(--xq-text-3); font-size: 11px; }
.step-title > b { color: var(--xq-danger); font-size: 23px; }
.member-lookup { display: grid; gap: 9px; margin-top: 16px; padding: 14px; border: 1px solid #cfe0ff; border-radius: 11px; background: #f6f9ff; }
.member-lookup .toolbar { justify-content: flex-start; }
.member-lookup .el-input { max-width: 330px; }
</style>
