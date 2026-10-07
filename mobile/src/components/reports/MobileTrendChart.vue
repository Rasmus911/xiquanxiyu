<script setup lang="ts">
import {computed} from 'vue'
import {trendMinWidth} from '../../mobile-management'
import type {MobileTrendPoint} from '../../types'
const props=defineProps<{rows:MobileTrendPoint[]}>()
const scale=computed(()=>{
  const values=props.rows.map(row=>Number(row.cash_inflow))
  const positive=Math.max(0,...values),negative=Math.max(0,...values.map(value=>-value))
  const span=Math.max(1,positive+negative)
  return {span,zero:negative/span*100}
})
function barStyle(value:string){
  const amount=Number(value),height=Math.abs(amount)/scale.value.span*100
  return {height:`${height}%`,bottom:`${amount<0?scale.value.zero-height:scale.value.zero}%`}
}
</script>
<template><div class="trend-scroll"><div class="trend" :style="{minWidth:trendMinWidth(rows.length)}"><div v-for="row in rows" :key="row.date" class="bar-column"><div class="bar-track"><b class="zero-line" :style="{bottom:`${scale.zero}%`}"></b><i :class="{negative:Number(row.cash_inflow)<0}" :style="barStyle(row.cash_inflow)"></i></div><strong>¥{{Number(row.cash_inflow).toFixed(0)}}</strong><span>{{row.date.slice(5)}}</span></div></div></div></template>
<style scoped>.trend-scroll{overflow-x:auto}.trend{display:flex;align-items:end;gap:8px;height:190px;padding:12px 4px}.bar-column{display:grid;grid-template-rows:120px auto auto;flex:1;min-width:30px;text-align:center}.bar-track{position:relative;height:120px;border-radius:8px;background:#edf1f6}.zero-line{position:absolute;left:0;right:0;border-top:1px solid #a8b5c6}.bar-track i{position:absolute;right:0;left:0;border-radius:6px;background:var(--m-primary)}.bar-track i.negative{background:#bd5a55}.bar-column strong{margin-top:5px;color:var(--m-text-2);font-size:12px}.bar-column span{color:var(--m-text-3);font-size:12px}</style>
