<script setup lang="ts">
import { useBusinessGuard } from '../business/state'
const guardBusinessOperation = useBusinessGuard()

import dayjs from 'dayjs'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiData, apiErrorMessage, http } from '../api/http'
import AppPageHeader from '../components/app/AppPageHeader.vue'
import { subscribeRealtime } from '../realtime/events'
import { useConnectivityStore } from '../stores/connectivity'

interface TrendPoint { date: string; revenue: string; recharge: string; cash_inflow: string; settlement_count: number }

const range = ref<[string, string]>([
  dayjs().subtract(6, 'day').startOf('day').format('YYYY-MM-DD HH:mm:ss'),
  dayjs().add(1, 'day').startOf('day').format('YYYY-MM-DD HH:mm:ss'),
])
const summary = ref<Record<string, any>>({})
const items = ref<Array<Record<string, string>>>([])
const trend = ref<TrendPoint[]>([])
const insights = ref<Record<string, any>>({})
const failure = ref('')
const rankBy = ref<'amount' | 'quantity'>('amount')
const selectedDays = ref(7)
let loadGeneration = 0
const loading = ref(false)
const connectivity = useConnectivityStore()
let refreshTimer: number | undefined
let realtimeRefreshTimer: number | undefined
let unsubscribeRealtime: (() => void) | undefined

const payNames: Record<string, string> = { cash: '现金', wechat: '微信', alipay: '支付宝', balance: '会员储值' }
const payColors: Record<string, string> = { cash: '#35c6a6', wechat: '#6979f8', alipay: '#39a9ff', balance: '#a66bff' }
const kindNames: Record<string, string> = { ticket: '门票', service: '服务', product: '商品', package: '套票', compensation: '赔偿' }

const paymentRows = computed(() => Object.entries(summary.value.cashflow_totals || {})
  .map(([method, amount]) => ({ method, amount: Number(amount) }))
  .filter((row) => row.amount !== 0))
const paymentTotal = computed(() => paymentRows.value.reduce((sum, row) => sum + row.amount, 0))
const donutStyle = computed(() => {
  if (!paymentTotal.value || paymentRows.value.some(row => row.amount < 0)) return { background: '#e8edf5' }
  let start = 0
  const segments = paymentRows.value.map((row) => {
    const end = start + row.amount / paymentTotal.value * 100
    const segment = `${payColors[row.method] || '#7d8ba5'} ${start}% ${end}%`
    start = end
    return segment
  })
  return { background: `conic-gradient(${segments.join(',')})` }
})

const chartWidth = 1000
const chartHeight = 270
const chartPadding = 42
const maxTrend = computed(() => Math.max(1, ...trend.value.flatMap((row) => [Number(row.revenue), Number(row.recharge), Number(row.cash_inflow)])))
const minTrend = computed(() => Math.min(0, ...trend.value.flatMap(row => [Number(row.revenue), Number(row.recharge), Number(row.cash_inflow)])))
const revenueComparison = computed(() => {
  const previous = Number(insights.value.previous?.operating_revenue || 0)
  const current = Number(summary.value.operating_revenue || 0)
  if (previous <= 0) return previous === 0 ? '上期无正营收，不计算增幅' : '上期为负，不计算增幅'
  const value = (current - previous) / previous * 100
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
})
const hourMaximum = computed(() => Math.max(1, ...(insights.value.hours || []).map((row: any) => row.visits)))
const busiest = computed(() => (insights.value.hours || []).filter((row: any) => row.visits > 0)
  .sort((a: any, b: any) => b.visits - a.visits).slice(0, 3))
const composition = computed(() => Object.entries(items.value.reduce((out: Record<string, number>, item) => {
  out[item.kind] = (out[item.kind] || 0) + Number(item.amount); return out
}, {})).sort((a,b) => b[1]-a[1]))
function selectPeriod(days: number) {
  selectedDays.value = days
  range.value = [dayjs().subtract(days-1,'day').startOf('day').format('YYYY-MM-DD HH:mm:ss'),
    dayjs().add(1,'day').startOf('day').format('YYYY-MM-DD HH:mm:ss')]
  void load()
}

