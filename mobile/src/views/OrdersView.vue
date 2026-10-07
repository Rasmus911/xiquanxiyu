<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MobileState from '../components/common/MobileState.vue'
import MobileTopbar from '../components/navigation/MobileTopbar.vue'
import WristbandList from '../components/orders/WristbandList.vue'
import { useBusinessStore } from '../stores/business'
import { useConnectivityStore } from '../stores/connectivity'
import { useSessionStore } from '../stores/session'
const route=useRoute();const router=useRouter();const business=useBusinessStore();const connectivity=useConnectivityStore();const session=useSessionStore();const search=ref('');const area=ref<'all'|'male'|'female'>('all');const now=ref(Date.now());let timer=0
const canFilter=computed(()=>session.employee?.capabilities?.order_all === true);const rows=computed(()=>business.wristbands.filter(row=>(area.value==='all'||row.bath_area===area.value)&&(!search.value.trim()||row.number.includes(search.value.trim()))))
onMounted(()=>{timer=window.setInterval(()=>now.value=Date.now(),30000)});onBeforeUnmount(()=>window.clearInterval(timer));function select(visitId:string){business.selectVisit(visitId);void router.push(`/orders/${visitId}`)}
</script>
<template><div><MobileTopbar title="已激活手牌" :subtitle="`${session.employee?.display_name||session.employee?.username||''} · 同步 ${connectivity.syncLabel}`"><button class="small-button" @click="business.refreshBootstrap()">刷新</button></MobileTopbar><main class="mobile-page"><div v-if="route.query.notice" class="notice">{{route.query.notice}}</div><input v-model="search" class="mobile-input" placeholder="搜索手牌号"/><div v-if="canFilter" class="segment"><button v-for="item in ([['all','全部'],['male','男浴'],['female','女浴']] as const)" :key="item[0]" :class="{active:area===item[0]}" @click="area=item[0]">{{item[1]}}</button></div><MobileState v-if="business.loading&&!business.wristbands.length" kind="loading" title="正在同步手牌"/><MobileState v-else-if="business.error&&!business.wristbands.length" kind="error" title="无法读取手牌" :description="business.error" @retry="business.refreshBootstrap()"/><MobileState v-else-if="!rows.length" kind="empty" title="暂时没有已激活手牌" description="前台开牌后会自动出现在这里"/><WristbandList v-else :rows="rows" :now="now" @select="select"/></main></div></template>
