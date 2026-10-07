<script setup lang="ts">
import type { MixedPayment } from '../../domain/checkout/mixed-payments'
defineProps<{ payments: MixedPayment[]; total: string; paid: string; balanced: boolean; remaining: string; overpaid: string; disabled?: boolean }>()
defineEmits<{ fill: [index: number]; change: [] }>()
const labels: Record<string, string> = { cash: '现金', wechat: '微信', alipay: '支付宝', balance: '会员余额' }
</script>

<template>
  <section class="payment-panel">
    <div class="panel-title"><div><strong>2. 组合收款</strong><span>填写实际收取的金额，不使用的方式留 0；微信和支付宝请确认已到账</span></div></div>
    <div v-for="(payment, index) in payments" :key="index" class="payment-row">
      <strong class="payment-label">{{ labels[payment.method] }}</strong>
      <el-input-number v-model="payment.amount" :min="0" :precision="2" :controls="false" :disabled="disabled" :aria-label="labels[payment.method] + '金额'" @change="$emit('change')" />
      <el-input v-model="payment.reference" placeholder="流水号（选填）" :disabled="disabled" />
      <el-button data-testid="fill-payment" plain :disabled="disabled" @click="$emit('fill', index)">{{ payment.method === 'balance' ? '使用可用余额' : '补齐剩余' }}</el-button>
    </div>
    <div :class="['payment-summary', { balanced }]">
      <span>应收 <b>¥{{ total }}</b></span><span>收款合计 <b>¥{{ paid }}</b></span><strong>{{ balanced ? '金额已平，可确认收款' : Number(overpaid) > 0 ? `多填 ¥${overpaid}，请调整` : `还需收款 ¥${remaining}` }}</strong>
    </div>
  </section>
</template>

<style scoped>
.payment-panel { display: grid; gap: 12px; }
.panel-title { display: flex; align-items: center; justify-content: space-between; }
.panel-title strong, .panel-title span { display: block; } .panel-title span { margin-top: 3px; color: var(--xq-text-3); font-size: 11px; }
.payment-row { display: grid; grid-template-columns: 90px 140px minmax(120px, 1fr) 130px; gap: 10px; align-items: center; }
.payment-label { font-size: 14px; color: var(--xq-text-1); }
.payment-summary { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 11px 13px; color: var(--xq-warning); border-radius: 10px; background: #fff7e8; }
.payment-summary.balanced { color: #08796c; background: var(--xq-accent-soft); }
@media (max-width: 1100px) { .payment-row { grid-template-columns: 1fr 1fr; } }
</style>