function chartPoint(value: number, index: number) {
  const width = chartWidth - chartPadding * 2
  const height = chartHeight - chartPadding * 2
  const x = chartPadding + (trend.value.length <= 1 ? width / 2 : index / (trend.value.length - 1) * width)
  const y = chartPadding + height - (value-minTrend.value) / (maxTrend.value-minTrend.value) * height
  return { x, y }
}

function linePoints(field: 'revenue' | 'recharge' | 'cash_inflow') {
  return trend.value.map((row, index) => {
    const point = chartPoint(Number(row[field]), index)
    return `${point.x},${point.y}`
  }).join(' ')
}

const revenueArea = computed(() => {
  if (!trend.value.length) return ''
  const points = linePoints('revenue')
  const first = chartPoint(Number(trend.value[0].revenue), 0)
  const last = chartPoint(Number(trend.value.at(-1)?.revenue || 0), trend.value.length - 1)
  return `M ${first.x} ${chartPoint(0,0).y} L ${points.replaceAll(',', ' ')} L ${last.x} ${chartPoint(0,0).y} Z`
})

const topItems = computed(() => [...items.value]
  .sort((a, b) => Number(b[rankBy.value]) - Number(a[rankBy.value]))
  .slice(0, 8))
const maxItemAmount = computed(() => Math.max(1, ...topItems.value.map((row) => Number(row[rankBy.value]))))

