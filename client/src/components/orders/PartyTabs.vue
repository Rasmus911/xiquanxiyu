<script setup lang="ts">
import { Connection } from '@element-plus/icons-vue'
import type { Visit } from '../../types'

defineProps<{
  visits: Visit[]
  currentId?: string
  disabled?: boolean
  elapsed: (openedAt?: string) => string
}>()
defineEmits<{ select: [visitId: string] }>()
</script>

<template>
  <section v-if="visits.length > 1" class="party-tabs" aria-label="联动手牌">
    <div class="party-title"><el-icon><Connection /></el-icon><span>联动手牌</span><small>消费分别记在各自手牌，可随时单独结账</small></div>
    <button v-for="item in visits" :key="item.id" :disabled="disabled" :class="{ active: item.id === currentId }" @click="$emit('select', item.id)">
      <strong>{{ item.wristband_number }}</strong>
      <span>¥{{ item.total_amount }}</span>
      <small>{{ elapsed(item.opened_at) }}</small>
    </button>
  </section>
</template>

<style scoped>
.party-tabs { display: flex; align-items: stretch; gap: 9px; margin-bottom: 16px; padding: 10px; overflow-x: auto; border: 1px solid #cfe0ff; border-radius: var(--xq-radius-md); background: #f6f9ff; }
.party-title { display: grid; grid-template-columns: auto auto; align-content: center; gap: 2px 6px; min-width: 190px; padding: 0 10px; color: var(--xq-primary); }
.party-title small { grid-column: 1 / -1; color: var(--xq-text-3); font-size: 10px; }
button { min-width: 116px; padding: 9px 12px; color: var(--xq-text-2); cursor: pointer; border: 1px solid var(--xq-border); border-radius: 10px; background: white; text-align: left; }
button.active { color: var(--xq-primary); border-color: var(--xq-primary); box-shadow: 0 0 0 2px rgba(37,99,235,.10); }
button strong, button span, button small { display: block; }
button strong { font-size: 15px; } button span { margin-top: 3px; font-weight: 750; } button small { margin-top: 2px; color: var(--xq-text-3); font: 10px Consolas, monospace; }
</style>
