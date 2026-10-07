<script setup lang="ts">
import { useConnectivityStore } from '../../stores/connectivity'
const connectivity = useConnectivityStore()
</script>
<template><transition name="banner"><div v-if="!connectivity.canWrite" class="network-banner danger">网络不可用，暂时不能提交；已选内容会保留。</div><div v-else-if="!connectivity.socketConnected" class="network-banner">实时连接正在恢复，页面会定时同步。</div></transition></template>
<style scoped>.network-banner{position:fixed;z-index:80;top:0;right:0;left:0;padding:9px 14px;color:#75530f;background:#fff1cf;text-align:center;font-size:12px}.network-banner.danger{color:#8e3228;background:#ffe9e6}.banner-enter-active,.banner-leave-active{transition:.18s}.banner-enter-from,.banner-leave-to{opacity:0;transform:translateY(-100%)}</style>