function money(value: unknown) {
  return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

async function load(silent = false) {
  const generation = ++loadGeneration
  const guard = guardBusinessOperation('load')
  const isCurrent = () => generation === loadGeneration && guard()
  if (!isCurrent()) return

  if (!silent) loading.value = true
  try {
    const params = { start: dayjs(range.value[0]).toISOString(), end: dayjs(range.value[1]).toISOString() }
    const [summaryResponse, itemsResponse, trendResponse, insightsResponse] = await Promise.all([
      http.get('/reports/summary', { params }),
      http.get('/reports/items', { params }),
      http.get('/reports/trend', { params }),
      http.get('/reports/insights', { params }),
    ]); if (!isCurrent()) return;
    summary.value = apiData<Record<string, any>>(summaryResponse)
    items.value = apiData<Array<Record<string, string>>>(itemsResponse)
    trend.value = apiData<TrendPoint[]>(trendResponse)
    insights.value = apiData<Record<string, any>>(insightsResponse)
    failure.value = ''
  } catch (error) { if (!isCurrent()) return; 
    failure.value = apiErrorMessage(error)
    if (!silent) ElMessage.error(failure.value)
  } finally { if (!isCurrent()) return; 
    loading.value = false
  }
}

onMounted(() => {
  load()
  unsubscribeRealtime = subscribeRealtime(['reports', 'checkout', 'members', 'inventory'], () => {
    if (realtimeRefreshTimer) window.clearTimeout(realtimeRefreshTimer)
    realtimeRefreshTimer = window.setTimeout(() => load(true), 350)
  })
  refreshTimer = window.setInterval(() => {
    if (!connectivity.isOnline && document.visibilityState === 'visible') load(true)
  }, 60_000)
})
onBeforeUnmount(() => {
  ++loadGeneration
  unsubscribeRealtime?.()
  if (realtimeRefreshTimer) window.clearTimeout(realtimeRefreshTimer)
  if (refreshTimer) window.clearInterval(refreshTimer)
})
</script>

<template>
  <div class="page report-page" v-loading="loading">
    <AppPageHeader title="经营报表" description="消费营收与会员储值、次卡收款分开核算，实际资金流入只计算一次。" eyebrow="BUSINESS REPORT"><template #actions><div class="toolbar">
        <el-button v-for="days in [1,7,30]" :key="days" :data-testid="`report-period-${days}`" :type="selectedDays === days ? 'primary' : 'default'" @click="selectPeriod(days)">{{ days===1?'今日':`近${days}天` }}</el-button>
        <el-date-picker v-model="range" :clearable="false" type="datetimerange" value-format="YYYY-MM-DD HH:mm:ss" start-placeholder="开始" end-placeholder="结束" @change="selectedDays=0; load()" />
        <el-button type="primary" @click="load()">刷新报表</el-button>
      </div></template></AppPageHeader>

    <el-alert v-if="failure" :title="failure+'；以下可能为上次成功读取的数据，请刷新。'" type="error" :closable="false" />
    <section v-if="insights.current" class="metric-grid">
      <article class="metric-card accent-cyan"><span>消费营收</span><strong>¥{{ money(summary.operating_revenue) }}</strong><small data-testid="revenue-comparison">对比前一等长期间 {{ revenueComparison }}</small></article>
      <article class="metric-card accent-blue"><span>实际新增资金流入</span><strong>¥{{ money(summary.actual_cash_inflow) }}</strong><small>普通收款 + 充值售卡 − 外部退款</small></article>
      <article class="metric-card accent-purple" data-testid="visit-count"><span>已结账手牌人次</span><strong>{{ insights.visit_count }}</strong><small>{{ summary.settlement_count }} 笔账单；合并结账按人次算</small></article>
      <article class="metric-card accent-gold" data-testid="visit-average"><span>每手牌平均营收</span><strong>{{ insights.average_visit_revenue===null?'—':`¥${money(insights.average_visit_revenue)}` }}</strong><small>消费净营收 ÷ 已结账手牌人次</small></article>
    </section>
    <section v-if="insights.current" class="detail-strip">
      <article><span>充值 / 次卡售卡</span><strong>¥{{ money(summary.member_recharge) }}</strong><small>储值 ¥{{ money(summary.stored_value_recharge) }} · 次卡 ¥{{ money(summary.pass_card_sales) }}</small></article>
      <article><span>储值余额核销</span><strong>¥{{ money(summary.stored_value_consumed) }}</strong><small>不重复计入新增资金</small></article>
      <article><span>会员关联人次占比</span><strong>{{ insights.member_visit_share===null?'—':`${Number(insights.member_visit_share).toFixed(1)}%` }}</strong><small>{{ insights.member_visit_count }} / {{ insights.visit_count }} 人次；不是复购率</small></article>
      <article data-testid="purchase-cost"><span>已录采购入库成本</span><strong>¥{{ money(insights.purchase_cost?.recorded_amount) }}</strong><small>{{ insights.purchase_cost?.unpriced_receipts }}笔未设置 · 不是耗用成本或利润</small></article>
    </section>

    <el-alert class="accounting-note" type="info" :closable="false" show-icon title="合并看“实际新增资金流入”：普通收款加会员充值；储值卡消费不再增加一次资金流入，因此同一笔钱不会流水两次。" />

    <section class="visual-grid">
      <el-card shadow="never" class="trend-card">
        <template #header><div class="card-title"><div><strong>每日资金趋势</strong><span>分离查看，再用实际资金流入合并</span></div><div class="legend"><i class="revenue"></i>消费营收<i class="recharge"></i>充值<i class="cashflow"></i>实际流入</div></div></template>
        <div v-if="trend.length" class="chart-wrap">
          <svg :viewBox="`0 0 ${chartWidth} ${chartHeight}`" role="img" aria-label="每日营业收入和充值趋势图">
            <defs><linearGradient id="revenueFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#31d3b3" stop-opacity=".32" /><stop offset="1" stop-color="#31d3b3" stop-opacity="0" /></linearGradient></defs>
            <line v-for="line in 5" :key="line" :x1="chartPadding" :x2="chartWidth - chartPadding" :y1="chartPadding + (line - 1) * (chartHeight - chartPadding * 2) / 4" :y2="chartPadding + (line - 1) * (chartHeight - chartPadding * 2) / 4" class="grid-line" />
            <text v-for="line in 5" :key="`axis-${line}`" x="0" :y="chartPadding + (line-1)*(chartHeight-chartPadding*2)/4">{{ Math.round(maxTrend-(line-1)*(maxTrend-minTrend)/4) }}</text>
            <line :x1="chartPadding" :x2="chartWidth-chartPadding" :y1="chartPoint(0,0).y" :y2="chartPoint(0,0).y" stroke="#667085" />
            <path :d="revenueArea" fill="url(#revenueFill)" />
            <polyline :points="linePoints('revenue')" class="revenue-line" />
            <polyline :points="linePoints('recharge')" class="recharge-line" />
            <polyline :points="linePoints('cash_inflow')" class="cashflow-line" />
            <g v-for="(row, index) in trend" :key="row.date">
              <circle :cx="chartPoint(Number(row.revenue), index).x" :cy="chartPoint(Number(row.revenue), index).y" r="5" class="revenue-dot"><title>{{ row.date }} 营业收入 ¥{{ row.revenue }}</title></circle>
              <circle :cx="chartPoint(Number(row.recharge), index).x" :cy="chartPoint(Number(row.recharge), index).y" r="4" class="recharge-dot"><title>{{ row.date }} 会员充值 ¥{{ row.recharge }}</title></circle>
              <circle :cx="chartPoint(Number(row.cash_inflow), index).x" :cy="chartPoint(Number(row.cash_inflow), index).y" r="4" class="cashflow-dot"><title>{{ row.date }} 实际新增资金流入 ¥{{ row.cash_inflow }}</title></circle>
              <text v-if="trend.length <= 14 || index % 7 === 0 || index === trend.length - 1" :x="chartPoint(0, index).x" :y="chartHeight - 10" text-anchor="middle">{{ row.date.slice(5) }}</text>
            </g>
          </svg>
        </div>
        <el-empty v-else description="暂无趋势数据" />
      </el-card>

      <el-card shadow="never" class="payment-card">
        <template #header><div class="card-title"><div><strong>实际资金流入结构</strong><span>已排除储值余额重复支付</span></div></div></template>
        <div class="donut-wrap">
          <div class="donut" :style="donutStyle"><div><small>支付合计</small><strong>¥{{ money(paymentTotal) }}</strong></div></div>
          <div class="payment-legend">
            <div v-for="row in paymentRows" :key="row.method"><i :style="{ background: payColors[row.method] || '#7d8ba5' }"></i><span>{{ payNames[row.method] || row.method }}</span><strong>¥{{ money(row.amount) }}</strong><small>{{ row.amount<0?'净退款':paymentTotal>0&&!paymentRows.some(r=>r.amount<0)?`${(row.amount/paymentTotal*100).toFixed(1)}%`:'—' }}</small></div>
            <div v-if="!paymentRows.length" class="muted">暂无支付数据</div>
          </div>
        </div>
      </el-card>
    </section>

    <section v-if="insights.current" class="bottom-grid">
      <el-card shadow="never"><template #header><div class="card-title"><div><strong>入场时段观察</strong><span>期间已结账手牌的入场时间 · 北京时间 · 非全部到店客流</span></div></div></template>
        <svg viewBox="0 0 800 190" role="img" aria-label="已结账手牌入场时段" class="hour-chart"><g v-for="row in insights.hours" :key="row.hour"><rect :x="20+row.hour*32" :y="150-row.visits/hourMaximum*115" width="23" :height="row.visits/hourMaximum*115" fill="#2c735b"><title>{{ row.hour }}时：{{ row.visits }}人次</title></rect><text :x="31+row.hour*32" y="170" text-anchor="middle">{{ row.hour }}</text></g><text x="20" y="18">最高 {{ hourMaximum }} 人次</text></svg>
        <p class="muted">{{ busiest.length ? `入场较多时段：${busiest.map((r:any)=>`${r.hour}时（${r.visits}人次）`).join('、')}` : '当前期间暂无已结账手牌' }}。可据此安排接待人手；活动效果需结合后续同口径数据观察。</p>
      </el-card>
      <el-card shadow="never"><template #header><div class="card-title"><div><strong>消费项目构成</strong><span>未全额退款账单的项目金额；不等于扣退款后的净营收</span></div></div></template><div v-for="[kind,amount] in composition" :key="kind" class="composition"><span>{{ kindNames[kind] || kind }}</span><strong>¥{{ money(amount) }}</strong></div><el-empty v-if="!composition.length" description="暂无项目数据" /><p class="muted">查看套票与单项需求，用同等期间数据比较活动前后变化；不直接推断活动带来的收益。</p></el-card>
    </section>
    <section class="bottom-grid">
      <el-card shadow="never">
        <template #header><div class="card-title"><div><strong>热销项目排行</strong><span>已结账项目 Top 8 · 未全额退款账单</span></div><el-radio-group v-model="rankBy"><el-radio-button value="amount">按金额</el-radio-button><el-radio-button value="quantity">按份数</el-radio-button></el-radio-group></div></template>
        <div class="ranking">
          <div v-for="(item, index) in topItems" :key="`${item.kind}-${item.name}`" class="rank-row">
            <b>{{ String(index + 1).padStart(2, '0') }}</b>
            <div><div class="rank-label"><span>{{ item.name }}</span><small>{{ kindNames[item.kind] || item.kind }} · {{ item.quantity }} 份</small><strong>¥{{ money(item.amount) }}</strong></div><div class="bar"><i :style="{ width: `${Number(item[rankBy]) / maxItemAmount * 100}%` }"></i></div></div>
          </div>
          <el-empty v-if="!topItems.length" description="暂无项目数据" />
        </div>
      </el-card>
      <el-card shadow="never">
        <template #header><div class="card-title"><div><strong>项目明细</strong><span>按项目汇总</span></div></div></template>
        <el-table :data="items" max-height="420">
          <el-table-column label="类型" width="90"><template #default="scope">{{ kindNames[scope.row.kind] || scope.row.kind }}</template></el-table-column>
          <el-table-column prop="name" label="项目" />
          <el-table-column prop="quantity" label="数量" width="85" />
          <el-table-column prop="amount" label="金额" width="120"><template #default="scope"><strong>¥{{ money(scope.row.amount) }}</strong></template></el-table-column>
        </el-table>
      </el-card>
    </section>
  </div>
</template>

<style scoped>
.report-page { --ink: var(--xq-text-1); }
.detail-strip { display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:16px;padding:18px;background:#f6f8f7;border:1px solid var(--xq-border);border-radius:8px }
.detail-strip article { display:grid;gap:8px }.detail-strip span {font-size:13px;color:var(--xq-text-2)}.detail-strip strong{font-size:21px}.detail-strip small{color:var(--xq-text-3);line-height:1.6}
.hour-chart{height:190px}.composition{display:flex;justify-content:space-between;border-bottom:1px solid var(--xq-border);padding:12px 0}.muted{font-size:12px;line-height:1.7;color:var(--xq-text-3)}
@media(max-width:1200px){.detail-strip{grid-template-columns:repeat(2,1fr)}}
.metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; }
.metric-card { min-height: 126px; padding: 18px; color: var(--xq-text-1); border: 1px solid var(--xq-border); border-radius: 7px; background: white; }

.metric-card span, .metric-card strong, .metric-card small { position: relative; z-index: 1; display: block; }
.metric-card span { color: var(--xq-text-2); font-size: 14px; }
.metric-card strong { margin: 13px 0 8px; font-size: 28px; letter-spacing: -.5px; }
.metric-card small { color: var(--xq-text-3); }
.accent-cyan { --accent: #31d3b3; border-top: 3px solid #2c735b; }
.accent-purple { --accent: #9b7bff; border-top: 3px solid #827257; }
.accent-blue { --accent: #4facff; border-top: 3px solid #567486; }
.accent-gold { --accent: #f3bb55; border-top: 3px solid #a58b4b; }
.visual-grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(320px, .8fr); gap: 18px; margin-top: 18px; }
.accounting-note { margin-top: 16px; border-radius: 12px; }
.bottom-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 18px; }
.trend-card, .payment-card, .bottom-grid :deep(.el-card) { border-radius: 8px; }
.card-title { display: flex; align-items: center; justify-content: space-between; }
.card-title strong, .card-title span { display: block; }
.card-title strong { font-size: 17px; color: var(--ink); }
.card-title span { margin-top: 4px; font-size: 12px; color: #8a96a9; }
.legend { display: flex; align-items: center; gap: 7px; color: #78869a; font-size: 12px; }
.legend i { width: 18px; height: 3px; border-radius: 2px; }
.legend .revenue { background: #31caaa; }
.legend .recharge { background: #8a70f7; margin-left: 10px; }
.legend .cashflow { background: #4facff; margin-left: 10px; }
.chart-wrap { width: 100%; overflow: hidden; }
svg { display: block; width: 100%; height: 285px; }
svg text { fill: #8b98aa; font-size: 12px; }
.grid-line { stroke: #e8edf4; stroke-width: 1; stroke-dasharray: 5 6; }
.revenue-line, .recharge-line, .cashflow-line { fill: none; stroke-width: 4; stroke-linecap: round; stroke-linejoin: round; }
.revenue-line { stroke: #31caaa; }
.recharge-line { stroke: #8a70f7; }
.cashflow-line { stroke: #4facff; stroke-dasharray: 8 7; }
.revenue-dot { fill: white; stroke: #31caaa; stroke-width: 4; }
.recharge-dot { fill: white; stroke: #8a70f7; stroke-width: 3; }
.cashflow-dot { fill: white; stroke: #4facff; stroke-width: 3; }
.donut-wrap { display: flex; flex-direction: column; align-items: center; gap: 24px; }
.donut { width: 190px; height: 190px; padding: 24px; border-radius: 50%; }
.donut > div { width: 100%; height: 100%; display: grid; place-content: center; text-align: center; border-radius: 50%; background: white; box-shadow: inset 0 0 0 1px #edf1f6; }
.donut small, .donut strong { display: block; }
.donut small { color: #8a96a9; }
.donut strong { margin-top: 4px; color: var(--ink); font-size: 20px; }
.payment-legend { width: 100%; }
.payment-legend > div { display: grid; grid-template-columns: 10px 1fr auto 48px; align-items: center; gap: 9px; padding: 8px 2px; }
.payment-legend i { width: 9px; height: 9px; border-radius: 50%; }
.payment-legend span { color: #59677b; }
.payment-legend small { text-align: right; color: #95a0b0; }
.ranking { display: grid; gap: 15px; }
.rank-row { display: grid; grid-template-columns: 34px 1fr; align-items: center; gap: 10px; }
.rank-row > b { color: #9aa6b7; font-size: 12px; }
.rank-label { display: grid; grid-template-columns: minmax(100px, 1fr) auto auto; align-items: baseline; gap: 10px; }
.rank-label span { font-weight: 700; color: #273850; }
.rank-label small { color: #94a0b2; }
.rank-label strong { color: #17283f; }
.bar { height: 7px; margin-top: 7px; overflow: hidden; border-radius: 5px; background: #edf1f6; }
.bar i { display: block; height: 100%; border-radius: inherit; background: var(--xq-primary); }
@media (max-width: 1200px) { .metric-grid { grid-template-columns: repeat(2, 1fr); } .visual-grid, .bottom-grid { grid-template-columns: 1fr; } }
</style>
