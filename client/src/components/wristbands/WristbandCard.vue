<script setup lang="ts">
import type { Wristband } from '../../types'

const props = defineProps<{
  row: Wristband
  selected: boolean
  batchActive: boolean
  selectable: boolean
  elapsed: string
  canClear?: boolean
  canManage?: boolean
}>()
const emit = defineEmits<{
  primary: [row: Wristband]
  toggleSelect: [row: Wristband]
  switch: [row: Wristband]
  lost: [row: Wristband]
  recover: [row: Wristband]
  replace: [row: Wristband]
  forceClear: [row: Wristband]
}>()

const statusMeta = {
  available: { label: '空闲', color: '#0f9f8f' },
  in_use: { label: '使用中', color: '#d97706' },
  lost: { label: '已挂失', color: '#dc2626' },
  disabled: { label: '已停用', color: '#8795a8' },
}

function activate() {
  if (props.batchActive) {
    if (props.selectable) emit('toggleSelect', props.row)
    return
  }
  emit('primary', props.row)
}
</script>

<template>
  <article
    role="button"
    :tabindex="row.status === 'disabled' || (batchActive && !selectable) ? -1 : 0"
    :aria-label="`${row.number} 号手牌，${statusMeta[row.status].label}`"
    :aria-pressed="batchActive ? selected : undefined"
    :class="['wristband-card', `status-${row.status}`, { selected, 'batch-active': batchActive, disabled: batchActive && !selectable }]"
    :style="{ '--status-color': statusMeta[row.status].color }"
    @click="activate"
    @keydown.enter.self.prevent="activate"
    @keydown.space.self.prevent="activate"
  >
    <div class="card-top">
      <el-checkbox v-if="batchActive && selectable" :model-value="selected" @click.stop @change="emit('toggleSelect', row)" />
      <span v-else class="select-placeholder"></span>
      <span class="status"><i></i>{{ statusMeta[row.status].label }}</span>
    </div>
    <strong class="number">{{ row.number }}</strong>
    <span v-if="row.visit_id" class="amount">¥{{ row.amount }}</span>
    <span v-if="row.opened_at" class="timer"><el-icon><Timer /></el-icon>{{ elapsed }}</span>
    <div v-if="(row.linked_numbers?.length || 0) > 1" class="linked"><el-icon><Connection /></el-icon>{{ row.linked_numbers?.join(' ↔ ') }} · 整组 ¥{{ row.linked_total_amount }}</div>
    <p v-else class="hint">{{ row.status === 'available' ? (batchActive ? '可加入联动组' : '点击开单') : row.status === 'in_use' ? (batchActive ? '可联动或合并结账' : '点击查看消费') : row.note || '暂不可使用' }}</p>

    <div v-if="canManage && !batchActive && row.status === 'in_use'" class="card-actions" @click.stop>
      <el-button size="small" plain @click="emit('switch', row)"><el-icon><Switch /></el-icon>换牌</el-button>
      <el-button size="small" type="warning" plain @click="emit('lost', row)"><el-icon><Warning /></el-icon>挂失</el-button>
      <el-button v-if="canClear" data-testid="force-clear" size="small" type="danger" plain @click="emit('forceClear', row)">强制清空</el-button>
    </div>
    <div v-if="canManage && !batchActive && row.status === 'lost'" class="card-actions" @click.stop>
      <el-button size="small" type="success" plain @click="emit('recover', row)"><el-icon><RefreshRight /></el-icon>恢复</el-button>
      <el-button v-if="row.visit_id" size="small" type="warning" plain @click="emit('replace', row)"><el-icon><Tickets /></el-icon>补牌</el-button>
      <el-button v-if="canClear && row.visit_id" data-testid="force-clear" size="small" type="danger" plain @click="emit('forceClear', row)">强制清空</el-button>
    </div>
  </article>
</template>

<style scoped>
.wristband-card { display: flex; flex-direction: column; min-height: 208px; padding: 14px; cursor: pointer; border: 1px solid var(--xq-border); border-top: 4px solid var(--status-color); border-radius: var(--xq-radius-md); background: var(--xq-bg-card); box-shadow: var(--xq-shadow-card); transition: border-color .16s; }
.wristband-card:hover { border-color: var(--xq-primary); }
.wristband-card:focus-visible { outline: 3px solid var(--xq-primary); outline-offset: 3px; }
.wristband-card.selected { border-color: var(--xq-primary); box-shadow: inset 0 0 0 1px var(--xq-primary); }
.wristband-card.disabled { cursor: not-allowed; opacity: .56; transform: none; }
.card-top, .status, .timer, .linked { display: flex; align-items: center; }
.card-top { justify-content: space-between; }
.select-placeholder { width: 16px; }
.status { gap: 6px; color: var(--status-color); font-size: 12px; font-weight: 750; }
.status i { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.number { margin: 14px 0 2px; color: var(--xq-text-1); text-align: center; font-size: 34px; line-height: 1.1; }
.amount { color: var(--xq-danger); text-align: center; font-size: 18px; font-weight: 800; }
.timer { justify-content: center; gap: 5px; margin-top: 6px; color: var(--xq-text-2); font: 700 12px Consolas, monospace; }
.linked { min-height: 27px; margin-top: 9px; padding: 6px 8px; overflow: hidden; color: var(--xq-primary); background: var(--xq-primary-soft); border-radius: 7px; font-size: 11px; white-space: nowrap; text-overflow: ellipsis; }
.hint { min-height: 28px; margin: 9px 0 0; color: var(--xq-text-3); text-align: center; font-size: 11px; }
.card-actions { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; margin-top: auto; padding-top: 12px; border-top: 1px solid var(--xq-border); }
.card-actions :deep(.el-button), .card-actions :deep(.el-dropdown) { width: 100%; margin: 0; }
</style>
