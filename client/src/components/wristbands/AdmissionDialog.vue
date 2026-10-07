<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { admissionChoices, initialTicketSelection, ticketSelectionPayload, type AdmissionBand } from '../../domain/wristbands/tickets'
import type { CatalogItem } from '../../types'

const props = withDefaults(defineProps<{ modelValue: boolean; bands: AdmissionBand[]; tickets: CatalogItem[];
  title?: string; description?: string; initial?: Record<string, string> }>(), { title: '逐人选择门票', description: '' })
const emit = defineEmits<{ confirm: [ids: Record<string, string>]; cancel: [] }>()
const selected = ref<Record<string, string>>({})
const error = ref('')
const choices = computed(() => { try { return admissionChoices(props.tickets) } catch { return [] } })
watch(() => [props.modelValue, props.bands, props.tickets], (_value, previous) => {
  if (!props.modelValue) return
  error.value = ''
  try {
    const defaults = initialTicketSelection(props.bands, choices.value)
    const opening = !previous?.[0] || previous?.[1] !== props.bands
    const prior = opening ? props.initial : selected.value
    for (const band of props.bands) if (choices.value.some(row => row.id === prior?.[band.id]))
      defaults[band.id] = prior![band.id]!
    selected.value = defaults
  } catch (failure) { error.value = String((failure as Error).message) }
}, { immediate: true })
function confirm() {
  if (error.value || !props.bands.length) return
  try { emit('confirm', ticketSelectionPayload(props.bands, choices.value, selected.value)) }
  catch (failure) { error.value = String((failure as Error).message) }
}
</script>

<template>
  <el-dialog :model-value="modelValue" :title="title" width="min(560px, 94vw)" @close="emit('cancel')">
    <p v-if="description" class="muted">{{ description }}</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <form v-else @submit.prevent="confirm">
      <fieldset v-for="band in bands" :key="band.id" :data-band-id="band.id">
        <legend>{{ band.number }} 号手牌</legend>
        <label v-for="option in choices" :key="option.id">
          <input v-model="selected[band.id]" type="radio" :name="`ticket-${band.id}`" :value="option.id" />
          <span>{{ option.name }} <strong>¥{{ option.price }}</strong></span>
        </label>
      </fieldset>
    </form>
    <template #footer>
      <el-button @click="emit('cancel')">取消</el-button>
      <el-button data-testid="confirm-admission" type="primary" :disabled="!!error || !bands.length" @click="confirm">确认</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
fieldset { border: 1px solid var(--xq-border); border-radius: 8px; margin: 12px 0; padding: 12px; }
legend { font-weight: 700; padding: 0 5px; }
label { display: flex; align-items: center; gap: 10px; padding: 10px 4px; cursor: pointer; }
input { width: 18px; height: 18px; accent-color: var(--xq-primary); }
strong { margin-left: 8px; }
</style>
