<script setup lang="ts">
defineProps<{ title: string; subtitle?: string; back?: boolean }>()
defineEmits<{ back: [] }>()
</script>
<template><header class="mobile-topbar"><button v-if="back" class="icon-button" aria-label="返回" @click="$emit('back')">‹</button><div><strong>{{ title }}</strong><span v-if="subtitle">{{ subtitle }}</span></div><div class="topbar-actions"><slot /></div></header></template>
<style scoped>.mobile-topbar{position:sticky;z-index:30;top:0;display:flex;align-items:center;gap:11px;min-height:62px;padding:10px 16px;padding-top:max(10px,env(safe-area-inset-top));border-bottom:1px solid var(--m-border);background:rgba(255,255,255,.94);backdrop-filter:blur(12px)}.mobile-topbar>div:nth-child(2){min-width:0;flex:1}.mobile-topbar strong,.mobile-topbar span{display:block}.mobile-topbar strong{color:var(--m-text-1);font-size:17px}.mobile-topbar span{margin-top:2px;color:var(--m-text-3);font-size:10px}.icon-button{width:42px;height:42px;border:0;border-radius:12px;color:var(--m-text-1);background:var(--m-bg);font-size:30px}.topbar-actions{display:flex;gap:7px}</style>
