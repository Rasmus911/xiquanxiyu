<script setup lang="ts">defineProps<{ online: boolean }>()</script>
<template><transition name="offline"><div v-if="!online" class="offline-banner"><el-icon><WarningFilled /></el-icon>实时连接暂时中断，页面会继续尝试重连；请勿重复提交收款或加单。</div></transition></template>
<style scoped>
.offline-banner { position: sticky; z-index: 20; top: 0; display: flex; align-items: center; justify-content: center; gap: 8px; min-height: 38px; color: #8a4d13; background: #fff4dc; border-bottom: 1px solid #f3d7a1; font-size: 12px; }
.offline-enter-active, .offline-leave-active { transition: .18s ease; }.offline-enter-from, .offline-leave-to { opacity: 0; transform: translateY(-8px); }
</style>
