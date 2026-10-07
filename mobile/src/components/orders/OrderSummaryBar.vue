<script setup lang="ts">defineProps<{kinds:number;units:number;amount:number;disabled:boolean;sending:boolean;compact?:boolean}>();defineEmits<{submit:[]}>()</script>
<template><div class="summary-bar" :class="{compact}"><div><span>已选 {{kinds}} 种 · {{units}} 份</span><strong>¥{{amount.toFixed(2)}}</strong></div><button data-testid="submit-order" :disabled="disabled||sending" @click="$emit('submit')">{{sending?'正在提交':'确认加单'}}</button></div></template>
<style scoped>
.summary-bar{position:fixed;z-index:32;right:12px;bottom:calc(76px + env(safe-area-inset-bottom));left:12px;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 13px;color:var(--m-text-1);border:1px solid var(--m-border);border-radius:8px;background:white}
span,strong{display:block}span{color:var(--m-text-2);font-size:12px}strong{margin-top:2px;font-size:22px}
.summary-bar button{min-width:122px;min-height:48px;border:0;border-radius:7px;color:white;background:var(--m-primary);font-weight:700}.summary-bar button:disabled{opacity:.45}
.summary-bar.compact{position:static;z-index:auto;flex-wrap:wrap;justify-content:flex-end;padding:0;border:0;border-radius:0;background:transparent}.compact strong{font-size:17px}.compact button{min-width:100px;min-height:42px}
</style>
