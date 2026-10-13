<script setup lang="ts">
import { businessGeneration, onBusinessSessionClear, useBusinessGuard } from '../business/state'
const guardBusinessOperation = useBusinessGuard()

import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { apiData, apiErrorMessage, http } from '../api/http'
import AppPageHeader from '../components/app/AppPageHeader.vue'
import PaymentPanel from '../components/checkout/PaymentPanel.vue'
import MemberPaymentSelector from '../components/checkout/MemberPaymentSelector.vue'
import VisitSelector from '../components/checkout/VisitSelector.vue'
import { checkoutFingerprint, checkoutRequestKey, clearCheckoutRequest } from '../domain/checkout/checkout-request'
import { applyMemberBalance, fillRemaining, paymentPayload, paymentSummary, type MixedPayment } from '../domain/checkout/mixed-payments'
import { initialCheckoutSelection, toggleCheckoutVisit } from '../domain/checkout/selection'
import { subscribeRealtime } from '../realtime/events'
import { useAuthStore } from '../stores/auth'
import { useConnectivityStore } from '../stores/connectivity'
import { useRuntimeStore } from '../stores/runtime'
import { printSettlementJob } from '../domain/receipts/printing'
import type { CheckoutBenefits, Member } from '../types'

interface Preview { visits: Array<{ visit_id: string; wristband_number: string; amount: string }>; total_amount: string; amount_due?: string;
  pass_redemption_amount?: string; pass_redemption_count?: number;
  pass_redemptions?: Array<{ visit_id: string; order_item_id: string; member_pass_id: string; count: number; amount: string }>;
  auto_included_linked_visits?: number; checkout_scope?: 'party' | 'selected' }

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const runtime = useRuntimeStore()
const connectivity = useConnectivityStore()
const preview = ref<Preview | null>(null)
const availableVisits = ref<Preview['visits']>([])
const selectedVisitIds = ref<string[]>([])
const loading = ref(false)
const previewing = ref(false)
const memberBusy = ref(false)
const memberReset = ref(0)
const sessionEnded = ref(false)
const uncertainPayment = ref(false)
const formLocked = computed(() => loading.value || uncertainPayment.value || previewing.value || memberBusy.value || sessionEnded.value)
type PendingCheckout = { visit_ids: string[]; checkout_scope: 'selected'; member_id: string | null;
  payments: ReturnType<typeof paymentPayload>; idempotency_key: string } & CheckoutBenefits
let pendingCheckout: PendingCheckout | null = null
let busyLease: Promise<() => Promise<void>> | null = null
watch(formLocked, locked => {
  if (locked && !sessionEnded.value) busyLease = runtime.setBusinessBusy('正在核实结账或确认收款，完成前不能更新或退出')
  else { const lease = busyLease; busyLease = null; void lease?.then(release => release()) }
}, { flush: 'sync' })
let settlementConfirmed = false
const payments = reactive<MixedPayment[]>(['cash', 'wechat', 'alipay', 'balance'].map(method => ({ method, amount: 0, reference: '' })))
const automaticCash = ref(true)
const memberId = ref('')
const selectedMember = ref<Member | null>(null)
const benefits = ref<CheckoutBenefits>({ pass_use: null, member_verification: null })
const verificationReady = computed(() => !selectedMember.value?.holder_surname || benefits.value.member_verification?.surname_confirmed === true)
const amountDue = computed(() => preview.value?.amount_due ?? preview.value?.total_amount ?? '0.00')
const entryVisitIds = computed(() => String(route.query.visits || '').split(',').filter(Boolean))
const checkoutScope = computed<'party' | 'selected'>(() => route.query.scope === 'selected' ? 'selected' : 'party')
const isIndividualCheckout = computed(() => selectedVisitIds.value.length < availableVisits.value.length)
const summary = computed(() => paymentSummary(amountDue.value, payments))
const paid = computed(() => summary.value.paid)
const balanced = computed(() => summary.value.balanced && summary.value.valid)
let previewGeneration = 0
let refreshTimer: number | undefined
let unsubscribeRealtime: (() => void) | undefined

