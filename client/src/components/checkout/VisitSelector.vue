<script setup lang="ts">
defineProps<{
  visits: Array<{ visit_id: string; wristband_number: string; amount: string }>
  selectedIds: string[]
}>()
defineEmits<{ toggle: [visitId: string] }>()
</script>

<template>
  <div class="visit-selector">
    <button v-for="visit in visits" :key="visit.visit_id" :class="{ selected: selectedIds.includes(visit.visit_id) }" @click="$emit('toggle', visit.visit_id)">
      <el-checkbox :model-value="selectedIds.includes(visit.visit_id)" @click.stop @change="$emit('toggle', visit.visit_id)" />
      <span><strong>{{ visit.wristband_number }} 号</strong><small>本手牌消费</small></span>
      <b>¥{{ visit.amount }}</b>
    </button>
  </div>
</template>

<style scoped>
.visit-selector { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
button { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 9px; padding: 12px; color: var(--xq-text-2); cursor: pointer; border: 1px solid var(--xq-border); border-radius: 11px; background: white; text-align: left; }
button.selected { color: var(--xq-primary); border-color: var(--xq-primary); background: var(--xq-primary-soft); }
span strong, span small { display: block; } span small { margin-top: 2px; color: var(--xq-text-3); font-size: 10px; } b { color: var(--xq-danger); }
</style>
