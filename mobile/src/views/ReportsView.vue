<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import MobileTopbar from '../components/navigation/MobileTopbar.vue'
import MobileState from '../components/common/MobileState.vue'
import MobileMetricGrid from '../components/reports/MobileMetricGrid.vue'
import MobileTrendChart from '../components/reports/MobileTrendChart.vue'
import { useBusinessStore } from '../stores/business'

const business = useBusinessStore()
const days = ref<1 | 7 | 30>(1)
const paymentNames: Record<string, string> = { cash: '现金', wechat: '微信', alipay: '支付宝', balance: '会员储值' }
const insights=computed(()=>business.report?.insights)
const hoursMax=computed(()=>Math.max(1,...(insights.value?.hours||[]).map(row=>row.visits)))
const growth=computed(()=>{const previous=Number(insights.value?.previous.operating_revenue||0);if(previous<=0)return '上期无正营收，不计算增幅';const n=(Number(business.report?.summary.operating_revenue||0)-previous)/previous*100;return `${n>=0?'+':''}${n.toFixed(1)}%`})

async function load(value = days.value) {
  days.value = value
  await business.loadReport(value).catch(() => undefined)
}

onMounted(() => load())
</script>

<template>
  <div>
    <MobileTopbar title="经营报表" subtitle="数据由云端统一核算" />
    <main class="mobile-page">
      <div class="segment">
        <button v-for="item in ([1, 7, 30] as const)" :key="item" :class="{ active: days === item }" @click="load(item)">
          {{ item === 1 ? '今日' : `${item}天` }}
        </button>
      </div>
      <MobileState v-if="business.loading && !business.report" kind="loading" title="正在生成报表" />
      <MobileState v-else-if="business.error && !business.report" kind="error" title="报表读取失败" :description="business.error" @retry="load()" />
      <template v-else-if="business.report">
        <MobileMetricGrid :summary="business.report.summary" />
        <section v-if="insights" class="mobile-card insight-card"><h3>经营观察</h3><div class="mini-metrics"><article><span>已结账手牌人次</span><strong>{{insights.visit_count}}</strong></article><article><span>每手牌平均营收</span><strong>{{insights.average_visit_revenue===null?'—':`¥${insights.average_visit_revenue}`}}</strong></article></div><p>消费营收对比前一等长期间：{{growth}}</p><p>会员关联人次占比 {{insights.member_visit_share===null?'—':`${Number(insights.member_visit_share).toFixed(1)}%`}}（{{insights.member_visit_count}} / {{insights.visit_count}}），不是复购率。</p><p>采购入库已录成本 ¥{{insights.purchase_cost.recorded_amount}} · {{insights.purchase_cost.unpriced_receipts}}笔未设置。采购不是耗用成本，不据此计算利润。</p><h3>已结账手牌入场时段</h3><p>北京时间；只统计本期已结账手牌，非全部到店客流。</p><svg viewBox="0 0 800 200" role="img" aria-label="已结账手牌入场时段"><g v-for="row in insights.hours" :key="row.hour"><rect :x="20+row.hour*32" :y="160-row.visits/hoursMax*120" width="22" :height="row.visits/hoursMax*120" fill="#2c735b"><title>{{row.hour}}时 {{row.visits}}人次</title></rect><text v-if="row.hour%3===0" :x="20+row.hour*32" y="190">{{row.hour}}时</text></g></svg></section>
        <section class="mobile-card">
          <h3>资金流入趋势</h3>
          <MobileTrendChart :rows="business.report.trend" />
        </section>
        <section class="mobile-card">
          <h3>收款方式</h3>
          <div v-for="(value, method) in business.report.summary.cashflow_totals" :key="method" class="payment-row">
            <span>{{ paymentNames[method] || method }}</span><strong>¥{{ Number(value).toFixed(2) }}</strong>
          </div>
        </section>
        <section class="mobile-card">
          <h3>热销项目</h3>
          <div v-if="!business.report.items.length" class="empty-copy">当前范围暂无消费项目</div>
          <div v-for="(row, index) in [...business.report.items].sort((a, b) => Number(b.amount) - Number(a.amount)).slice(0, 6)" :key="`${row.kind}-${row.name}`" class="rank">
            <b>{{ index + 1 }}</b><span>{{ row.name }}<small>{{ row.quantity }} 份</small></span><strong>¥{{ row.amount }}</strong>
          </div>
        </section>
      </template>
    </main>
  </div>
</template>
<style scoped>.insight-card{padding:16px;margin-top:14px}.insight-card p{font-size:12px;line-height:1.7;color:var(--m-text-2)}.insight-card svg{width:100%;height:auto}.insight-card text{font-size:23px;fill:var(--m-text-3)}</style>

<style scoped>.empty-copy{padding:24px 0;color:var(--m-text-3);text-align:center;font-size:12px}.payment-row{display:flex;align-items:center;justify-content:space-between;min-height:42px;border-bottom:1px solid var(--m-border)}.payment-row:last-child{border:0}.payment-row span{color:var(--m-text-2);font-size:12px}.payment-row strong{color:var(--m-text-1);font-size:13px}</style>