async function load(silent = false) {
  if (loading.value || pendingCheckout || sessionEnded.value) return
  const isCurrent = guardBusinessOperation('load')
  if (!isCurrent()) return
  const owned = ++previewGeneration
  if (!selectedVisitIds.value.length || !verificationReady.value) { preview.value = null; return }
  const identity = checkoutFingerprint(selectedVisitIds.value, [], memberId.value, benefits.value)
  const body = JSON.parse(JSON.stringify({ visit_ids: selectedVisitIds.value, checkout_scope: 'selected', member_id: memberId.value || null, ...benefits.value }))
  previewing.value = true
  try {
    const nextPreview = apiData<Preview>(await http.post('/checkout/preview', body))
    if (!isCurrent() || owned !== previewGeneration || pendingCheckout || identity !== checkoutFingerprint(selectedVisitIds.value, [], memberId.value, benefits.value)) return
    if (benefits.value.pass_use && nextPreview.amount_due === undefined) throw new Error('服务器未返回抵次后的应收金额，请刷新')
    preview.value = nextPreview
    if (automaticCash.value && payments.slice(1).every(row => !row.amount)) payments[0].amount = Number(amountDue.value)
  } catch (error) { if (!isCurrent() || owned !== previewGeneration) return;
    preview.value = null
    if (!silent) ElMessage.error(apiErrorMessage(error))
  } finally {
    if (owned === previewGeneration) previewing.value = false
  }
}

async function initialize() {
  const isCurrent = guardBusinessOperation('initialize')
  if (!isCurrent()) return

  resetMember()
  previewing.value = true
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
  } finally {
    if (isCurrent()) previewing.value = false
  }
}

async function toggleVisit(visitId: string) {
  if (formLocked.value) return
  const isCurrent = guardBusinessOperation('toggleVisit')
  if (!isCurrent()) return

  const next = toggleCheckoutVisit(selectedVisitIds.value, visitId)
  if (next === selectedVisitIds.value) return ElMessage.warning('至少保留一个手牌进行结账')
  selectedVisitIds.value = next
  resetMember()
  await load(); if (!isCurrent()) return;
}

function fillPayment(index: number) {
  if (formLocked.value || !preview.value) return
  if (payments[index]?.method === 'balance' && !selectedMember.value) {
    return ElMessage.warning('请先查询手机号或读取实体卡识别会员')
  }
  try {
    if (payments[index]?.method === 'balance') {
      if (!verificationReady.value) return ElMessage.warning('请先核实持卡人姓氏')
      applyMemberBalance(amountDue.value, payments, selectedMember.value!.balance, automaticCash.value)
    } else {
      fillRemaining(amountDue.value, payments, index)
    }
    automaticCash.value = false
  } catch (error) { ElMessage.warning(error instanceof Error ? error.message : '请检查支付金额') }
}

function resetMember() {
  memberReset.value++
  selectedMember.value = null
  memberId.value = ''
  benefits.value = { pass_use: null, member_verification: null }
  payments.find(row => row.method === 'balance')!.amount = 0
}

function selectMember(value: { member: Member | null; benefits: CheckoutBenefits }) {
  if (pendingCheckout || loading.value || sessionEnded.value) return
  const changed = checkoutFingerprint([], [], memberId.value, benefits.value) !== checkoutFingerprint([], [], value.member?.id || '', value.benefits)
  if (!changed) return
  if (memberId.value !== (value.member?.id || '')) payments.find(row => row.method === 'balance')!.amount = 0
  selectedMember.value = value.member
  memberId.value = value.member?.id || ''
  benefits.value = JSON.parse(JSON.stringify(value.benefits))
  void load()
}

onBusinessSessionClear(() => {
  sessionEnded.value = true; previewGeneration++; previewing.value = false
  preview.value = null; resetMember()
})

