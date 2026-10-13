<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { InputInstance } from 'element-plus'
import { normalizeCardInput } from '../../domain/members/card-input'

const props = defineProps<{ modelValue: boolean; busy?: boolean; error?: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; read: [cardUid: string] }>()
const input = ref<InputInstance>(), buffer = ref(''), validation = ref(''), submitted = ref(false)
let focusGeneration = 0
watch(() => props.modelValue, async (open) => {
  const generation = ++focusGeneration
  buffer.value = ''; validation.value = ''; submitted.value = false
  if (open) {
    await nextTick()
    if (props.modelValue && generation === focusGeneration) input.value?.focus()
  }
}, { immediate: true })
function read() {
  if (!props.modelValue || props.busy || submitted.value) return
  const uid = normalizeCardInput(buffer.value)
  if (uid === null) { validation.value = '请读取 1–64 位数字卡号，不含空格'; return }
  validation.value = ''; submitted.value = true; emit('read', uid)
}
function close() {
  // ElDialog also emits false after a programmatic close finishes animating.
  // That notification is not a cancellation of the successfully scanned card.
  if (props.modelValue && !props.busy) emit('update:modelValue', false)
}
async function focusInput() {
  const generation = focusGeneration
  // ElDialog focuses its container on the tick following open-auto-focus.
  await nextTick(); await nextTick()
  if (props.modelValue && generation === focusGeneration) input.value?.focus()
}
</script>

<template>
  <el-dialog :model-value="modelValue" title="读取实体卡" width="420px" :close-on-click-modal="false" :close-on-press-escape="false" @open-auto-focus="focusInput" @update:model-value="close">
    <p>将光标留在卡号输入框，刷卡后按 Enter 完成读取。</p>
    <el-input ref="input" v-model="buffer" name="card_uid" autocomplete="off" inputmode="numeric" :disabled="busy" @input="submitted = false; validation = ''" @keydown.enter.stop.prevent="read" @keydown.esc.stop.prevent="close" />
    <el-alert v-if="validation || error" :title="validation || error" type="error" :closable="false" />
    <template #footer><el-button @click="close" :disabled="busy">取消</el-button><el-button type="primary" :disabled="busy || submitted" @click="read">读取卡号</el-button></template>
  </el-dialog>
</template>
