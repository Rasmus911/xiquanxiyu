<script setup lang="ts">
defineProps<{
  selectedNumbers: string[]
  activeVisitCount: number
  maleCount: number
  femaleCount: number
}>()
defineEmits<{ link: []; checkout: []; cancel: [] }>()
</script>

<template>
  <transition name="batch-bar">
    <aside class="batch-action-bar">
      <div class="selection-copy">
        <strong>已选 {{ selectedNumbers.length }} 个手牌</strong>
        <span v-if="selectedNumbers.length">{{ selectedNumbers.join('、') }} · 男浴 {{ maleCount }} · 女浴 {{ femaleCount }}</span>
        <span v-else>可跨男浴和女浴选择，选完后再决定联动或结账</span>
      </div>
      <div class="actions">
        <el-button @click="$emit('cancel')">取消选择</el-button>
        <el-button type="primary" :disabled="selectedNumbers.length < 2" @click="$emit('link')"><el-icon><Connection /></el-icon>联动手牌</el-button>
        <el-button type="success" :disabled="activeVisitCount < 1" @click="$emit('checkout')"><el-icon><Money /></el-icon>合并结账（{{ activeVisitCount }}）</el-button>
      </div>
    </aside>
  </transition>
</template>

<style scoped>
.batch-action-bar { position: fixed; z-index: 45; right: 28px; bottom: 22px; left: 234px; display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 15px 18px; color: white; border: 1px solid rgba(255,255,255,.14); border-radius: 7px; background: #2d3d34; box-shadow: var(--xq-shadow-float); backdrop-filter: blur(14px); }
.selection-copy { min-width: 0; }
.selection-copy strong, .selection-copy span { display: block; }
.selection-copy strong { font-size: 14px; }
.selection-copy span { margin-top: 4px; overflow: hidden; color: #bfc9d8; font-size: 11px; white-space: nowrap; text-overflow: ellipsis; }
.actions { display: flex; gap: 9px; flex-shrink: 0; }
.batch-bar-enter-active, .batch-bar-leave-active { transition: .2s ease; }
.batch-bar-enter-from, .batch-bar-leave-to { opacity: 0; transform: translateY(20px); }
@media (max-width: 1050px) { .batch-action-bar { left: 230px; flex-direction: column; align-items: stretch; } .actions { justify-content: flex-end; } }
</style>