async function complete() {
  const generation = businessGeneration.capture()
  if (loading.value || previewing.value || memberBusy.value || sessionEnded.value) return
  const isCurrent = guardBusinessOperation('complete')
  if (!isCurrent()) return

  if (!pendingCheckout && (!preview.value || !balanced.value || !verificationReady.value)) return ElMessage.warning('请核实会员及应收金额，支付合计必须等于应收金额')
  if (!pendingCheckout && payments.some((row) => row.method === 'balance' && Number(row.amount) > 0) && !selectedMember.value) {
    return ElMessage.warning('请重新查询手机号或读取实体卡识别储值会员')
  }
  const memberPayment = Number(payments.find(row => row.method === 'balance')?.amount || 0)
  if (!pendingCheckout && memberPayment > Number(selectedMember.value?.balance || 0)) {
    return ElMessage.warning('会员余额不足，请使用可用余额，剩余金额用其他方式补齐')
  }
  loading.value = true
  await busyLease
  if (!isCurrent()) { loading.value = false; return }
  if (!pendingCheckout) {
    const activePayments = paymentPayload(payments)
    const key = checkoutRequestKey(checkoutFingerprint(selectedVisitIds.value, activePayments.map(row => ({ ...row, amount: Number(row.amount) })), memberId.value, benefits.value))
    pendingCheckout = { visit_ids: [...selectedVisitIds.value], checkout_scope: 'selected', member_id: memberId.value || null,
      payments: activePayments, idempotency_key: key, ...JSON.parse(JSON.stringify(benefits.value)) as CheckoutBenefits }
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
    const printerName = auth.terminal?.printer_name || localStorage.getItem('xiquan_printer_name') || undefined
    const result = await printSettlementJob(settlement.id,'automatic',printerName,generation); if (!isCurrent()) return;
    if (result.state !== 'success') {
      ElMessage.warning(result.message)
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
  }
}

onMounted(() => {
  initialize()
  unsubscribeRealtime = subscribeRealtime(['visits', 'wristbands', 'members'], () => { if (!formLocked.value) void load(true) })
  refreshTimer = window.setInterval(() => {
    if (!formLocked.value && !connectivity.isOnline && document.visibilityState === 'visible') load(true)
  }, 30_000)
})

onBeforeRouteLeave(() => {
  if (formLocked.value && !sessionEnded.value && !settlementConfirmed) { ElMessage.warning('请先确认当前收款结果，再离开收款页面'); return false }
  resetMember()
  previewGeneration++
})

onBeforeUnmount(() => {
  previewGeneration++
  const lease = busyLease; busyLease = null; void lease?.then(release => release())
  unsubscribeRealtime?.()
  if (refreshTimer) window.clearInterval(refreshTimer)
})
</script>

<template>
  <div class="page checkout-page">
    <AppPageHeader :title="isIndividualCheckout ? '选择手牌结账' : '统一结账'" description="先确认本次结账手牌，再填写支付方式；收款成功与打印小票相互独立。" eyebrow="CHECKOUT" />
    <el-card shadow="never" class="checkout-card">
      <section class="checkout-step">
        <div class="step-title"><div><strong>1. 选择本次结账手牌</strong><span>未选中的联动手牌会继续使用，不受本次结账影响</span></div><b>原账单 ¥{{ preview?.total_amount || '0.00' }}</b></div>
        <fieldset :disabled="formLocked"><VisitSelector :visits="availableVisits" :selected-ids="selectedVisitIds" @toggle="!formLocked && toggleVisit($event)" /></fieldset>
        <el-alert v-if="isIndividualCheckout" type="warning" :closable="false" show-icon title="本次只结所选手牌；结账后，其余联动手牌仍可继续消费。" />
      </section>
      <el-divider />
      <PaymentPanel :payments="payments" :total="amountDue" :paid="paid" :balanced="balanced" :remaining="summary.remaining" :overpaid="summary.overpaid" :disabled="formLocked || !preview" @fill="fillPayment" @change="automaticCash = false" />
      <MemberPaymentSelector :visits="availableVisits.filter(visit => selectedVisitIds.includes(visit.visit_id))" :reset-token="memberReset" :disabled="loading || uncertainPayment || previewing || sessionEnded" @selection="selectMember" @busy="memberBusy = $event" @balance="fillPayment(3)" />
      <el-alert v-if="preview?.pass_redemption_count" type="success" :closable="false" :title="`本次抵票 ${preview.pass_redemption_count} 人，抵扣 ¥${preview.pass_redemption_amount}，剩余应收 ¥${amountDue}`" />
      <ul v-if="preview?.pass_redemptions?.length" class="redemptions"><li v-for="redemption in preview.pass_redemptions" :key="redemption.order_item_id">{{ availableVisits.find(visit => visit.visit_id === redemption.visit_id)?.wristband_number }} 号门票抵扣 ¥{{ redemption.amount }}</li></ul>
      <el-divider />
      <el-alert v-if="uncertainPayment" type="warning" :closable="false" show-icon title="上次收款结果待确认：请勿重新收钱。金额和手牌已锁定，点击下方按钮确认原结果。" />
      <section class="submit-step"><div><strong>3. 确认收款</strong><span>收款完成后即视为结账成功；打印失败请到“小票补打”处理。</span></div><el-button type="success" size="large" :loading="loading" :disabled="loading || previewing || memberBusy || sessionEnded || (!uncertainPayment && (!preview || !balanced || !verificationReady || !selectedVisitIds.length))" @click="complete">{{ uncertainPayment ? '确认上次收款结果' : `确认收款 ¥${amountDue}` }}</el-button></section>
    </el-card>
  </div>
</template>

<style scoped>
.checkout-page { max-width: 1040px; margin: 0 auto; }
.checkout-card { border-radius: var(--xq-radius-lg); }
.checkout-step { display: grid; gap: 14px; }
fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }
fieldset:disabled { opacity: .65; }
.step-title, .submit-step { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.step-title strong, .step-title span, .submit-step strong, .submit-step span { display: block; }
.step-title span, .submit-step span { margin-top: 4px; color: var(--xq-text-3); font-size: 11px; }
.step-title > b { color: var(--xq-danger); font-size: 23px; }
</style>
